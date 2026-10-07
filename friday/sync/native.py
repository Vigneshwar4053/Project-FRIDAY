"""Only this module uses ctypes. Paths are trusted application configuration."""
import ctypes
import errno
from pathlib import Path

from friday.sync.base import ManagedSynchronization, NativeUnavailable, SynchronizationError

DEFAULT_LIBRARY_PATH = Path(__file__).resolve().parents[2] / 'native' / 'sync' / 'libfriday_sync.so'


class NativeSemaphore(ManagedSynchronization):
    backend_name = 'Native C (POSIX mutex)'

    def __init__(self, library_path: str | Path = DEFAULT_LIBRARY_PATH):
        super().__init__()
        path = Path(library_path).resolve()
        try:
            self._library = ctypes.CDLL(str(path), use_errno=True)
            self._library.friday_semaphore_create.argtypes = []
            self._library.friday_semaphore_create.restype = ctypes.c_void_p
            for name in ('acquire', 'release', 'destroy'):
                function = getattr(self._library, f'friday_semaphore_{name}')
                function.argtypes = [ctypes.c_void_p]
                function.restype = ctypes.c_int
        except (OSError, AttributeError) as exc:
            raise NativeUnavailable('Native synchronization library is missing or incompatible; build native/sync.') from exc
        self._handle = self._library.friday_semaphore_create()
        if not self._handle:
            raise NativeUnavailable(f'Native synchronization initialization failed (errno {ctypes.get_errno()}).')

    @staticmethod
    def _check(code: int, operation: str) -> None:
        if code:
            raise SynchronizationError(f'Native synchronization {operation} failed (error {code}).')

    def _acquire_resource(self) -> None:
        try:
            code = self._library.friday_semaphore_acquire(self._handle)
            self._check(code, 'acquire')
        except BaseException:
            # ctypes can deliver a pending Python signal after C acquired the
            # mutex but before returning its success code to Python. ERRORCHECK
            # unlock is safe here: EPERM means this thread never acquired it.
            cleanup = self._library.friday_semaphore_release(self._handle)
            if cleanup not in (0, errno.EPERM):
                self._check(cleanup, 'interrupted acquire cleanup')
            raise

    def _release_resource(self) -> None:
        self._check(self._library.friday_semaphore_release(self._handle), 'release')

    def _close_resource(self) -> None:
        self._check(self._library.friday_semaphore_destroy(self._handle), 'destroy')
        self._handle = None
