"""Offline configuration, speech and capture regressions. No hardware use."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from friday.config.settings import settings
from friday.main import cli_main, main
from friday.memory import MemoryManager
from friday.voice.backend import LocalVoiceBackend, VoiceConfiguration, VoiceError
from friday.voice.configuration import (TINY_EN_SHA256, configuration_path, dependency_directory,
    inspect_configuration, resolve_configuration)
from friday.voice.cli import voice_turn
from friday.voice.tts import EspeakNGBackend, SpeechError, automatic_speech_allowed, speak_turn, MAX_SPEECH_BYTES


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root/'config'),
                                          'XDG_DATA_HOME': str(self.root/'data')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path = configuration_path()
        self.data = dict(version=1, binary=str(self.root/'whisper-cli'),
                         model=str(self.root/'ggml-tiny.en.bin'), model_sha256=TINY_EN_SHA256)

    def save(self, data=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data if data is None else data))
        self.path.chmod(0o600)

    def test_xdg_paths(self):
        self.assertEqual(self.path, self.root/'config/friday/voice.json')
        self.assertEqual(dependency_directory(), self.root/'data/friday/voice')

    def test_relative_xdg_ignored(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative', 'XDG_DATA_HOME': 'relative'}), \
             patch('friday.voice.configuration.Path.home', return_value=self.root):
            self.assertEqual(configuration_path(), self.root/'.config/friday/voice.json')
            self.assertEqual(dependency_directory(), self.root/'.local/share/friday/voice')

    def test_no_configuration_no_backend(self):
        self.assertIsNone(resolve_configuration())

    def test_saved_configuration_discovery_is_lazy(self):
        self.save()
        with patch('friday.voice.backend.subprocess.Popen') as process:
            configuration = resolve_configuration()
            LocalVoiceBackend(configuration)
        self.assertEqual(configuration.binary, self.root/'whisper-cli')
        process.assert_not_called()

    def test_each_cli_field_overrides_saved_value(self):
        self.save()
        self.assertEqual(resolve_configuration(binary=self.root/'override').binary, self.root/'override')
        self.assertEqual(resolve_configuration(model=self.root/'other').model, self.root/'other')
        self.assertEqual(resolve_configuration(model_sha256=TINY_EN_SHA256).model_sha256, TINY_EN_SHA256)

    def test_complete_cli_recovers_from_malformed_saved_file(self):
        self.save()
        self.path.write_text('bad json')
        result = resolve_configuration(binary=self.root/'explicit', model=self.root/'model', model_sha256=TINY_EN_SHA256)
        self.assertEqual(result.binary, self.root/'explicit')

    def test_partial_cli_without_saved_file_is_incomplete(self):
        with self.assertRaisesRegex(VoiceError, 'incomplete'):
            resolve_configuration(binary=self.root/'binary')

    def test_invalid_schema_and_types(self):
        for data in ([], {'version':1}, dict(self.data, version=True), dict(self.data, extra='bad'),
                     dict(self.data, binary=None), dict(self.data, model=13)):
            self.save(data)
            with self.assertRaises(VoiceError):
                resolve_configuration()

    def test_unapproved_hash_rejected(self):
        for value in ('', '0'*64, 'BASE.EN', None):
            self.save(dict(self.data, model_sha256=value))
            with self.assertRaises(VoiceError):
                resolve_configuration()

    def test_relative_and_control_paths_rejected(self):
        for value in ('whisper-cli', '', '/tmp/bin\x1b[2J', '/tmp/bin\n'):
            self.save(dict(self.data, binary=value))
            with self.assertRaises(VoiceError):
                resolve_configuration()

    def test_shell_syntax_is_literal_path(self):
        value = str(self.root/'$(touch forbidden);whisper')
        self.save(dict(self.data, binary=value))
        with patch('friday.voice.backend.subprocess.Popen') as process:
            result = inspect_configuration(resolve_configuration(), self.path)
        self.assertEqual(result['binary'],value)
        self.assertEqual(result['status'],'unavailable')
        process.assert_not_called()

    def test_duplicate_keys_and_oversize_rejected(self):
        self.save()
        for raw in ('{"version":1,"version":1}', 'x'*4097):
            self.path.write_text(raw)
            with self.assertRaises(VoiceError):
                resolve_configuration()

    def test_symlink_and_other_user_writable_rejected(self):
        self.save()
        self.path.chmod(0o666)
        with self.assertRaises(VoiceError):
            resolve_configuration()
        target = self.root/'real-config'
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(VoiceError):
            resolve_configuration()

    def test_missing_binary_and_missing_model_distinguished(self):
        self.save()
        config = resolve_configuration()
        with self.assertRaisesRegex(VoiceError, 'executable unavailable'):
            LocalVoiceBackend(config).verify()
        config.binary.write_text('fake executable')
        config.binary.chmod(0o700)
        with self.assertRaisesRegex(VoiceError, 'model unavailable'):
            LocalVoiceBackend(config).verify()

    def test_real_checksum_match_and_mismatch_without_subprocess(self):
        binary = self.root/'binary'
        binary.write_text('fake executable')
        binary.chmod(0o700)
        model = self.root/'model'
        model.write_bytes(b'fixture model')
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        config = VoiceConfiguration(binary, model, digest)
        with patch('friday.voice.backend.subprocess.Popen') as process:
            LocalVoiceBackend(config).verify()
            with self.assertRaisesRegex(VoiceError, 'integrity check failed'):
                LocalVoiceBackend(replace(config, model_sha256='0'*64)).verify()
        process.assert_not_called()

    def test_nonregular_model_rejected_without_opening(self):
        binary=self.root/'binary'
        binary.write_text('fake executable');binary.chmod(0o700)
        fifo=self.root/'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(VoiceError,'model unavailable'):
            LocalVoiceBackend(VoiceConfiguration(binary,fifo,TINY_EN_SHA256)).verify()

    def test_nonexecutable_binary_refused_before_model_or_capture(self):
        self.save()
        config=resolve_configuration()
        config.binary.write_text('not executable');config.binary.chmod(0o600)
        with patch('friday.voice.backend.subprocess.Popen') as process:
            with self.assertRaisesRegex(VoiceError,'executable unavailable'):
                LocalVoiceBackend(config).verify()
        process.assert_not_called()

    def test_inspection_no_assistant_or_audio(self):
        self.save()
        with patch('friday.main.main') as assistant, patch('friday.voice.backend.subprocess.Popen') as process, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(cli_main(['--check-voice-config']),1)
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['microphone'],'OFF')
        assistant.assert_not_called()
        process.assert_not_called()

    def test_inspection_verified_files_label_does_not_claim_compatibility(self):
        self.save()
        with patch('friday.voice.backend.LocalVoiceBackend.verify'), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(cli_main(['--check-voice-config']),0)
        self.assertEqual(json.loads(output.getvalue())['status'],'verified_files')

    def test_invalid_configuration_text_fallback(self):
        self.save({'version':2})
        with patch('friday.main.main') as assistant:
            self.assertEqual(cli_main(['--adaptive']),0)
        self.assertIsNone(assistant.call_args.kwargs['voice_backend'])
        self.assertIn('invalid',assistant.call_args.kwargs['voice_notice'])
        self.assertTrue(assistant.call_args.kwargs['adaptive'])

    def test_cli_composition_with_saved_configuration_and_override(self):
        self.save()
        with patch('friday.main.main') as assistant:
            cli_main(['--voice-binary',str(self.root/'override')])
        backend = assistant.call_args.kwargs['voice_backend']
        self.assertEqual(backend.configuration.binary,self.root/'override')
        self.assertEqual(backend.configuration.model,self.root/'ggml-tiny.en.bin')


class SpeechTests(unittest.TestCase):
    def child(self):
        child = Mock(returncode=0)
        child.poll.return_value = 0
        child.communicate.return_value = (None,b'')
        return child

    def run_speech(self, text='Hello, I am FRIDAY.', child=None):
        child = self.child() if child is None else child
        with patch('friday.voice.tts.Path.is_file',return_value=True), \
             patch('friday.voice.tts.os.access',return_value=True), \
             patch('friday.voice.tts.subprocess.Popen',return_value=child) as process:
            EspeakNGBackend().speak(text)
        return process, child

    def test_plain_text_stdin_no_shell_no_text_in_argv(self):
        text = '--help; $(touch /tmp/forbidden) <audio src="private.wav"/>'
        process, child = self.run_speech(text)
        args = process.call_args.args[0]
        self.assertEqual(args[0],'/usr/bin/espeak-ng')
        self.assertIn('--stdin',args)
        self.assertNotIn('-m',args)
        self.assertNotIn(text,str(args))
        self.assertFalse(process.call_args.kwargs.get('shell',False))
        self.assertTrue(process.call_args.kwargs['start_new_session'])
        self.assertEqual([call.kwargs for call in child.communicate.call_args_list],
                         [{'input':text.encode(),'timeout':60},{'timeout':2}])

    def test_invalid_text_never_launches(self):
        with patch('friday.voice.tts.subprocess.Popen') as process:
            for text in ('', ' ', 'a'*(MAX_SPEECH_BYTES+1), '\x1b[2J', 'one\ntwo', None):
                with self.assertRaises(SpeechError):
                    EspeakNGBackend().speak(text)
        process.assert_not_called()

    def test_utf8_byte_limit(self):
        with self.assertRaises(SpeechError):
            EspeakNGBackend().speak('é'*(MAX_SPEECH_BYTES//2+1))

    def test_ordinary_answer_beyond_old_manual_limit(self):
        process,child=self.run_speech('a'*2000)
        self.assertEqual(child.communicate.call_args_list[0].kwargs['input'],b'a'*2000)

    def test_missing_binary(self):
        with patch('friday.voice.tts.Path.is_file',return_value=False), patch('friday.voice.tts.subprocess.Popen') as process:
            with self.assertRaisesRegex(SpeechError,'owner approval'):
                EspeakNGBackend().speak('Hello')
        process.assert_not_called()

    def test_audio_error_with_nonzero_exit(self):
        child = self.child()
        child.returncode = 1
        with self.assertRaisesRegex(SpeechError,'audio device'):
            self.run_speech(child=child)

    def test_audio_diagnostic_even_with_zero_exit(self):
        child = self.child()
        child.communicate.return_value=(None,b'PRIVATE TEXT: audio error')
        with self.assertRaises(SpeechError) as error:
            self.run_speech(child=child)
        self.assertNotIn('PRIVATE TEXT',str(error.exception))

    def test_timeout_cleanup(self):
        child = self.child()
        child.communicate.side_effect = subprocess.TimeoutExpired('fake',60)
        with patch('friday.voice.tts.stop_process') as stop:
            with self.assertRaisesRegex(SpeechError,'timed out'):
                self.run_speech(child=child)
        stop.assert_called_once_with(child)

    def test_interrupt_cleanup_and_return_to_cli(self):
        child = self.child()
        child.communicate.side_effect = KeyboardInterrupt
        output=[]
        with patch('friday.voice.tts.Path.is_file',return_value=True), \
             patch('friday.voice.tts.os.access',return_value=True), \
             patch('friday.voice.tts.subprocess.Popen',return_value=child), \
             patch('friday.voice.tts.stop_process') as stop:
            speak_turn('Hello', write=output.append)
        stop.assert_called_once_with(child)
        self.assertIn('cancelled',output[0])

    def test_shutdown_unwinds_child_cleanup(self):
        child=self.child()
        child.communicate.side_effect=SystemExit(143)
        with patch('friday.voice.tts.stop_process') as stop:
            with self.assertRaises(SystemExit):
                self.run_speech(child=child)
        stop.assert_called_once_with(child)

    def test_unexpected_error_redacted(self):
        backend=Mock()
        backend.speak.side_effect=RuntimeError('PRIVATE TEXT')
        output=[]
        speak_turn('Hello',backend,write=output.append)
        self.assertNotIn('PRIVATE',str(output))

    def test_untrusted_response_labels_never_authorize_speech(self):
        for category in (None,'greeting','trusted','file_content','permission','model_answer',object()):
            self.assertFalse(automatic_speech_allowed(category))


class SpeechCLITests(unittest.TestCase):
    def run_cli(self, commands, speech=None):
        speech = Mock() if speech is None else speech
        with tempfile.TemporaryDirectory() as directory, \
             patch('friday.main.settings', replace(settings,database_path=Path(directory)/'memory.db')), \
             patch('friday.main.OllamaProvider') as provider, \
             patch('builtins.input',side_effect=commands), patch('sys.stdout',new_callable=io.StringIO) as output, \
             patch('friday.voice.backend.LocalVoiceBackend.capture') as capture:
            provider.return_value.chat.return_value='Ordinary reply'
            main(speech_backend=speech)
            with MemoryManager(Path(directory)/'memory.db') as memory:
                messages = memory.get_recent_messages(100)
            capture.assert_not_called()
            return speech, provider.return_value, output.getvalue(), messages

    def test_explicit_speak_no_model_or_persistence(self):
        speech, provider, _, messages = self.run_cli(['/speak Hello, I am FRIDAY.','quit'])
        speech.speak.assert_called_once_with('Hello, I am FRIDAY.')
        provider.chat.assert_not_called()
        self.assertEqual(messages,[])

    def test_normal_reply_spoken_once_without_startup_speech(self):
        speech, provider, _, messages = self.run_cli(['hello','quit'])
        speech.speak.assert_called_once_with('Ordinary reply')
        self.assertEqual(provider.chat.call_count,1)
        self.assertEqual(len(messages),2)

    def test_speak_cancel_keeps_text_cli_working(self):
        speech=Mock()
        speech.speak.side_effect=KeyboardInterrupt
        _, provider, output, messages = self.run_cli(['/speak Hello','hello','quit'],speech)
        self.assertIn('Speech cancelled',output)
        self.assertEqual(provider.chat.call_count,1)
        self.assertEqual([m.content for m in messages],['hello','Ordinary reply'])

    def test_speech_error_is_not_stored(self):
        speech=Mock()
        speech.speak.side_effect=SpeechError('Offline speech output timed out.')
        _, provider, output, messages = self.run_cli(['/speak Hello','quit'],speech)
        self.assertIn('timed out',output)
        self.assertEqual(messages,[])
        provider.chat.assert_not_called()

    def test_public_voice_reply_spoken_once(self):
        speech=Mock()
        voice=Mock()
        voice.transcribe.return_value='Hello Friday.'
        with tempfile.TemporaryDirectory() as directory, \
             patch('friday.main.settings',replace(settings,database_path=Path(directory)/'memory.db')), \
             patch('friday.main.OllamaProvider') as provider, \
             patch('builtins.input',side_effect=['/voice','','y','quit']), \
             patch('sys.stdout',new_callable=io.StringIO), \
             patch('friday.voice.startup.StartupGreeting.greet', return_value=False), patch('sys.stdin.isatty',return_value=True), patch('sys.stdout.isatty',return_value=True):
            provider.return_value.chat.return_value='Safe greeting'
            main(voice_backend=voice,speech_backend=speech)
            with MemoryManager(Path(directory)/'memory.db') as memory:
                self.assertEqual(memory.get_recent_messages(100),[])
        speech.speak.assert_called_once_with('Safe greeting')

    def test_spoken_cli_speak_command_never_dispatched(self):
        voice=Mock()
        voice.transcribe.return_value='/speak Secret text'
        assistant=Mock()
        with patch('friday.voice.tts.EspeakNGBackend') as speech:
            voice_turn(assistant,voice,read=Mock(side_effect=['','y']),write=Mock(),interactive=True)
        assistant.respond.assert_called_once_with('/speak Secret text',persist=False)
        speech.assert_not_called()


class CaptureWindowTests(unittest.TestCase):
    def config(self):
        return VoiceConfiguration(Path('/missing/binary'),Path('/missing/model'),'0'*64)

    def fixture(self):
        return ['id: ALC256 Analog\nstream: CAPTURE','closed',
                'state: RUNNING\nowner_pid: 123\nhw_ptr: 100',
                'state: RUNNING\nowner_pid: 123\nhw_ptr: 200',
                'format: S16_LE\nchannels: 2\nrate: 48000 (48000/1)',
                'state: RUNNING\nowner_pid: 123\nhw_ptr: 400']

    def execute(self, child, events, texts=None):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.wav'
            with wave.open(str(path),'wb') as audio:
                audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(48000)
                audio.writeframes(b'\0'*48000*12*4)
            with patch('friday.voice.backend.Path.read_text',side_effect=texts or self.fixture()), \
                 patch('friday.voice.backend.subprocess.Popen',return_value=child) as process, \
                 patch('friday.voice.backend.time.sleep'), \
                 patch('friday.voice.backend.time.monotonic',side_effect=[0,0,0,0,0,0 if child.communicate.side_effect is None else 8]), \
                 patch('friday.voice.backend.os.killpg') as kill, patch('friday.voice.backend.stop_process') as stop:
                LocalVoiceBackend(self.config()).capture(path,events.append)
        return process, kill, stop

    def child(self):
        child=Mock(pid=123,returncode=0)
        child.poll.return_value=None
        return child

    def test_full_window_starts_after_cue(self):
        events=[]
        child=self.child()
        def communicate(**kwargs):
            events.append(('wait',kwargs['timeout']))
            if kwargs['timeout']==8:
                raise subprocess.TimeoutExpired('capture',8)
            return b'',b''
        child.communicate.side_effect=communicate
        process, kill, stop = self.execute(child,events)
        self.assertLess(events.index('CAPTURE READY — SPEAK NOW'),events.index(('wait',8)))
        self.assertIn(('wait',4),events)
        args=process.call_args.args[0]
        self.assertEqual(args[args.index('-d')+1],'12')
        kill.assert_not_called()
        stop.assert_called_once_with(child)

    def test_early_completion_rejected(self):
        child=self.child()
        child.communicate.return_value=(b'',b'')
        with patch('friday.voice.backend.time.monotonic',return_value=0), self.assertRaisesRegex(VoiceError,'full speech window'):
            self.execute(child,[])

    def test_stalled_after_settling_refuses_cue(self):
        texts=self.fixture()
        texts[-1]=texts[-1].replace('400','200')
        events=[]
        with self.assertRaisesRegex(VoiceError,'before speech cue'):
            self.execute(self.child(),events,texts)
        self.assertNotIn('CAPTURE READY — SPEAK NOW',events)

    def test_capture_interrupt_stops_process(self):
        child=self.child()
        child.communicate.side_effect=KeyboardInterrupt
        with patch('friday.voice.backend.Path.read_text',side_effect=self.fixture()), \
             patch('friday.voice.backend.subprocess.Popen',return_value=child), \
             patch('friday.voice.backend.time.sleep'), patch('friday.voice.backend.stop_process') as stop:
            with self.assertRaises(KeyboardInterrupt):
                LocalVoiceBackend(self.config()).capture(Path('/unused'),Mock())
        stop.assert_called_once_with(child)

    def test_preroll_preserved_and_total_wav_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'audio.wav'
            child=self.child()
            child.poll.return_value=0
            child.communicate.return_value=(b'Hello',b'')
            for seconds, accepted in ((10,True),(13,False)):
                with wave.open(str(path),'wb') as audio:
                    audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(48000)
                    audio.writeframes(b'\0'*48000*seconds*4)
                with patch('friday.voice.backend.subprocess.Popen',return_value=child):
                    if accepted:
                        self.assertEqual(LocalVoiceBackend(self.config()).transcribe(path),'Hello')
                    else:
                        with self.assertRaises(VoiceError):
                            LocalVoiceBackend(self.config()).transcribe(path)
