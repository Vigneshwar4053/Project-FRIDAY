"""Bounded local capture/STT subprocesses; no assistant or tool access."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import signal
import stat
import struct
import subprocess
import time
import wave
from typing import Protocol


class VoiceError(RuntimeError):
    """Safe fixed diagnostic; never includes transcript or backend output."""


class VoiceBackend(Protocol):
    def capture(self, path: Path, announce) -> None: ...
    def transcribe(self, path: Path) -> str: ...


@dataclass(frozen=True)
class VoiceConfiguration:
    binary: Path
    model: Path
    model_sha256: str
    card: int = 1
    device: str = 'hw:CARD=Generic_1,DEV=0'
    duration: int = 8

    def __post_init__(self):
        if type(self.duration) is not int or not 1 <= self.duration <= 8:
            raise ValueError('Voice duration must be 1–8 seconds.')
        if type(self.card) is not int or self.card < 0:
            raise ValueError('Invalid voice card.')
        if self.card != 1 or self.device != 'hw:CARD=Generic_1,DEV=0':
            raise ValueError('This experimental backend requires the verified ALC256 device.')
        if len(self.model_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.model_sha256):
            raise ValueError('Pinned SHA-256 required.')


class ProcessCleanupError(RuntimeError):
    """Fixed local-process diagnostic; no subprocess output or private paths."""


def stop_process(child):
    """Drain/reap every child; interrupt a live group, then kill if necessary."""
    try:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        child.communicate(timeout=2)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        cancelled = isinstance(error, KeyboardInterrupt)
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            raise ProcessCleanupError('Local audio process cleanup could not be confirmed.') from None
        try:
            child.communicate(timeout=2)
        except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt):
            raise ProcessCleanupError('Local audio process cleanup could not be confirmed.') from None
        if cancelled:
            raise KeyboardInterrupt from None
    except OSError:
        raise ProcessCleanupError('Local audio process cleanup could not be confirmed.') from None


def validate_wav(path, *, minimum_frames=1, maximum_frames):
    """Validate finalized RIFF lengths and complete bounded native PCM; no repair."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise VoiceError('Recording file is not a regular WAV.')
            if not 44 <= info.st_size <= maximum_frames * 4 + 65536:
                raise VoiceError('Recording file size is invalid or exceeds the capture bound.')
            header = source.read(12)
            if header[:4] != b'RIFF' or header[8:] != b'WAVE':
                raise VoiceError('Recording WAV header is invalid.')
            if struct.unpack('<I', header[4:8])[0] + 8 != info.st_size:
                raise VoiceError('Recording file was incomplete or not finalized.')
            data_bytes = None
            seen = set()
            while source.tell() < info.st_size:
                chunk = source.read(8)
                if len(chunk) != 8:
                    raise VoiceError('Recording file was incomplete.')
                name, size = struct.unpack('<4sI', chunk)
                end = source.tell() + size + (size % 2)
                if end > info.st_size:
                    raise VoiceError('Recording file was incomplete.')
                if name in (b'fmt ', b'data'):
                    if name in seen:
                        raise VoiceError('Recording WAV header is ambiguous.')
                    seen.add(name)
                if name == b'data':
                    data_bytes = size
                if name == b'fmt ':
                    if size < 16:
                        raise VoiceError('Recording WAV header is invalid.')
                    pcm = struct.unpack('<HHIIHH', source.read(16))
                    if pcm != (1, 2, 48000, 192000, 4, 16):
                        raise VoiceError('Recording PCM format differs from the approved native format.')
                source.seek(end)
            if data_bytes is None or data_bytes % 4:
                raise VoiceError('Recording PCM data was incomplete.')
            source.seek(0)
            with wave.open(source, 'rb') as audio:
                frames = audio.getnframes()
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (2, 2, 48000, 'NONE'):
                    raise VoiceError('Recording PCM format differs from the approved native format.')
                if not minimum_frames <= frames <= maximum_frames:
                    raise VoiceError('Recording frame count is incomplete or exceeds the capture bound.')
                if data_bytes != frames * 4 or len(audio.readframes(frames)) != frames * 4:
                    raise VoiceError('Recording file was incomplete.')
            return frames
    except FileNotFoundError:
        raise VoiceError('Recording file is missing.') from None
    except (OSError, wave.Error, EOFError, struct.error):
        raise VoiceError('Recording file is unavailable or its WAV header is invalid.') from None


def fields(text):
    return dict(line.split(':', 1) for line in text.splitlines() if ':' in line)


def normalized_fields(text):
    return {k.strip(): v.strip() for k, v in fields(text).items()}


class LocalVoiceBackend:
    """Lazy: constructing the backend never opens a microphone or loads a model."""
    def __init__(self, configuration: VoiceConfiguration):
        self.configuration = configuration

    def verify(self):
        c = self.configuration
        try:
            if not c.binary.is_file() or not os.access(c.binary, os.X_OK):
                raise VoiceError('Voice executable unavailable. Restore trusted whisper-cli and inspect --check-voice-config; microphone remains OFF.')
            if not c.model.is_file():
                raise VoiceError('Voice model unavailable. Restore the approved tiny.en model and inspect --check-voice-config; microphone remains OFF.')
            digest = hashlib.sha256()
            with c.model.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != c.model_sha256:
                raise VoiceError('Voice model integrity check failed. Verify the approved tiny.en file and SHA-256; microphone remains OFF.')
        except OSError:
            raise VoiceError('Voice model unavailable. Restore the approved tiny.en model and inspect --check-voice-config; microphone remains OFF.') from None

    def capture(self, path, announce):
        c = self.configuration
        base = Path(f'/proc/asound/card{c.card}/pcm0c')
        status = base / 'sub0/status'
        child = None
        try:
            info = normalized_fields((base / 'info').read_text())
            if info.get('id') != 'ALC256 Analog' or info.get('stream') != 'CAPTURE':
                raise VoiceError('Configured microphone identity differs; capture refused.')
            if status.read_text().strip() != 'closed':
                raise VoiceError('Configured microphone is busy.')
            announce('RECORDING — remain quiet until SPEAK NOW. Ctrl+C cancels.')
            child = subprocess.Popen(['/usr/bin/arecord', '-D', c.device, '--fatal-errors',
                '-t', 'wav', '-f', 'S16_LE', '-r', '48000', '-c', '2', '-d', str(c.duration + 4), str(path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            started = time.monotonic()
            def pointer():
                data = normalized_fields(status.read_text())
                if data.get('state') != 'RUNNING' or int(data.get('owner_pid', '-1')) != child.pid:
                    return None
                return int(data['hw_ptr'])
            previous = None
            while time.monotonic() - started < 2:
                if child.poll() is not None:
                    raise VoiceError('Recording process exited unexpectedly before readiness.')
                current = pointer()
                if previous is not None and current is not None and current > previous:
                    break
                previous = current
                time.sleep(.02)
            else:
                raise VoiceError('Capture readiness could not be verified.')
            hardware = normalized_fields((base / 'sub0/hw_params').read_text())
            if (hardware.get('format'), hardware.get('channels'), hardware.get('rate', '').split()[0]) != ('S16_LE', '2', '48000'):
                raise VoiceError('Native capture format unavailable.')
            time.sleep(.8)
            settled = pointer()
            if child.poll() is not None or settled is None or settled <= current:
                raise VoiceError('Capture stopped before speech cue.')
            # The fixed arecord duration was requested by FRIDAY at launch.
            # Refuse a delayed cue that would consume its four-second headroom.
            if time.monotonic() - started > 3:
                raise VoiceError('Capture readiness exceeded the bounded speaking-window headroom.')
            announce('CAPTURE READY — SPEAK NOW')
            cue = time.monotonic()
            if cue - started > 3:
                raise VoiceError('Capture cue was delayed; full speech window unavailable.')
            # REQUESTED_DURATION -> READY -> FULL_WINDOW -> FINALIZED.
            # Natural completion avoids arecord's ambiguous exit-1 abort path.
            # The full window starts only after the flushed cue returns.
            try:
                child.communicate(timeout=c.duration)
            except subprocess.TimeoutExpired:
                if time.monotonic() - cue < c.duration:
                    raise VoiceError('Capture speech window could not be verified.')
                announce('Speech window complete; finalizing recording.')
                # arecord's duration is a frame limit. Allow at most its four
                # seconds of readiness headroom to finish naturally; do not
                # accept an interrupted or killed recording as successful.
                child.communicate(timeout=4)
            else:
                if time.monotonic() - cue < c.duration:
                    if child.returncode is not None and child.returncode < 0:
                        raise VoiceError('Recording process was interrupted unexpectedly during the speech window.')
                    if child.returncode:
                        raise VoiceError('Recording process failed during the speech window; audio device or recording became unavailable.')
                    raise VoiceError('Capture stopped before the full speech window elapsed.')
            if child.returncode != 0:
                if child.returncode is not None and child.returncode < 0:
                    raise VoiceError('Recording process was interrupted unexpectedly.')
                raise VoiceError('Recording process failed; audio device or recording became unavailable.')
            # Successful communicate reaps the process. Natural -d completion
            # must have written the entire requested frame count, not a partial
            # file that happens to contain a usable WAV header.
            frames = 48000 * (c.duration + 4)
            validate_wav(path, minimum_frames=frames, maximum_frames=frames)

        except subprocess.TimeoutExpired:
            raise VoiceError('Recording timed out or could not be finalized.') from None
        except (OSError, ValueError, KeyError, IndexError):
            raise VoiceError('Audio device unavailable or readiness uncertain.') from None
        finally:
            try:
                if child is not None:
                    stop_process(child)
            except ProcessCleanupError:
                announce('Microphone shutdown could not be confirmed.')
                raise ProcessCleanupError('Recording process cleanup could not be confirmed.') from None
            except KeyboardInterrupt:
                # stop_process completed its kill/reap before preserving cancel.
                announce('Microphone OFF.')
                raise
            else:
                announce('Microphone OFF.')

    def transcribe(self, path):
        c = self.configuration
        child = None
        try:
            validate_wav(path, maximum_frames=48000 * (c.duration + 4))
            child = subprocess.Popen([str(c.binary), '-m', str(c.model), '-f', str(path),
                '-l', 'en', '-t', '4', '--no-gpu', '--no-prints', '--no-timestamps',
                '--no-fallback', '--beam-size', '5', '--best-of', '5', '--temperature', '0'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            stdout, _ = child.communicate(timeout=60)
            if child.returncode != 0:
                raise VoiceError('Offline transcription failed.')
            if len(stdout) > 4096:
                raise VoiceError('Transcript exceeds the safe limit.')
            text = stdout.decode('utf-8', 'strict').strip()
            if any(ord(ch) < 32 and ch not in '\n\t' or ord(ch) == 127 for ch in text):
                raise VoiceError('Transcript contains unsupported control characters.')
            return text
        except subprocess.TimeoutExpired:
            raise VoiceError('Offline transcription timed out.') from None
        except (OSError, UnicodeError, wave.Error):
            raise VoiceError('Offline transcription unavailable.') from None
        finally:
            if child is not None:
                stop_process(child)
