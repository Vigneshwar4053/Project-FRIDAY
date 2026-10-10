"""Owner-provisioned XDG voice configuration; reading never initializes audio."""
import json
import os
from pathlib import Path
import stat

from friday.voice.backend import LocalVoiceBackend, VoiceConfiguration, VoiceError

TINY_EN_SHA256 = '921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f'


def xdg_directory(variable, fallback):
    value = os.environ.get(variable)
    # XDG specifies absolute directories; ignore relative environment values.
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def configuration_path():
    return xdg_directory('XDG_CONFIG_HOME', '.config') / 'friday' / 'voice.json'


def dependency_directory():
    return xdg_directory('XDG_DATA_HOME', '.local/share') / 'friday' / 'voice'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate configuration field.')
        result[key] = value
    return result


def read_configuration(path):
    try:
        # Executable paths are security-sensitive owner configuration, not input
        # from a transcript. Refuse symlinks and files writable by other users.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('Unsafe configuration permissions.')
            raw = source.read(4097)
        if len(raw) > 4096:
            raise ValueError('Configuration too large.')
        data = json.loads(raw, object_pairs_hook=unique_object)
        if (not isinstance(data, dict) or set(data) != {'version', 'binary', 'model', 'model_sha256'}
                or type(data['version']) is not int or data['version'] != 1):
            raise ValueError('Invalid configuration schema.')
        return {key: data[key] for key in ('binary', 'model', 'model_sha256')}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, UnicodeError):
        raise VoiceError('Saved voice configuration is invalid. Inspect voice.json or use complete --voice-* overrides; text mode remains available.') from None


def configured_path(value):
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid path.')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Absolute executable/model paths required.')
    # No environment expansion, shell evaluation, or PATH lookup.
    return path


def resolve_configuration(*, binary=None, model=None, model_sha256=None, path=None):
    overrides = {'binary': binary, 'model': model, 'model_sha256': model_sha256}
    # Complete explicit overrides also recover from a malformed saved file.
    data = {} if all(v is not None for v in overrides.values()) else read_configuration(path or configuration_path())
    data.update({k: v for k, v in overrides.items() if v is not None})
    if not data:
        return None
    if set(data) != set(overrides):
        raise VoiceError('Voice configuration is incomplete. Set binary, model and model_sha256 in voice.json or --voice-* arguments; microphone remains OFF.')
    try:
        if data['model_sha256'] != TINY_EN_SHA256:
            raise ValueError('Only the explicitly approved tiny.en pin is supported.')
        return VoiceConfiguration(configured_path(data['binary']), configured_path(data['model']), data['model_sha256'])
    except (ValueError, TypeError, RuntimeError):
        raise VoiceError('Invalid voice paths or model SHA-256. Use absolute paths and the approved tiny.en checksum; text mode remains available.') from None


def inspect_configuration(configuration, path):
    """Dependency inspection only; no executable launch, recording or playback."""
    result = {'configuration_file': str(path), 'microphone': 'OFF',
              'dependency_directory': str(dependency_directory()), 'status': 'not_configured'}
    if configuration is None:
        result['message'] = 'Create owner-provisioned voice.json after restoring trusted dependencies.'
        return result
    result.update(binary=str(configuration.binary), model=str(configuration.model),
                  model_sha256=configuration.model_sha256)
    try:
        LocalVoiceBackend(configuration).verify()
        result['status'] = 'verified_files'
        result['message'] = 'Files and model checksum verified; CLI/model compatibility and hardware require separate validation.'
    except VoiceError as error:
        result['status'] = 'unavailable'
        result['message'] = str(error)
    return result
