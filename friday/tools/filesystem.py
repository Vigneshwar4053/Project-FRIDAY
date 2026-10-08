"""Explicit local path boundary using Linux descriptor-relative operations."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import stat
from friday.tools.grants import directory_descriptor, lexical_path
from friday.tools.sensitive import SensitivePaths

MAX_DIRECTORY_ENTRIES = 100


class OutsideRoots(ValueError):
    """A valid lexical path needs an explicit read grant."""


class FileSystemPolicy:
    """Trusted roots only; relative paths use the first root. Symlinks are denied."""
    def __init__(self, allowed_roots, max_file_size=1024 * 1024, *,
                 write_roots=None, max_directory_entries=MAX_DIRECTORY_ENTRIES,
                 sensitive_paths=None, grant_store=None):
        if type(max_file_size) is not int or max_file_size <= 0:
            raise ValueError('Maximum file size must be a positive integer.')
        if type(max_directory_entries) is not int or max_directory_entries <= 0:
            raise ValueError('Maximum directory entries must be a positive integer.')
        roots = tuple(dict.fromkeys(lexical_path(os.fspath(root)).absolute() for root in allowed_roots))
        if not roots:
            raise ValueError('Explicit existing directory roots are required.')
        for root in roots:
            if not stat.S_ISDIR(root.stat(follow_symlinks=False).st_mode):
                raise ValueError('Explicit existing directory roots are required.')
            with directory_descriptor(root):
                pass  # Validate components without canonicalizing through symlinks.
        self._roots = roots
        self.sensitive = sensitive_paths or SensitivePaths()
        self.grant_store = grant_store
        self._operation = ContextVar('filesystem_operation', default=None)
        self._approval = ContextVar('filesystem_approval', default=None)
        self._max_file_size = max_file_size
        self.max_directory_entries = max_directory_entries
        self._write_roots = (roots[0],) if write_roots is None else tuple(
            lexical_path(os.fspath(root)).absolute() for root in write_roots)
        if any(root not in roots for root in self._write_roots):
            raise ValueError('Write roots must be explicit allowed roots.')

    @property
    def allowed_roots(self):
        return self._roots

    @property
    def max_file_size(self):
        return self._max_file_size

    def persistent_grants(self):
        return self.grant_store.load() if self.grant_store is not None else ()

    def candidate(self, requested, *, include_persistent=False, home_aliases=False):
        """Resolve spelling only; this does not authorize the resulting path."""
        path = lexical_path(requested)
        roots = self._roots[1:]
        if include_persistent:
            roots = (*roots, *(g.folder for g in self.persistent_grants()))
        aliases = {}
        for root in dict.fromkeys(roots):
            aliases.setdefault(root.name.casefold(), []).append(root)
        if not path.is_absolute() and path.parts:
            candidates = aliases.get(path.parts[0].casefold(), [])
            if len(candidates) > 1:
                raise ValueError('Folder alias is ambiguous; use an absolute path.')
            if candidates:
                local = self._roots[0] / path.parts[0]
                if local != candidates[0] and os.path.lexists(local):
                    raise ValueError('Folder alias conflicts with a project entry; use an absolute path.')
                path = candidates[0].joinpath(*path.parts[1:])
            elif home_aliases and path.parts[0].casefold() in {
                    'downloads', 'documents', 'desktop', 'pictures', 'videos', 'music', 'public', 'templates'}:
                if not os.path.lexists(self._roots[0] / path.parts[0]):
                    path = Path.home() / path.parts[0].capitalize() / Path(*path.parts[1:])
        if not path.is_absolute():
            path = self._roots[0] / path
        path = lexical_path(str(path))
        if self.sensitive.excluded(path):
            raise ValueError('Path is excluded by privacy policy.')
        return path

    def resolve(self, requested):
        interactive_read = self._operation.get() in {'read_file', 'list_directory'}
        path = self.candidate(requested, include_persistent=interactive_read,
                              home_aliases=interactive_read)
        canonical = path.resolve(strict=False)
        if self.sensitive.excluded(canonical):
            raise ValueError('Path is excluded by privacy policy.')
        grants = self.persistent_grants() if interactive_read else ()
        roots = (*self._roots, *(g.folder for g in grants))
        approval = self._approval.get()
        if approval is not None and path == approval.target and self._operation.get() == approval.operation:
            roots = (*roots, approval.folder.folder)
        for root in roots:
            # Check both lexical and canonical boundaries. Descriptor traversal
            # below additionally rejects every symlink, including in-root ones.
            if path.is_relative_to(root) and canonical.is_relative_to(root):
                return root, path.relative_to(root)
        raise OutsideRoots('Path is outside allowed roots.')

    @contextmanager
    def request_access(self, operation, approval=None):
        operation_token = self._operation.set(operation)
        approval_token = self._approval.set(approval)
        try:
            yield
        finally:
            self._approval.reset(approval_token)
            self._operation.reset(operation_token)

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
            for part in root.parts[1:]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            expected = None
            if self._operation.get() in {'read_file', 'list_directory'}:
                expected = next((g for g in self.persistent_grants() if g.folder == root), None)
            approval = self._approval.get()
            if approval is not None and root == approval.folder.folder:
                expected = approval.folder
            if expected is not None:
                metadata = os.fstat(fd)
                if (metadata.st_dev, metadata.st_ino) != (expected.device, expected.inode):
                    raise ValueError('Approved folder was replaced.')
            for part in relative.parts[:-1]:
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
                approval = self._approval.get()
                if approval is not None:
                    metadata = os.fstat(fd)
                    if (Path(display) != approval.target or
                        (metadata.st_dev, metadata.st_ino) != approval.identity):
                        raise ValueError('Approved target was replaced.')
                yield fd, display
            finally:
                os.close(fd)


def regular_file(fd):
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('A regular, singly linked file is required.')
    return metadata
