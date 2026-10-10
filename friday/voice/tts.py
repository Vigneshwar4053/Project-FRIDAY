"""Bounded offline speech and session output control; no tools/memory/capture."""
from pathlib import Path
import os
import subprocess
from typing import Protocol

from friday.voice.backend import stop_process
from friday.core.response import ResponseMetadata, speech_text_has_sensitive_structure

MAX_SPEECH_BYTES = 8192


class SpeechError(RuntimeError):
    """Fixed diagnostics never contain speech input or subprocess output."""


class SpeechBackend(Protocol):
    def speak(self, text: str) -> None: ...


def automatic_speech_allowed(response_category=None):
    """Only metadata created by trusted application code can authorize output."""
    return type(response_category) is ResponseMetadata and response_category.speech_eligible


class EspeakNGBackend:
    def __init__(self, binary=Path('/usr/bin/espeak-ng'), *, timeout=60):
        self.binary = Path(binary)
        self.timeout = timeout

    def verify(self):
        if not self.binary.is_absolute() or not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise SpeechError('eSpeak NG is unavailable. Install/provision espeak-ng only with owner approval; text mode remains available.')

    def stop(self):
        # Playback is synchronous; speak() always reaps its child in finally.
        pass

    def speak(self, text):
        if (not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_SPEECH_BYTES
                or any(ord(c) < 32 or ord(c) == 127 for c in text)):
            raise SpeechError('Speech text must be nonempty, at most 8192 UTF-8 bytes, and contain no control characters.')
        child = None
        try:
            self.verify()
            # Text stays out of argv/process listings and is never parsed as flags
            # or SSML (-m is deliberately absent). No shell or file input.
            child = subprocess.Popen([str(self.binary), '--stdin', '-b', '1', '-v', 'en', '-s', '175'],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                start_new_session=True)
            _, stderr = child.communicate(input=text.encode('utf-8'), timeout=self.timeout)
            # Some eSpeak audio failures print diagnostics with exit status zero.
            # Conservatively treat any diagnostics as unverified output failure.
            if child.returncode != 0 or stderr:
                raise SpeechError('Offline speech output failed or the audio device reported an error; check the local output device.')
        except subprocess.TimeoutExpired:
            raise SpeechError('Offline speech output timed out.') from None
        except OSError:
            raise SpeechError('Offline speech executable or audio device unavailable.') from None
        finally:
            if child is not None:
                stop_process(child)


def speak_turn(text, backend=None, *, write=print):
    try:
        (backend if backend is not None else EspeakNGBackend()).speak(text)
        write('Speech finished; microphone remains OFF.')
    except (KeyboardInterrupt, EOFError):
        write('Speech cancelled; microphone remains OFF.')
    except SpeechError as error:
        write('Speech error: ' + str(error))
    except Exception:
        write('Speech output failed safely; microphone remains OFF.')


class SpeechController:
    """One synchronous backend, session-only toggle, no text queue or retention."""
    def __init__(self, backend=None, *, write=print):
        self.backend = backend if backend is not None else EspeakNGBackend()
        self.write = write
        self.enabled = False
        self.closed = False
        self.available = self._verify()
        self.enabled = self.available

    def _verify(self):
        try:
            verify = getattr(self.backend, 'verify', None)
            if callable(verify):
                verify()  # File checks only; never playback.
            return True
        except Exception:
            self.write('Automatic speech unavailable. Check the offline TTS executable; installation requires owner approval. Text mode remains available.')
            return False

    def toggle(self):
        if self.closed:
            return False
        if not self.enabled:
            self.available = self._verify()
            self.enabled = self.available
        else:
            self.enabled = False
        self.write('Automatic speech enabled.' if self.enabled else 'Automatic speech disabled.')
        return self.enabled

    def speak_safe_response(self, text, metadata):
        if (self.closed or not self.enabled or not automatic_speech_allowed(metadata)
                or speech_text_has_sensitive_structure(text)):
            return
        # Paragraphs/list whitespace need not be control commands to the engine.
        # Keep terminal text intact; pass one plain utterance to the backend.
        self._speak(text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' '))

    def speak_explicit(self, text):
        if not self.closed:
            self._speak(text, explicit=True)  # Independent of automatic toggle.

    def _speak(self, text, *, explicit=False):
        try:
            self.backend.speak(text)
            if explicit:
                self.write('Speech finished; microphone remains OFF.')
        except (KeyboardInterrupt, EOFError):
            self.write('Speech cancelled; microphone remains OFF.')
        except SpeechError as error:
            self.write('Speech error: ' + str(error))
        except Exception:
            self.write('Speech output failed safely; microphone remains OFF.')

    def stop(self):
        stop = getattr(self.backend, 'stop', None)
        if callable(stop):
            try:
                stop()
            except Exception:
                self.write('Speech shutdown failed safely.')

    def shutdown(self):
        if not self.closed:
            self.stop()
            self.enabled = False
            self.closed = True
