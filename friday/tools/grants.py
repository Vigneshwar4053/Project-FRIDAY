"""Strict read-only grant records; no conversational state or model decisions."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
from uuid import uuid4

from friday.tools.sensitive import SensitivePaths

MAX_GRANTS = 64
MAX_STORE_BYTES = 65536
MAX_PATH_BYTES = 4096
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class PermissionStoreError(ValueError):
    """Generic failure safe to show without private paths or store contents."""


def lexical_path(value):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError('Invalid path.')
    if len(value.encode('utf-8', errors='strict')) > MAX_PATH_BYTES:
        raise ValueError('Path is too long.')
    path = Path(value).expanduser()
    if '..' in path.parts:
        raise ValueError('Parent traversal is not allowed.')
    if len(str(path).encode('utf-8', errors='strict')) > MAX_PATH_BYTES:
        raise ValueError('Path is too long.')
    if path.is_absolute():
        path = Path('/').joinpath(*path.parts[1:])
    return path


@contextmanager
def directory_descriptor(path, *, create=False):
    """Walk absolute directories, rejecting symlinks at every component."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('An absolute directory is required.')
    fd = os.open('/', _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


@dataclass(frozen=True)
class FolderGrant:
    folder: Path
    device: int
    inode: int
    scope: str = 'READ_ONLY'


def approved_folder(path, sensitive):
    path = lexical_path(str(path))
    home = Path.home().absolute()
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if (not path.is_absolute() or len(path.parts) <= 2 or home.is_relative_to(path) or account_home.is_relative_to(path) or
        path in {home / '.config', home / '.local', home / '.local' / 'share'} or
        path.parts[1] in {'etc', 'proc', 'sys', 'dev', 'usr', 'bin', 'sbin', 'lib',
                         'lib64', 'boot', 'run', 'root'} or sensitive.excluded(path)):
        raise ValueError('Folder is not eligible for interactive authorization.')
    with directory_descriptor(path) as fd:
        metadata = os.fstat(fd)
    return FolderGrant(path, metadata.st_dev, metadata.st_ino)


def _private_file(metadata):
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
        metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise PermissionStoreError('Permission storage is unavailable.')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate key.')
        result[key] = value
    return result


class PermissionStore:
    """Reload on every use; atomic snapshots and nonblocking process locks.

    The containing directory must be owned by this user and mode 0700. Missing
    storage is empty; malformed/insecure storage fails closed. No grant cache.
    """
    def __init__(self, path, sensitive=None):
        path = lexical_path(str(path))
        if not path.is_absolute():
            raise ValueError('Permission store path must be absolute.')
        self.path = path
        self.sensitive = sensitive or SensitivePaths()
        self._failed = False

    @contextmanager
    def _locked(self, *, create=False):
        with directory_descriptor(self.path.parent, create=create) as directory:
            metadata = os.fstat(directory)
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise PermissionStoreError('Permission storage is unavailable.')
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT
            lock = os.open('.grants.lock', flags, 0o600, dir_fd=directory)
            try:
                _private_file(os.fstat(lock))
                fcntl.flock(lock, (fcntl.LOCK_EX if create else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                yield directory
            finally:
                os.close(lock)

    def _read(self, directory):
        try:
            os.stat('.grants.pending', dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PermissionStoreError('Permission storage is unavailable.')
        try:
            fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                         os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return ()
        try:
            metadata = os.fstat(fd)
            _private_file(metadata)
            if metadata.st_size > MAX_STORE_BYTES:
                raise ValueError('Store exceeds limit.')
            chunks, remaining = [], MAX_STORE_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 8192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b''.join(chunks)
            if len(content) > MAX_STORE_BYTES:
                raise ValueError('Store exceeds limit.')
        finally:
            os.close(fd)
        data = json.loads(content.decode('utf-8', errors='strict'), object_pairs_hook=_object)
        if (type(data) is not dict or set(data) != {'version', 'grants'} or
            type(data['version']) is not int or data['version'] != 1 or
            type(data['grants']) is not list or len(data['grants']) > MAX_GRANTS):
            raise ValueError('Invalid grant schema.')
        grants = []
        for item in data['grants']:
            if (type(item) is not dict or set(item) != {'folder', 'scope', 'device', 'inode'} or
                item['scope'] != 'READ_ONLY' or type(item['folder']) is not str or
                type(item['device']) is not int or item['device'] < 0 or
                type(item['inode']) is not int or item['inode'] <= 0):
                raise ValueError('Invalid grant.')
            grant = approved_folder(item['folder'], self.sensitive)
            if str(grant.folder) != item['folder'] or (grant.device, grant.inode) != (item['device'], item['inode']):
                raise ValueError('Folder was replaced.')
            if grant.folder in [g.folder for g in grants]:
                raise ValueError('Duplicate grant.')
            grants.append(grant)
        return tuple(grants)

    def load(self):
        if self._failed:
            raise PermissionStoreError('Permission storage is unavailable.')
        try:
            # Missing private directory is the normal empty initial state.
            with self._locked() as directory:
                return self._read(directory)
        except FileNotFoundError:
            # Only a genuinely missing store AND lock is an initial empty state.
            # Existing snapshots without their lock are treated as corrupt.
            if os.path.lexists(self.path) or os.path.lexists(self.path.parent / '.grants.pending'):
                self._failed = True
                raise PermissionStoreError('Permission storage is unavailable.') from None
            return ()
        except (OSError, ValueError, UnicodeError, RuntimeError):
            self._failed = True
            raise PermissionStoreError('Permission storage is unavailable.') from None

    def _publish(self, directory, grants):
        content = json.dumps({'version': 1, 'grants': [
            {'folder': str(g.folder), 'scope': g.scope, 'device': g.device, 'inode': g.inode}
            for g in grants]}, ensure_ascii=True).encode('utf-8')
        if len(grants) > MAX_GRANTS or len(content) > MAX_STORE_BYTES:
            raise ValueError('Grant limit exceeded.')
        temporary = '.grants-' + uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                     os.O_CLOEXEC, 0o600, dir_fd=directory)
        published = False
        try:
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError('Write made no progress.')
                view = view[written:]
            os.fsync(fd)
            # A durable pending marker gates readers across errors/restarts.
            # Publication and revocation are durable before the marker is
            # removed. A crash can resurrect the marker (safe denial), but
            # cannot resurrect the replaced, revoked grant snapshot.
            marker = os.open('.grants.pending', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
            try:
                os.fsync(marker)
            finally:
                os.close(marker)
            os.fsync(directory)
            os.replace(temporary, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
            published = True
            os.fsync(directory)
            # Final transaction step: no further fallible persistence work.
            os.unlink('.grants.pending', dir_fd=directory)
        finally:
            os.close(fd)
            if not published:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def add(self, grant):
        try:
            if self._failed:
                raise PermissionStoreError('Permission storage is unavailable.')
            verified = approved_folder(str(grant.folder), self.sensitive)
            if verified != grant:
                raise ValueError('Folder was replaced.')
            with self._locked(create=True) as directory:
                grants = self._read(directory)
                if grant.folder not in [g.folder for g in grants]:
                    self._publish(directory, (*grants, grant))
        except (OSError, ValueError, UnicodeError, RuntimeError):
            self._failed = True
            raise PermissionStoreError('Permission storage is unavailable.') from None

    def revoke(self, folder):
        try:
            if self._failed:
                raise PermissionStoreError('Permission storage is unavailable.')
            with self._locked(create=True) as directory:
                grants = self._read(directory)
                remaining = tuple(g for g in grants if g.folder != folder)
                if len(remaining) == len(grants):
                    return False
                self._publish(directory, remaining)
                return True
        except (OSError, ValueError, UnicodeError, RuntimeError):
            self._failed = True
            raise PermissionStoreError('Permission storage is unavailable.') from None
