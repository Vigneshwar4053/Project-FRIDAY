"""Typed activation and confirmation; audio is removed before assistant execution."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from friday.providers.base import ProviderError
from friday.voice.backend import VoiceError, ProcessCleanupError


def voice_turn(assistant, backend, *, read=input, write=print, interactive=None, unavailable_reason=None):
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        write('Voice requires an interactive terminal; microphone remains OFF.')
        return None
    if backend is None:
        write(unavailable_reason or 'Voice is not configured; microphone remains OFF. Inspect --check-voice-config and provision trusted dependencies before creating voice.json.')
        return None
    try:
        verify = getattr(backend, 'verify', None)
        if verify is not None:
            verify()
        write('Microphone OFF. Up to eight seconds to speak AFTER SPEAK NOW, plus bounded readiness/finalization time. Enter activates; Ctrl+C cancels.')
        if read('Press Enter to activate microphone: ') != '':
            write('Voice cancelled; microphone remains OFF.')
            return None
        with TemporaryDirectory(prefix='friday-voice-') as directory:
            # TemporaryDirectory is private (0700), including on cancellation/error.
            path = Path(directory) / 'capture.wav'
            backend.capture(path, write)
            write('Processing locally; microphone OFF.')
            transcript = backend.transcribe(path)
        # No raw audio remains at either confirmation or filesystem permission prompts.
        if not isinstance(transcript, str) or not transcript.strip():
            write('No speech recognized; nothing sent to FRIDAY.')
            return None
        transcript = transcript.strip()
        if len(transcript.encode('utf-8')) > 4096 or any(
                (ord(c) < 32 and c not in '\n\t') or ord(c) == 127 for c in transcript):
            raise VoiceError('Transcript failed validation.')
        write('Recognized transcript: ' + json.dumps(transcript, ensure_ascii=True))
        if read('Send this transcript to FRIDAY? [y/N] ').strip().casefold() != 'y':
            write('Transcript discarded; nothing sent to FRIDAY. Type /voice to retry.')
            return None
        return assistant.respond(transcript, persist=False)
    except ProcessCleanupError:
        # A potentially live recording process is not an ordinary retryable
        # failure. End the CLI session through its established unwinding path.
        raise
    except (KeyboardInterrupt, EOFError):
        write('Voice cancelled; microphone OFF.')
        return None
    except VoiceError as error:
        write('Voice error: ' + str(error))
        return None
    except ProviderError:
        write('Voice response unavailable; private turn was not saved.')
        return None
    except Exception:
        # Never expose backend exceptions, device details, transcripts, or raw prompts.
        write('Voice operation failed safely; microphone OFF.')
        return None
