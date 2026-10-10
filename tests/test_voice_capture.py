"""Capture lifecycle fixtures: synthetic files/processes only, no audio devices."""
from contextlib import ExitStack
from pathlib import Path
import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from friday.voice.backend import (LocalVoiceBackend, ProcessCleanupError,
                                  VoiceConfiguration, VoiceError, stop_process, validate_wav)
from friday.voice.cli import voice_turn


def wav(path, frames=48000*12, *, channels=2, width=2, rate=48000):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(channels); audio.setsampwidth(width); audio.setframerate(rate)
        audio.writeframes(b'\0' * frames * channels * width)


class Clock:
    def __init__(self): self.now=0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now+=seconds


class Recorder:
    """Only writes the final WAV on process completion; tracks reap/signals."""
    pid=123
    def __init__(self, clock, path, outcome='natural', output=None):
        self.clock=clock; self.path=path; self.outcome=outcome; self.output=output or wav
        self.returncode=None; self.reaped=False; self.waits=[]; self.signals=[]; self.phase=0
    def poll(self): return self.returncode
    def communicate(self, timeout):
        self.waits.append(timeout)
        if self.returncode is not None:
            self.reaped=True
            return b'',b'PRIVATE backend diagnostic'
        if self.outcome=='cancel': raise KeyboardInterrupt
        if self.phase==0:
            self.phase=1
            if self.outcome in ('early','unexpected_int','device_error'):
                self.clock.now+=1
                self.returncode={'early':0,'unexpected_int':-signal.SIGINT,'device_error':1}[self.outcome]
                self.output(self.path); self.reaped=True
                return b'',b'PRIVATE backend diagnostic'
            self.clock.now+=timeout
            raise subprocess.TimeoutExpired('fake recorder',timeout)
        if self.outcome in ('ignore_int','hung'):
            self.clock.now+=timeout
            raise subprocess.TimeoutExpired('fake recorder',timeout)
        self.clock.now=12
        self.output(self.path); self.returncode=0; self.reaped=True
        return b'',b''
    def signal(self, pid, sig):
        assert pid==self.pid
        self.signals.append(sig)
        if sig==signal.SIGKILL:
            if self.outcome!='hung': self.returncode=-signal.SIGKILL
        elif self.outcome not in ('ignore_int','hung'):
            self.returncode=-signal.SIGINT


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'capture.wav'; self.clock=Clock(); self.events=[]
        self.config=VoiceConfiguration(Path('/unused/whisper'),Path('/unused/model'),'0'*64)
        self.texts=['id: ALC256 Analog\nstream: CAPTURE','closed',
                    'state: RUNNING\nowner_pid: 123\nhw_ptr: 100',
                    'state: RUNNING\nowner_pid: 123\nhw_ptr: 200',
                    'format: S16_LE\nchannels: 2\nrate: 48000 (48000/1)',
                    'state: RUNNING\nowner_pid: 123\nhw_ptr: 400']
    def run_capture(self, child, *, announce=None, texts=None):
        with ExitStack() as stack:
            process=stack.enter_context(patch('friday.voice.backend.subprocess.Popen',return_value=child))
            stack.enter_context(patch('friday.voice.backend.Path.read_text',side_effect=texts or self.texts))
            stack.enter_context(patch('friday.voice.backend.time.monotonic',self.clock.monotonic))
            stack.enter_context(patch('friday.voice.backend.time.sleep',self.clock.sleep))
            stack.enter_context(patch('friday.voice.backend.os.killpg',side_effect=child.signal))
            LocalVoiceBackend(self.config).capture(self.path,announce or self.events.append)
            return process
    def recorder(self, **kwargs): return Recorder(self.clock,self.path,**kwargs)
    def assert_off(self): self.assertEqual(self.events[-1],'Microphone OFF.')

    def test_natural_completion_has_full_window_and_finalized_wav(self):
        child=self.recorder(); cue=[]
        def announce(text):
            self.events.append(text)
            if text=='CAPTURE READY — SPEAK NOW':
                cue.append(self.clock.now); self.assertFalse(self.path.exists())
        process=self.run_capture(child,announce=announce)
        self.assertGreaterEqual(self.clock.now-cue[0],8)
        self.assertEqual(child.returncode,0); self.assertTrue(child.reaped)
        self.assertEqual(child.signals,[]); self.assertEqual(child.waits,[8,4,2])
        self.assertEqual(validate_wav(self.path,minimum_frames=576000,maximum_frames=576000),576000)
        args=process.call_args.args[0]
        self.assertEqual(args[:3],['/usr/bin/arecord','-D','hw:CARD=Generic_1,DEV=0'])
        self.assertIn('--fatal-errors',args); self.assertEqual(args[args.index('-d')+1],'12')
        self.assertTrue(process.call_args.kwargs['start_new_session']); self.assert_off()

    def test_early_normal_completion_rejected_even_with_valid_full_wav(self):
        child=self.recorder(outcome='early')
        with self.assertRaisesRegex(VoiceError,'full speech window'): self.run_capture(child)
        self.assertEqual(child.returncode,0); self.assertTrue(child.reaped); self.assert_off()

    def test_unexpected_sigint_not_accepted_even_with_valid_full_wav(self):
        child=self.recorder(outcome='unexpected_int')
        with self.assertRaisesRegex(VoiceError,'interrupted unexpectedly'): self.run_capture(child)
        self.assertEqual(child.returncode,-signal.SIGINT); self.assertEqual(child.signals,[]); self.assert_off()

    def test_device_error_redacted(self):
        child=self.recorder(outcome='device_error')
        with self.assertRaisesRegex(VoiceError,'device or recording became unavailable') as error:
            self.run_capture(child)
        self.assertNotIn('PRIVATE',str(error.exception)); self.assertEqual(child.returncode,1); self.assert_off()

    def test_exit_before_readiness(self):
        child=self.recorder(); child.returncode=1
        with self.assertRaisesRegex(VoiceError,'before readiness'): self.run_capture(child)
        self.assertNotIn('CAPTURE READY — SPEAK NOW',self.events)
        self.assertTrue(child.reaped); self.assert_off()

    def test_readiness_timeout_stops_and_reaps(self):
        child=self.recorder()
        # The second read must be closed; subsequent pointer reads never advance.
        calls=0
        def read(path):
            nonlocal calls
            calls+=1
            return self.texts[0] if calls==1 else 'closed' if calls==2 else 'state: RUNNING\nowner_pid: 123\nhw_ptr: 100'
        with patch('friday.voice.backend.Path.read_text',autospec=True,side_effect=read), \
             patch('friday.voice.backend.subprocess.Popen',return_value=child), \
             patch('friday.voice.backend.time.monotonic',self.clock.monotonic), \
             patch('friday.voice.backend.time.sleep',self.clock.sleep), \
             patch('friday.voice.backend.os.killpg',side_effect=child.signal):
            with self.assertRaisesRegex(VoiceError,'readiness could not be verified'):
                LocalVoiceBackend(self.config).capture(self.path,self.events.append)
        self.assertEqual(child.signals,[signal.SIGINT]); self.assertTrue(child.reaped); self.assert_off()

    def test_cue_delay_refused_and_reaped(self):
        child=self.recorder()
        def announce(text):
            self.events.append(text)
            if text=='CAPTURE READY — SPEAK NOW': self.clock.now+=4
        with self.assertRaisesRegex(VoiceError,'cue was delayed'): self.run_capture(child,announce=announce)
        self.assertTrue(child.reaped); self.assert_off()

    def test_owner_cancellation_interrupts_and_reaps(self):
        child=self.recorder(outcome='cancel')
        with self.assertRaises(KeyboardInterrupt): self.run_capture(child)
        self.assertEqual(child.signals,[signal.SIGINT]); self.assertTrue(child.reaped); self.assert_off()

    def test_natural_timeout_ignoring_sigint_is_killed_and_not_accepted(self):
        child=self.recorder(outcome='ignore_int')
        with self.assertRaisesRegex(VoiceError,'timed out'): self.run_capture(child)
        self.assertEqual(child.signals,[signal.SIGINT,signal.SIGKILL])
        self.assertEqual(child.returncode,-signal.SIGKILL); self.assertTrue(child.reaped); self.assert_off()

    def test_unreapable_child_reports_uncertainty_instead_of_false_off(self):
        child=self.recorder(outcome='hung')
        with self.assertRaisesRegex(ProcessCleanupError,'cleanup could not be confirmed'): self.run_capture(child)
        self.assertNotIn('Microphone OFF.',self.events)
        self.assertEqual(self.events[-1],'Microphone shutdown could not be confirmed.')
        self.assertEqual(child.signals,[signal.SIGINT,signal.SIGKILL])

    def test_missing_output_rejected(self):
        child=self.recorder(output=lambda _:None)
        with self.assertRaisesRegex(VoiceError,'file is missing'): self.run_capture(child)
        self.assertTrue(child.reaped); self.assert_off()

    def test_full_length_requirement_refuses_partial_recording(self):
        child=self.recorder(output=lambda p:wav(p,48000*8))
        with self.assertRaisesRegex(VoiceError,'frame count is incomplete'): self.run_capture(child)
        self.assertTrue(child.reaped); self.assert_off()

    def test_wrong_owner_pointer_refuses_ready_cue(self):
        child=self.recorder(); texts=self.texts.copy()
        texts[3]=texts[3].replace('123','999')
        # Return stale pointer indefinitely until timeout, never silently switch.
        texts=texts[:4]+[texts[3]]*110
        with self.assertRaisesRegex(VoiceError,'readiness could not be verified'): self.run_capture(child,texts=texts)
        self.assertNotIn('CAPTURE READY — SPEAK NOW',self.events); self.assert_off()


class WAVTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.wav'
    def validate(self): return validate_wav(self.path,maximum_frames=576000)
    def test_valid_wav(self):
        wav(self.path); self.assertEqual(self.validate(),576000)
    def test_missing_wav(self):
        with self.assertRaisesRegex(VoiceError,'missing'): self.validate()
    def test_corrupt_header(self):
        self.path.write_bytes(b'x'*44)
        with self.assertRaisesRegex(VoiceError,'header is invalid'): self.validate()
    def test_truncated_payload(self):
        wav(self.path); self.path.write_bytes(self.path.read_bytes()[:-4])
        with self.assertRaisesRegex(VoiceError,'incomplete or not finalized'): self.validate()
    def test_unfinalized_riff_header(self):
        wav(self.path); data=bytearray(self.path.read_bytes()); struct.pack_into('<I',data,4,0x7fffffff)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(VoiceError,'not finalized'): self.validate()
    def test_wrong_channels(self):
        wav(self.path,48000,channels=1)
        with self.assertRaisesRegex(VoiceError,'PCM format'): self.validate()
    def test_wrong_rate(self):
        wav(self.path,48000,rate=16000)
        with self.assertRaisesRegex(VoiceError,'PCM format'): self.validate()
    def test_wrong_width(self):
        wav(self.path,48000,width=1)
        with self.assertRaisesRegex(VoiceError,'PCM format'): self.validate()
    def test_inconsistent_byte_rate_refused(self):
        wav(self.path); data=bytearray(self.path.read_bytes()); struct.pack_into('<I',data,28,16000)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(VoiceError,'PCM format'): self.validate()
    def test_inconsistent_block_alignment_refused(self):
        wav(self.path); data=bytearray(self.path.read_bytes()); struct.pack_into('<H',data,32,2)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(VoiceError,'PCM format'): self.validate()
    def test_empty_recording(self):
        wav(self.path,0)
        with self.assertRaisesRegex(VoiceError,'frame count'): self.validate()
    def test_oversized_recording(self):
        wav(self.path,576001)
        with self.assertRaisesRegex(VoiceError,'frame count'): self.validate()
    def test_data_chunk_length_incomplete(self):
        wav(self.path,48000); data=bytearray(self.path.read_bytes()); struct.pack_into('<I',data,40,192004)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(VoiceError,'incomplete'): self.validate()
    def test_pcm_frame_alignment(self):
        wav(self.path,48000); data=bytearray(self.path.read_bytes())
        struct.pack_into('<I',data,40,191999)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(VoiceError,'PCM data was incomplete'): self.validate()
    def test_symlink_output_refused(self):
        target=self.path.with_name('real.wav'); wav(target); self.path.symlink_to(target)
        with self.assertRaises(VoiceError): self.validate()
    def test_fifo_refused_without_blocking(self):
        os.mkfifo(self.path)
        with self.assertRaisesRegex(VoiceError,'not a regular WAV'): self.validate()
    def test_invalid_wav_never_launches_decoder(self):
        self.path.write_bytes(b'x'*44)
        backend=LocalVoiceBackend(VoiceConfiguration(Path('/unused'),Path('/unused'),'0'*64))
        with patch('friday.voice.backend.subprocess.Popen') as process:
            with self.assertRaises(VoiceError): backend.transcribe(self.path)
        process.assert_not_called()


class ProcessFixtureTests(unittest.TestCase):
    def fixture(self, script):
        child=subprocess.Popen([sys.executable,'-B','-c',script],stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        self.addCleanup(stop_process,child)
        ready,_,_=select.select([child.stdout],[],[],3)
        self.assertTrue(ready,'Controlled subprocess did not become ready')
        self.assertEqual(child.stdout.readline(),b'READY\n')
        return child
    def test_real_sigint_can_finalize_wav_and_return_exit_one(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.wav'
            script=f'''import signal,time,wave,sys
w=wave.open({str(path)!r},'wb');w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000)
w.writeframesraw(b'\\0'*48000*4)
def finish(sig,frame):
    w.close();sys.exit(1)
signal.signal(signal.SIGINT,finish)
print('READY',flush=True)
while True: time.sleep(.1)
'''
            child=self.fixture(script); stop_process(child)
            self.assertEqual(child.returncode,1); self.assertEqual(child.poll(),1)
            self.assertEqual(validate_wav(path,maximum_frames=576000),48000)
    def test_real_unhandled_sigint_returns_negative(self):
        child=self.fixture("import signal,time\nsignal.signal(signal.SIGINT,signal.SIG_DFL)\nprint('READY',flush=True)\nwhile True: time.sleep(.1)")
        stop_process(child); self.assertEqual(child.returncode,-signal.SIGINT)
        self.assertEqual(child.poll(),-signal.SIGINT)
    def test_real_ignored_sigint_requires_sigkill_and_is_reaped(self):
        child=self.fixture("import signal,time\nsignal.signal(signal.SIGINT,signal.SIG_IGN)\nprint('READY',flush=True)\nwhile True: time.sleep(.1)")
        stop_process(child); self.assertEqual(child.returncode,-signal.SIGKILL)
        self.assertEqual(child.poll(),-signal.SIGKILL)
    def test_signal_lookup_race_still_reaps(self):
        child=Mock();child.poll.return_value=None;child.communicate.return_value=(b'',b'')
        with patch('friday.voice.backend.os.killpg',side_effect=ProcessLookupError): stop_process(child)
        child.communicate.assert_called_once_with(timeout=2)

    def test_cancellation_during_cleanup_is_preserved_after_kill_and_reap(self):
        child=Mock(pid=123);child.poll.return_value=None
        child.communicate.side_effect=[KeyboardInterrupt,(b'',b'')]
        with patch('friday.voice.backend.os.killpg') as kill:
            with self.assertRaises(KeyboardInterrupt): stop_process(child)
        self.assertEqual([call.args[1] for call in kill.call_args_list],[signal.SIGINT,signal.SIGKILL])
        self.assertEqual([call.kwargs for call in child.communicate.call_args_list],[{'timeout':2},{'timeout':2}])


class FailurePrivacyTests(unittest.TestCase):
    def test_uncertain_cleanup_is_fatal_and_temporary_audio_removed(self):
        assistant=Mock(); backend=Mock(); paths=[]
        def fail(path,announce):
            paths.append(path); wav(path,48000)
            raise ProcessCleanupError('Recording process cleanup could not be confirmed.')
        backend.capture.side_effect=fail
        with self.assertRaises(ProcessCleanupError):
            voice_turn(assistant,backend,read=Mock(return_value=''),write=Mock(),interactive=True)
        self.assertFalse(paths[0].exists()); assistant.respond.assert_not_called()
        backend.transcribe.assert_not_called()

    def test_capture_failure_cleans_audio_before_no_dispatch(self):
        assistant=Mock(); backend=Mock(); paths=[]
        def fail(path,announce):
            paths.append(path); wav(path,48000)
            raise VoiceError('Recording process failed.')
        backend.capture.side_effect=fail
        output=[]
        self.assertIsNone(voice_turn(assistant,backend,read=Mock(return_value=''),write=output.append,interactive=True))
        self.assertFalse(paths[0].exists()); assistant.respond.assert_not_called()
        backend.transcribe.assert_not_called()
        self.assertNotIn('PRIVATE',str(output))
