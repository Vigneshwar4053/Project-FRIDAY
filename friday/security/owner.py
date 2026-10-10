"""Hidden terminal authentication, independent of models and permission grants.

Argon2 is an optional, separately approved dependency. Its absence disables
sensitive operations; no substitute hashing algorithm is provided.
"""
from dataclasses import dataclass
from enum import Enum
import base64
import getpass
import os
from pathlib import Path
import re
import stat
import sys
from threading import Lock
from time import monotonic
from types import MappingProxyType
import warnings

ENABLED = 'FRIDAY_OWNER_AUTH_ENABLED'
HASH = 'FRIDAY_OWNER_AUTH_HASH'
MAX_CONFIG_BYTES = 16384


class OwnerAuthenticationError(PermissionError):
    """Public messages never contain configuration, submitted secrets or hashes."""


class SensitiveOperation(str, Enum):
    BROWSER_NAVIGATION = 'browser_navigation'
    OPEN_PROJECT = 'open_project'
    OPEN_FILE = 'open_file'
    DESKTOP_INPUT = 'desktop_input'


# Authentication requirements, not a capability grant or application allowlist
# override. The reviewed adapter must establish capability and policy first.
SENSITIVE_APPLICATIONS = MappingProxyType({
    SensitiveOperation.BROWSER_NAVIGATION: frozenset({'firefox'}),
    SensitiveOperation.OPEN_PROJECT: frozenset({'vscode'}),
    SensitiveOperation.OPEN_FILE: frozenset({'vscode'}),
    SensitiveOperation.DESKTOP_INPUT: frozenset({'firefox','vscode','files'}),
})


@dataclass(frozen=True)
class OwnerRequest:
    operation: SensitiveOperation
    application_id: str
    target: str

    def __post_init__(self):
        if (type(self.operation) is not SensitiveOperation or
                self.application_id not in SENSITIVE_APPLICATIONS.get(self.operation, ()) or
                type(self.target) is not str or not self.target or
                len(self.target.encode('utf-8')) > 8192 or
                any(ord(c) < 32 for c in self.target)):
            raise ValueError('Invalid exact owner authorization request.')


def validate_hash(encoded):
    # Fixed resource parameters prevent a tampered configuration from selecting
    # unbounded hashing costs. Only the setup command's Argon2id format is valid.
    if type(encoded) is not str:
        raise OwnerAuthenticationError('Owner credential configuration is unavailable or invalid.')
    match = re.fullmatch(r'\$argon2id\$v=19\$m=65536,t=3,p=1\$([A-Za-z0-9+/]{22})\$([A-Za-z0-9+/]{43})', encoded)
    if not match:
        raise OwnerAuthenticationError('Owner credential configuration is unavailable or invalid.')
    for value, size in zip(match.groups(), (16, 32)):
        decoded = base64.b64decode(value + '=' * (-len(value) % 4), validate=True)
        if len(decoded) != size or base64.b64encode(decoded).decode().rstrip('=') != value:
            raise OwnerAuthenticationError('Owner credential configuration is unavailable or invalid.')
    return encoded


def private_config(path):
    """Read a bounded, owner-only regular file without following symlinks."""
    from friday.tools.grants import directory_descriptor
    path = Path(path).absolute()
    try:
        with directory_descriptor(path.parent) as parent:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                        info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or
                        info.st_size > MAX_CONFIG_BYTES):
                    raise ValueError('Unsafe credential file.')
                content = os.read(fd, MAX_CONFIG_BYTES + 1)
                if len(content) > MAX_CONFIG_BYTES:
                    raise ValueError('Oversized credential file.')
                return content.decode('utf-8'), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            finally:
                os.close(fd)
    except (OSError, ValueError, UnicodeError):
        raise OwnerAuthenticationError('Owner credential configuration is unavailable or invalid.') from None


def load_hash(path):
    content, _ = private_config(path)
    values = {}
    for line in content.splitlines():
        key, separator, value = line.strip().partition('=')
        if key not in {ENABLED, HASH}:
            continue
        if not separator or key in values:
            raise OwnerAuthenticationError('Owner credential configuration is unavailable or invalid.')
        values[key] = value
    if values.get(ENABLED) != 'true':
        raise OwnerAuthenticationError('Owner authentication is not configured; sensitive operation denied.')
    return validate_hash(values.get(HASH))


class Argon2Provider:
    def __init__(self):
        try:
            from argon2 import PasswordHasher, Type
            from argon2.exceptions import VerificationError
        except ImportError:
            raise OwnerAuthenticationError('Argon2id dependency is unavailable; sensitive operation denied.') from None
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1,
                                     hash_len=32, salt_len=16, type=Type.ID)
        self.verification_error = VerificationError

    def hash(self, secret):
        return validate_hash(self.hasher.hash(secret, salt=os.urandom(16)))

    def verify(self, encoded, secret):
        validate_hash(encoded)
        try:
            return self.hasher.verify(encoded, secret) is True
        except self.verification_error:
            return False


def hidden_secret(prompt):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise OwnerAuthenticationError('Owner authentication requires a private interactive terminal.')
    with warnings.catch_warnings():
        # getpass must never fall back to echoed stdin input.
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise OwnerAuthenticationError('Owner authentication cancelled or unavailable.') from None


class OwnerAuthenticator:
    MAX_FAILURES = 3
    COOLDOWN = 30

    def __init__(self, config_path, *, reader=hidden_secret, provider_factory=Argon2Provider, clock=monotonic):
        self.path = Path(config_path)
        self.reader = reader
        self.provider_factory = provider_factory
        self.clock = clock
        self.failures = 0
        self.until = 0
        self.lock = Lock()

    def authenticate(self, request):
        if type(request) is not OwnerRequest:
            raise OwnerAuthenticationError('Invalid owner authorization request.')
        if not self.lock.acquire(blocking=False):
            raise OwnerAuthenticationError('Owner authentication is already in progress.')
        secret = None
        try:
            now = self.clock()
            if now < self.until:
                raise OwnerAuthenticationError('Owner authentication temporarily locked; retry later.')
            if self.until:
                self.failures = 0
                self.until = 0
            encoded = load_hash(self.path)
            provider = self.provider_factory()  # Fail before prompting if absent.
            secret = self.reader('Owner security passphrase (hidden): ')
            valid = (type(secret) is str and 12 <= len(secret) <= 1024 and
                     '\x00' not in secret and provider.verify(encoded, secret))
            # A configuration change during entry invalidates this request.
            if load_hash(self.path) != encoded:
                raise OwnerAuthenticationError('Owner credential configuration changed; request denied.')
            if not valid:
                self.failures += 1
                if self.failures >= self.MAX_FAILURES:
                    self.until = self.clock() + self.COOLDOWN
                raise OwnerAuthenticationError('Owner authentication failed; request denied.')
            self.failures = 0
            # No token, session grant, cached success or executable permission.
        except OwnerAuthenticationError:
            raise
        except (Exception, KeyboardInterrupt):
            raise OwnerAuthenticationError('Owner authentication cancelled or unavailable.') from None
        finally:
            # Python immutable strings cannot be reliably wiped. Do not copy,
            # cache, log, persist or forward the submitted secret.
            secret = None
            self.lock.release()
