"""Small atomic owner-only desktop preferences; no conversations or credentials."""
import json
import os
from pathlib import Path
import tempfile

DEFAULTS = dict(answer_length='Short', voice='en', speed=175, volume=100,
                speech_enabled=False, speak_welcome=False, hidden_projects=False, selected_model='qwen3:4b', response_mode='Short')

class Preferences:
    def __init__(self, path=None):
        base = os.environ.get('XDG_CONFIG_HOME', '')
        self.path = Path(path) if path else (Path(base) if base.startswith('/') else Path.home()/'.config')/'zorvyq/desktop.json'
        self.values = dict(DEFAULTS)
        try:
            if self.path.is_symlink():
                raise ValueError('Unsafe preferences path')
            data = json.loads(self.path.read_text())
            for key, default in DEFAULTS.items():
                value = data.get(key, default)
                if type(value) is type(default):
                    self.values[key] = value
            if 'response_mode' not in data:
                self.values['response_mode'] = {'Short':'Short','Balanced':'Medium','Detailed':'Deep Analysis'}.get(self.values['answer_length'],'Short')
        except FileNotFoundError:
            pass
        self.validate()

    def validate(self):
        from zorvyq.security import SPECIALIST
        v = self.values
        if v['selected_model'] not in ('qwen3:4b', SPECIALIST) or v['response_mode'] not in ('Short','Medium','Deep Analysis'):
            raise ValueError('Invalid model or response depth.')
        if v['answer_length'] not in ('Short', 'Balanced', 'Detailed') or not 80 <= v['speed'] <= 450 or not 0 <= v['volume'] <= 200:
            raise ValueError('Invalid desktop preferences')
        if not isinstance(v['voice'], str) or len(v['voice']) > 200:
            raise ValueError('Invalid voice')

    def save(self, **values):
        if set(values) - set(DEFAULTS) or any(type(value) is not type(DEFAULTS[key]) for key, value in values.items()):
            raise ValueError('Invalid desktop preference type.')
        previous = self.values.copy()
        self.values.update(values)
        try:
            self.validate()
        except ValueError:
            self.values = previous
            raise
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError('Unsafe preferences path')
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.desktop-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.values, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def response_instructions(length):
    return {'Short': 'Answer simple questions directly in about 1–3 sentences. Avoid introductions, decorative headings and repeated conclusions.',
            'Balanced': 'Give one short explanation with a few relevant details.',
            'Detailed': 'Give a comprehensive, carefully organized explanation.'}[length] + (
        ' Always honor an explicit request for more detail. Preserve necessary complete code, uncertainty, security warnings, permission explanations and verified citations. Never truncate a validated answer.')


def generation_prompt(model, system, length):
    """Use Ollama chat roles so each installed model applies its own template."""
    from zorvyq.security import SPECIALIST
    if model == SPECIALIST:
        system = 'You are ZORVYQ, a cybersecurity assistant. State uncertainty and do not claim source verification.'
    elif model != 'qwen3:4b':
        raise ValueError('Unsupported desktop generation model.')
    return system+'\n'+response_instructions(length)
