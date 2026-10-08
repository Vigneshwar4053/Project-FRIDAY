"""Explicit local path boundary using Linux descriptor-relative operations."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat

MAX_DIRECTORY_ENTRIES = 100


class FileSystemPolicy:
    """Trusted roots only; relative paths use the first root. Symlinks are denied."""
    def __init__(self, allowed_roots, max_file_size=1024 * 1024, *,
                 write_roots=None, max_directory_entries=MAX_DIRECTORY_ENTRIES):
        if type(max_file_size) is not int or max_file_size <= 0:
            raise ValueError('Maximum file size must be a positive integer.')
        if type(max_directory_entries) is not int or max_directory_entries <= 0:
            raise ValueError('Maximum directory entries must be a positive integer.')
        roots = tuple(dict.fromkeys(Path(root).expanduser().resolve(strict=True) for root in allowed_roots))
        if not roots or any(not root.is_dir() for root in roots):
            raise ValueError('Explicit existing directory roots are required.')
        self._roots = roots
        self._max_file_size = max_file_size
        self.max_directory_entries = max_directory_entries
        self._write_roots = (roots[0],) if write_roots is None else tuple(
            Path(root).expanduser().resolve(strict=True) for root in write_roots)
        if any(root not in roots for root in self._write_roots):
            raise ValueError('Write roots must be explicit allowed roots.')
        aliases = {}
        # The project basename must not shadow project-relative source paths
        # (e.g. a FRIDAY root containing the Python package friday/).
        for root in roots[1:]:
            aliases.setdefault(root.name.casefold(), []).append(root)
        self._aliases = aliases

    @property
    def allowed_roots(self):
        return self._roots

    @property
    def max_file_size(self):
        return self._max_file_size

    def resolve(self, requested):
        if not isinstance(requested, str) or not requested.strip() or '\x00' in requested:
            raise ValueError('Invalid path.')
        path = Path(requested).expanduser()
        if '..' in path.parts:
            raise ValueError('Parent traversal is not allowed.')
        if not path.is_absolute() and path.parts:
            candidates = self._aliases.get(path.parts[0].casefold(), [])
            if len(candidates) > 1:
                raise ValueError('Folder alias is ambiguous; use an absolute path.')
            if candidates:
                local = self._roots[0] / path.parts[0]
                if local != candidates[0] and os.path.lexists(local):
                    raise ValueError('Folder alias conflicts with a project entry; use an absolute path.')
                path = candidates[0].joinpath(*path.parts[1:])
        if not path.is_absolute():
            path = self._roots[0] / path
        canonical = path.resolve(strict=False)
        for root in self._roots:
            # Check both lexical and canonical boundaries. Descriptor traversal
            # below additionally rejects every symlink, including in-root ones.
            if path.is_relative_to(root) and canonical.is_relative_to(root):
                return root, path.relative_to(root)
        raise ValueError('Path is outside allowed roots.')

    def require_writable(self, requested):
        root, relative = self.resolve(requested)
        path = root / relative
        if not any(path.is_relative_to(root) for root in self._write_roots):
            raise ValueError('Path is read-only.')

    @contextmanager
    def parent(self, requested):
        root, relative = self.resolve(requested)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open('/', flags)
        try:
            # Walk even the configured root without following replaced symlinks.
            for part in root.parts[1:] + relative.parts[:-1]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            yield fd, relative.name if relative.parts else '.', str(root / relative)
        finally:
            os.close(fd)

    @contextmanager
    def open(self, requested, flags, mode=0o600):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            self.require_writable(requested)
        with self.parent(requested) as (parent, name, display):
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         mode, dir_fd=parent)
            try:
                yield fd, display
            finally:
                os.close(fd)


def regular_file(fd):
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('A regular, singly linked file is required.')
    return metadata
