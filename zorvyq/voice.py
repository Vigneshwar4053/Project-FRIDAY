"""Offline inventory and explicit playback; no microphone activation."""
import subprocess
from pathlib import Path
from friday.voice.tts import EspeakNGBackend, SpeechError

class DesktopSpeech(EspeakNGBackend):
    def __init__(self, preferences, **kwargs):
        super().__init__(**kwargs)
        self.preferences = preferences
        self.last_error = 'None'
        self.notice = ''

    def voices(self):
        try:
            self.verify()
            result = subprocess.run([str(self.binary), '--voices'], shell=False, capture_output=True,
                                    timeout=5, text=True, check=True)
            rows = []
            for line in result.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) >= 5:
                    # espeak's File column is an unambiguous installed voice ID.
                    rows.append((fields[4], fields[3].replace('_', ' ')))
            return tuple(dict.fromkeys(rows))
        except (OSError, subprocess.SubprocessError, SpeechError):
            self.last_error = 'voice_inventory_unavailable'
            return ()

    def resolve_voice(self):
        voices = self.voices()
        ids = [v[0] for v in voices]
        selected = self.preferences.values['voice']
        if selected not in ids and ids:
            selected = next((v for v in ids if v.endswith('/en')), ids[0])
            self.preferences.save(voice=selected)
            self.notice = 'Saved voice unavailable; selected an installed fallback.'
        if not ids:
            raise SpeechError('No installed offline voices found.')
        return selected

    def speak(self, text):
        if not self.preferences.values['speech_enabled']:
            self.last_error = 'speech_disabled'
            raise SpeechError('Speech output disabled.')
        try:
            self.voice = self.resolve_voice()
            self.speed = self.preferences.values['speed']
            self.volume = self.preferences.values['volume']
            super().speak(text)
            self.last_error = 'None'
        except SpeechError:
            self.last_error = 'offline_playback_failed'
            raise

from enum import Enum
from threading import Event

class VoiceState(str, Enum):
    IDLE='IDLE'
    LISTENING='LISTENING'
    TRANSCRIBING='TRANSCRIBING'
    PROCESSING='PROCESSING'
    SPEAKING='SPEAKING'
    ERROR='ERROR'

class VoiceInteraction:
    """Session state and cancellation only; construction never opens audio."""
    def __init__(self):
        self.state=VoiceState.IDLE
        self.cancelled=Event()
        self.welcome_attempted=False

    def begin(self,state):
        if self.state not in (VoiceState.IDLE,VoiceState.ERROR):
            raise ValueError('Voice interaction already active.')
        self.cancelled.clear();self.state=state

    def welcome(self,preferences):
        if self.welcome_attempted:return False
        self.welcome_attempted=True
        return preferences['speech_enabled'] and preferences['speak_welcome']


def speech_summary(text,mode='Short'):
    """Bound spoken text; keep code, citations and tables in the visible answer."""
    from friday.core.response import speech_text_has_sensitive_structure
    if speech_text_has_sensitive_structure(text):return None
    if any(marker in text for marker in ('```','Verified sources:','|','[C1]')):
        return 'The answer is ready. Please review the details on screen.'
    import re
    plain=re.sub(r'[*#`_]', '', ' '.join(text.split()))
    limit=360 if mode=='Short' else 700
    if len(plain)<=limit:return plain
    sentences=re.split(r'(?<=[.!?])\s+',plain)
    output=''
    for sentence in sentences:
        if len(output)+len(sentence)>limit:break
        output+=sentence+' '
    return (output.strip()+' Please review the full answer on screen.') if output else 'The answer is ready. Please review it on screen.'
