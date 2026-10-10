"""One local greeting per interactive launch; no microphone or stored audio."""
from datetime import datetime, timezone
from friday.voice.tts import EspeakNGBackend
from friday.core.response import ResponseCategory, ResponseProvenance, ResponseMetadata


def local_greeting(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('An aware clock is required.')
    hour = now.astimezone().hour
    period = 'morning' if 5 <= hour < 12 else 'afternoon' if 12 <= hour < 17 else 'evening'
    return f'Good {period}! Welcome back.'


class StartupGreeting:
    def __init__(self): self.done = False

    def greet(self, speech, *, interactive, diagnostics=False, write=print, now=None):
        if self.done or not interactive or diagnostics: return False
        self.done = True
        text = local_greeting(now)
        write(text)
        # Use the same speech policy/controller with a shorter startup bound.
        backend = speech.backend
        timeout = backend.timeout if isinstance(backend, EspeakNGBackend) else None
        try:
            if timeout is not None: backend.timeout = min(timeout, 5)
            speech.speak_safe_response(text, ResponseMetadata(ResponseCategory.GREETING,
                                                            ResponseProvenance.LOCAL_GREETING))
        finally:
            if timeout is not None: backend.timeout = timeout
        return True
