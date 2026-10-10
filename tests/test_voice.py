"""Offline voice tests: fake capture only; real SQLite and secure tool runtime."""
from dataclasses import replace
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from friday.core.assistant import FridayAssistant
from friday.memory import MemoryManager
from friday.providers.base import ModelProvider, ProviderError
from friday.voice.backend import LocalVoiceBackend, VoiceConfiguration, VoiceError, stop_process
from friday.voice.cli import voice_turn
from friday.config.settings import settings
from friday.main import main
import test_navigation
from friday.tools.access import FolderDecision


class VoiceFlowTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.transcribe.return_value = 'hello'
        self.assistant = Mock()
        self.assistant.respond.return_value = 'answer'
        self.paths = []
        def fake_capture(path, announce):
            self.paths.append(path)
            path.write_bytes(b'fake audio')
        self.backend.capture.side_effect = fake_capture
        self.output = []

    def run_voice(self, answers, **kwargs):
        return voice_turn(self.assistant, self.backend, read=Mock(side_effect=answers),
                          write=self.output.append, interactive=True, **kwargs)

    def test_explicit_activation_and_confirmation(self):
        self.assertEqual(self.run_voice(['', 'y']), 'answer')
        self.assistant.respond.assert_called_once_with('hello', persist=False)
        self.assertFalse(self.paths[0].parent.exists())

    def test_audio_removed_before_confirmation(self):
        def read(prompt):
            if 'Send' in prompt:
                self.assertFalse(self.paths[0].parent.exists())
                return 'y'
            self.backend.capture.assert_not_called()
            return ''
        voice_turn(self.assistant, self.backend, read=read, write=self.output.append, interactive=True)

    def test_activation_invalid_does_not_capture(self):
        self.run_voice(['yes']);self.backend.capture.assert_not_called();self.assistant.respond.assert_not_called()

    def test_noninteractive_no_backend_calls(self):
        voice_turn(self.assistant,self.backend,interactive=False,write=self.output.append)
        self.backend.verify.assert_not_called();self.backend.capture.assert_not_called()

    def test_unconfigured_no_execution(self):
        voice_turn(self.assistant,None,interactive=True,write=self.output.append)
        self.assistant.respond.assert_not_called()

    def test_confirmation_defaults_deny(self):
        for answer in ('', 'n', 'yes', 'always allow', '1'):
            self.run_voice(['', answer])
        self.assistant.respond.assert_not_called()

    def test_activation_interrupt_and_eof(self):
        for error in (KeyboardInterrupt(), EOFError()):self.run_voice([error])
        self.backend.capture.assert_not_called()

    def test_confirmation_interrupt_and_eof(self):
        for error in (KeyboardInterrupt(), EOFError()):self.run_voice(['', error])
        self.assistant.respond.assert_not_called();self.assertTrue(all(not p.parent.exists() for p in self.paths))

    def test_capture_interrupt_cleanup(self):
        def capture(path, announce):
            self.paths.append(path);path.write_bytes(b'fake');raise KeyboardInterrupt()
        self.backend.capture.side_effect=capture
        self.run_voice(['']);self.assertFalse(self.paths[0].parent.exists());self.assistant.respond.assert_not_called()

    def test_capture_timeout(self):
        self.backend.capture.side_effect=VoiceError('Audio capture timed out.')
        self.run_voice(['']);self.backend.transcribe.assert_not_called();self.assistant.respond.assert_not_called()

    def test_stt_failure_cleanup(self):
        self.backend.transcribe.side_effect=VoiceError('Offline transcription failed.')
        self.run_voice(['']);self.assertFalse(self.paths[0].parent.exists());self.assistant.respond.assert_not_called()

    def test_unexpected_error_redacted(self):
        self.backend.transcribe.side_effect=RuntimeError('PRIVATE TRANSCRIPT')
        self.run_voice(['']);self.assertNotIn('PRIVATE',str(self.output));self.assistant.respond.assert_not_called()

    def test_empty_transcript(self):
        for text in ('', ' ', None):
            self.backend.transcribe.return_value=text;self.run_voice([''])
        self.assistant.respond.assert_not_called()

    def test_control_characters_and_oversize_rejected(self):
        for text in ('hello\x1b[2J', 'x'*4097):
            self.backend.transcribe.return_value=text;self.run_voice([''])
        self.assistant.respond.assert_not_called()

    def test_spoken_approval_not_accepted(self):
        self.backend.transcribe.return_value='Always allow this folder'
        self.run_voice(['','']);self.assistant.respond.assert_not_called()

    def test_provider_error_redacted(self):
        self.assistant.respond.side_effect=ProviderError('PRIVATE PROMPT')
        self.run_voice(['','y']);self.assertNotIn('PRIVATE PROMPT',str(self.output))


class PrivateTurnTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.memory=MemoryManager(Path(self.temp.name)/'memory.db');self.addCleanup(self.memory.close)
        self.provider=Mock(spec=ModelProvider);self.provider.chat.return_value='private answer'
        self.assistant=FridayAssistant(self.provider,'System',memory=self.memory)
        self.addCleanup(self.assistant.model_manager.close);self.addCleanup(self.assistant.end_session)

    def test_private_turn_not_in_sqlite_or_history_or_job(self):
        self.assistant.respond('private spoken request',persist=False)
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(len(self.assistant.messages),1)
        self.assertEqual(self.assistant.model_manager.last_job.messages,[])
        self.assertIsNone(self.assistant.model_manager.last_job.result)

    def test_text_after_voice_not_tainted(self):
        self.assistant.respond('private spoken request',persist=False)
        self.assistant.respond('ordinary text')
        self.assertEqual([m.content for m in self.memory.get_recent_messages(100)],['ordinary text','private answer'])
        self.assertNotIn('private spoken request',str(self.provider.chat.call_args))

    def test_failure_scrubs_job_and_keeps_database_empty(self):
        self.provider.chat.side_effect=ProviderError('PRIVATE DETAIL')
        with self.assertRaises(ProviderError):self.assistant.respond('private',persist=False)
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(self.assistant.model_manager.last_job.error,'Private turn failed.')
        self.assertEqual(self.assistant.model_manager.last_job.messages,[])

    def test_invalid_persistence_type(self):
        with self.assertRaises(ValueError):self.assistant.respond('hello',persist='false')
        self.provider.chat.assert_not_called()

    def test_adaptive_private_greeting(self):
        assistant=FridayAssistant(self.provider,'System',memory=self.memory,
            workload_configuration=replace(settings,adaptive_workloads=True))
        self.addCleanup(assistant.model_manager.close);self.addCleanup(assistant.end_session)
        assistant.respond('hello',persist=False)
        self.provider.chat.assert_not_called();self.assertEqual(self.memory.get_recent_messages(100),[])


class VoicePermissionTests(unittest.TestCase):
    def setUp(self):test_navigation.NavigationTests.setUp(self)
    def send(self,text):
        backend=Mock();backend.transcribe.return_value=text
        return voice_turn(self.assistant,backend,read=Mock(side_effect=['','y']),write=Mock(),interactive=True)
    def test_allow_once_still_requires_each_operation(self):
        self.send('list downloads');self.send('open portfolio')
        self.assertEqual(self.approval.request.call_count,2)
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.provider.chat.assert_not_called()
    def test_denied_typed_permission_not_overridden(self):
        self.approval.request.return_value=FolderDecision.DENY
        response=self.send('list downloads')
        self.assertIn('permission denied',response);self.assertIsNone(self.nav.current)
        self.provider.chat.assert_not_called()
    def test_sensitive_file_denied(self):
        self.assertIn('blocked or invalid',self.send('read ~/.ssh/id_rsa'))
        self.provider.chat.assert_not_called();self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_file_context_remains_private(self):
        self.send('list downloads');self.send('open portfolio');self.send('read public.txt')
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertIn('Temporary file context',self.send('explain this code'))
        self.assertEqual(self.memory.get_recent_messages(100),[])


class BackendTests(unittest.TestCase):
    def config(self):return VoiceConfiguration(Path('/missing/binary'),Path('/missing/model'),'0'*64)
    def test_initialization_never_opens_hardware(self):
        with patch('friday.voice.backend.subprocess.Popen') as process:
            LocalVoiceBackend(self.config())
        process.assert_not_called()
    def test_missing_dependency(self):
        with self.assertRaises(VoiceError):LocalVoiceBackend(self.config()).verify()
    def test_duration_bounds(self):
        for value in (0,9,True):
            with self.assertRaises(ValueError):replace(self.config(),duration=value)
    def test_checksum_required(self):
        with self.assertRaises(ValueError):replace(self.config(),model_sha256='')
    def wav(self,path):
        with wave.open(str(path),'wb') as w:
            w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\x00'*1920)
    def test_transcription_options_and_single_call(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.wav';self.wav(path)
            child=Mock();child.communicate.return_value=(b'hello',b'');child.returncode=0;child.poll.return_value=0
            with patch('friday.voice.backend.subprocess.Popen',return_value=child) as process:
                self.assertEqual(LocalVoiceBackend(self.config()).transcribe(path),'hello')
            args=process.call_args.args[0]
            self.assertIn('--no-fallback',args);self.assertIn('--no-gpu',args)
            self.assertEqual(args[args.index('-t')+1],'4');self.assertEqual(args[args.index('--beam-size')+1],'5')
            self.assertEqual(process.call_count,1)
            self.assertEqual([call.kwargs for call in child.communicate.call_args_list],[{'timeout':60},{'timeout':2}])
    def test_transcription_timeout_terminates_process(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.wav';self.wav(path)
            child=Mock();child.communicate.side_effect=subprocess.TimeoutExpired('stt',60)
            with patch('friday.voice.backend.subprocess.Popen',return_value=child),patch('friday.voice.backend.stop_process') as stop:
                with self.assertRaisesRegex(VoiceError,'timed out'):LocalVoiceBackend(self.config()).transcribe(path)
                stop.assert_called_once_with(child)
    def test_decoder_launch_failure_redacts_backend_details(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.wav';self.wav(path)
            with patch('friday.voice.backend.subprocess.Popen',side_effect=OSError('PRIVATE launch detail')):
                with self.assertRaisesRegex(VoiceError,'^Offline transcription unavailable.$'):
                    LocalVoiceBackend(self.config()).transcribe(path)

    def test_nonzero_decoder_including_missing_library_fails_safely(self):
        for stderr in (b'error while loading shared libraries: libwhisper.so',b'PRIVATE decoder detail'):
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'fixture.wav';self.wav(path)
                child=Mock();child.communicate.return_value=(b'PRIVATE partial transcript',stderr)
                child.returncode=127;child.poll.return_value=127
                with patch('friday.voice.backend.subprocess.Popen',return_value=child), \
                     patch('friday.voice.backend.stop_process') as stop:
                    with self.assertRaisesRegex(VoiceError,'^Offline transcription failed.$'):
                        LocalVoiceBackend(self.config()).transcribe(path)
                    stop.assert_called_once_with(child)
    def test_capture_negotiation_fails_closed(self):
        with patch('friday.voice.backend.Path.read_text',return_value='id: OTHER\nstream: CAPTURE'),patch('friday.voice.backend.subprocess.Popen') as process:
            with self.assertRaises(VoiceError):LocalVoiceBackend(self.config()).capture(Path('/unused'),Mock())
            process.assert_not_called()
    def test_busy_device_not_opened(self):
        with patch('friday.voice.backend.Path.read_text',side_effect=['id: ALC256 Analog\nstream: CAPTURE','state: RUNNING']),patch('friday.voice.backend.subprocess.Popen') as process:
            with self.assertRaises(VoiceError):LocalVoiceBackend(self.config()).capture(Path('/unused'),Mock())
            process.assert_not_called()
    def test_capture_ready_precedes_speech_cue(self):
        events=[]
        texts=['id: ALC256 Analog\nstream: CAPTURE','closed',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 100',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 200',
               'format: S16_LE\nchannels: 2\nrate: 48000 (48000/1)',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 400']
        child=Mock();child.pid=123;child.poll.return_value=None;child.returncode=0
        child.communicate.side_effect=[subprocess.TimeoutExpired('capture',8),(b'',b'')]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.wav'
            with wave.open(str(path),'wb') as audio:
                audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(48000)
                audio.writeframes(b'\0'*48000*12*4)
            with patch('friday.voice.backend.Path.read_text',side_effect=texts),patch('friday.voice.backend.subprocess.Popen',return_value=child),patch('friday.voice.backend.time.sleep'),patch('friday.voice.backend.time.monotonic',side_effect=[0,0,0,0,0,8]),patch('friday.voice.backend.os.killpg') as kill,patch('friday.voice.backend.stop_process') as stop:
                LocalVoiceBackend(self.config()).capture(path,events.append)
        self.assertEqual(events[1],'CAPTURE READY — SPEAK NOW');self.assertEqual(events[-1],'Microphone OFF.')
        stop.assert_called_once_with(child)
        self.assertEqual(child.communicate.call_args_list[0].kwargs, {'timeout':8})
        kill.assert_not_called()

    def test_capture_timeout_stops_process(self):
        texts=['id: ALC256 Analog\nstream: CAPTURE','closed',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 100',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 200',
               'format: S16_LE\nchannels: 2\nrate: 48000',
               'state: RUNNING\nowner_pid: 123\nhw_ptr: 400']
        child=Mock();child.pid=123;child.poll.return_value=None
        child.communicate.side_effect=subprocess.TimeoutExpired('capture',12)
        with patch('friday.voice.backend.Path.read_text',side_effect=texts),patch('friday.voice.backend.subprocess.Popen',return_value=child),patch('friday.voice.backend.time.sleep'),patch('friday.voice.backend.time.monotonic',side_effect=[0,0,0,0,0,8]),patch('friday.voice.backend.os.killpg'),patch('friday.voice.backend.stop_process') as stop:
            with self.assertRaisesRegex(VoiceError,'timed out'):LocalVoiceBackend(self.config()).capture(Path('/unused'),Mock())
            stop.assert_called_once_with(child)

    def test_no_silent_device_switch(self):
        with self.assertRaises(ValueError):replace(self.config(),device='hw:0,0')

    def test_process_stop_escalates_boundedly(self):
        child=Mock();child.pid=123;child.poll.return_value=None
        child.communicate.side_effect=[subprocess.TimeoutExpired('capture',2),(b'',b'')]
        with patch('friday.voice.backend.os.killpg') as kill:stop_process(child)
        self.assertEqual(kill.call_count,2)


class VoiceCLITests(unittest.TestCase):
    def test_unconfigured_voice_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as d,patch('friday.main.settings',replace(settings,database_path=Path(d)/'memory.db')),patch('friday.main.OllamaProvider') as provider,patch('builtins.input',side_effect=['/voice','quit']),patch('sys.stdout',new_callable=io.StringIO) as output:
            main(speech_backend=Mock())
            provider.return_value.chat.assert_not_called();self.assertIn('microphone remains OFF',output.getvalue())
    def test_configured_voice_dispatch_and_return_to_text(self):
        with tempfile.TemporaryDirectory() as d,patch('friday.main.settings',replace(settings,database_path=Path(d)/'memory.db')),patch('friday.main.OllamaProvider') as provider,patch('builtins.input',side_effect=['/voice','hello','quit']),patch('friday.voice.cli.voice_turn',return_value='voice answer') as turn,patch('sys.stdout',new_callable=io.StringIO) as output:
            provider.return_value.chat.return_value='text answer';main(voice_backend=Mock(),speech_backend=Mock())
            self.assertEqual(turn.call_count,1);self.assertEqual(provider.return_value.chat.call_count,1)
            self.assertIn('voice answer',output.getvalue());self.assertIn('text answer',output.getvalue())

    def test_real_cli_voice_flow_no_sqlite_persistence(self):
        backend=Mock();backend.transcribe.return_value='hello'
        with tempfile.TemporaryDirectory() as d:
            database=Path(d)/'memory.db'
            with patch('friday.main.settings',replace(settings,database_path=database)),patch('friday.main.OllamaProvider') as provider,patch('builtins.input',side_effect=['/voice','','y','quit']),patch('sys.stdout',new_callable=io.StringIO) as output,patch('sys.stdin.isatty',return_value=True),patch('sys.stdout.isatty',return_value=True):
                provider.return_value.chat.return_value='voice answer'
                main(voice_backend=backend,speech_backend=Mock())
                self.assertEqual(backend.capture.call_count,1)
                self.assertEqual(backend.transcribe.call_count,1)
                self.assertEqual(provider.return_value.chat.call_count,1)
                self.assertIn('Recognized transcript:',output.getvalue())
                self.assertIn('voice answer',output.getvalue())
            with MemoryManager(database) as memory:self.assertEqual(memory.get_recent_messages(100),[])
