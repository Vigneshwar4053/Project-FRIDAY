"""Semantic user-folder names and bounded XDG data parsing; no authorization."""
import os
from pathlib import Path
import re
import stat
import unicodedata

from friday.tools.grants import directory_descriptor, lexical_path

MAX_XDG_BYTES = 16384
MAX_XDG_LINES = 64
ALIASES = {'photo': 'pictures', 'picture': 'pictures', 'photos': 'pictures', 'pictures': 'pictures', 'videos': 'videos',
           'downloads': 'downloads', 'documents': 'documents', 'music': 'music',
           'desktop': 'desktop'}
DIRECTORIES = {'pictures': ('XDG_PICTURES_DIR', 'Pictures'),
               'videos': ('XDG_VIDEOS_DIR', 'Videos'),
               'downloads': ('XDG_DOWNLOAD_DIR', 'Downloads'),
               'documents': ('XDG_DOCUMENTS_DIR', 'Documents'),
               'music': ('XDG_MUSIC_DIR', 'Music'),
               'desktop': ('XDG_DESKTOP_DIR', 'Desktop')}
_ALIAS = '(?:' + '|'.join(ALIASES) + ')'
_ASSIGNMENT = re.compile(r'XDG_([A-Z]+)_DIR="([^"\n]*)"\s*(?:#.*)?\Z')
_EXPLICIT_PATH = re.compile(r'(?:^|[\s"\'])((?:~/|/|\./|[\w.-]+/)[^\s]*)')


class LocationResolutionError(ValueError):
    """No private mapping/path/configuration details in this exception."""


def command_text(message):
    text = message.strip()
    # Optional assistant invocation, useful for transcribed voice input.
    text = re.sub(r'^friday\s*[,，:]\s*', '', text, flags=re.I)
    return text


def has_explicit_path(message):
    return bool(_EXPLICIT_PATH.search(message))


def semantic_concepts(message):
    if has_explicit_path(message):
        return frozenset()
    return frozenset(ALIASES[match.group().casefold()]
        for match in re.finditer(r'(?<![\w/.-])' + _ALIAS + r'(?![\w/.-])', message, re.I))


def instructional_question(message):
    text = command_text(message).casefold()
    text = re.sub(r'^(?:(?:please|(?:can|could|would)\s+you)\s+)*', '', text)
    return bool(re.match(r'^(?:how\s+(?:do|does|can|to)|explain)\b', text) or
                re.search(r'\b(?:show|tell)\s+me\s+how\b', text))


def browsing_guard(message):
    """Recognize unsupported navigation/launching before any model proposal."""
    text = command_text(message).rstrip('?. ').casefold()
    if instructional_question(text):
        return None
    action = re.sub(r'^(?:(?:please|(?:can|could|would)\s+you)\s+)*', '', text)
    if re.match(r'^(?:go\s+back\b|back\Z|return\s+to\s+(?:the\s+)?previous\b|enter\s+that\s+folder\b)', action):
        return 'That navigation form is not supported; name a visible child or use go back/go home.'
    if re.match(r'^launch\b', action) or re.match(r'^play\s+(?:a\s+|my\s+|the\s+)?(?:video|movie|music|song|audio)\b', action):
        return 'Application launching and playback are not supported; folders can be listed in FRIDAY.'
    if re.match(r'^(?:open|show|browse|display|take\s+me\s+to)\b', action) and not has_explicit_path(text) and re.search(r'\b(?:application|app|viewer|player)\b', text):
        return 'Application launching is not supported; folders can be listed in FRIDAY.'
    return None


class SemanticLocationResolver:
    """Resolve known concepts to lexical paths; ToolManager authorizes every use.

    A missing file/entry uses the conventional home-folder default. Malformed,
    unreadable, unsafe or disabled mappings fail closed, never silently default.
    Configuration is reloaded per resolution and never evaluated as shell code.
    """
    def _mapping(self):
        home = lexical_path(str(Path.home()))
        configured = os.environ.get('XDG_CONFIG_HOME')
        config_home = lexical_path(configured) if configured is not None else home / '.config'
        if not config_home.is_absolute():
            raise ValueError('Invalid configuration directory.')
        try:
            with directory_descriptor(config_home) as parent:
                fd = os.open('user-dirs.dirs', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=parent)
                try:
                    metadata = os.fstat(fd)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_XDG_BYTES:
                        raise ValueError('Invalid configuration file.')
                    chunks = []
                    remaining = MAX_XDG_BYTES + 1
                    while remaining:
                        chunk = os.read(fd, min(4096, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    body = b''.join(chunks)
                    if len(body) > MAX_XDG_BYTES:
                        raise ValueError('Configuration limit.')
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return home, {}
        lines = body.decode('utf-8', errors='strict').splitlines()
        if len(lines) > MAX_XDG_LINES:
            raise ValueError('Configuration line limit.')
        values = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = _ASSIGNMENT.fullmatch(line)
            if match is None:
                raise ValueError('Invalid configuration syntax.')
            key, value = 'XDG_' + match[1] + '_DIR', match[2]
            if key in values:
                raise ValueError('Duplicate configuration entry.')
            if value == '$HOME':
                values[key] = None  # XDG disabled folder: do not list the entire home.
                continue
            if value.startswith('$HOME/'):
                value = str(home) + value[5:]
            if any(c in value for c in ('$', '`', '\\', ';')) or any(
                    unicodedata.category(c).startswith('C') for c in value):
                raise ValueError('Unsupported configuration expansion.')
            path = lexical_path(value)
            if not path.is_absolute() or path == home or path == Path('/'):
                values[key] = None
            else:
                values[key] = path
        return home, values

    def resolve(self, location):
        if type(location) is not str or location.casefold() not in ALIASES:
            raise LocationResolutionError('Unknown semantic folder; please specify a location.')
        key, default = DIRECTORIES[ALIASES[location.casefold()]]
        try:
            home, values = self._mapping()
            path = values.get(key, home / default)
            if path is None:
                raise ValueError('Disabled location.')
            return str(path)
        except (OSError, ValueError, UnicodeError):
            raise LocationResolutionError('The configured folder location is unavailable or invalid.') from None

    def fast_location(self, message):
        """Small grammar for bare aliases and clear browsing verbs, not sentence lists."""
        text = command_text(message).rstrip('?. ')
        if instructional_question(text) or has_explicit_path(text):
            return None
        text = re.sub(r'^(?:(?:please|(?:can|could|would)\s+you)\s+)*', '', text, flags=re.I)
        target = r'(?:my\s+|the\s+)?(' + _ALIAS + r')(?:\s+(?:folder|directory))?'
        verb = (r'(?:(?:open|enter|show|browse|display)\s+(?:me\s+)?|list\s+|'
                r'take\s+me\s+to\s+(?:(?:the\s+place\s+)?where\s+I\s+keep\s+)?)?')
        match = re.fullmatch(verb + target, text, re.I)
        return ALIASES[match[1].casefold()] if match else None

    def normalize_proposal(self, tool_name, arguments, message):
        """Return normalized arguments and a trusted semantic-evidence flag.

        A location field is valid only for listing, exclusive of path, and grounded
        in one concept in the user's current request. Never remap explicit paths.
        """
        if tool_name != 'list_directory':
            return arguments, False
        if instructional_question(message) or browsing_guard(message):
            raise ValueError('Request does not authorize folder browsing.')
        concepts = semantic_concepts(message)
        if len(concepts) > 1:
            raise ValueError('Semantic folder target is ambiguous.')
        if set(arguments) == {'location'}:
            location = arguments['location']
            if (type(location) is not str or location not in ALIASES or
                    concepts != {ALIASES[location]} or browsing_guard(message)):
                raise ValueError('Invalid semantic proposal.')
            return {'path': self.resolve(location)}, True
        if set(arguments) == {'path'} and len(concepts) == 1:
            path = arguments['path']
            # Compatibility with the original model path contract, no arbitrary
            # absolute-path repair or parent-directory inference.
            if type(path) is str:
                token = path[2:] if path.startswith('~/') else path
                if token.casefold() in ALIASES and ALIASES[token.casefold()] in concepts:
                    return {'path': self.resolve(token)}, True
        return arguments, False
