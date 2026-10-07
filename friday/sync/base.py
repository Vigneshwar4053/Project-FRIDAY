"""Binary execution gate interface and safe process-local lifecycle."""
from abc import ABC, abstractmethod
from threading import Lock, get_ident


class SynchronizationError(RuntimeError):
    """An acquire, release, or lifecycle failure safe to show to the user."""


class NativeUnavailable(SynchronizationError):
    """Native library could not be loaded or initialized; fallback is permitted."""


class Synchronization(ABC):
    backend_name = 'synchronization'
    fallback_reason: str | None = None

    @abstractmethod
    def acquire(self) -> None:
        """Block until exclusively acquired by the calling thread."""

    @abstractmethod
    def release(self) -> None:
        """Release from the acquiring thread."""

    @abstractmethod
    def close(self) -> None:
        """Close only while idle; repeated close is safe."""

    def __enter__(self) -> 'Synchronization':
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class ManagedSynchronization(Synchronization):
    """Protect destruction against holders/waiters; this lock starts no threads."""
    def __init__(self):
        self._state_lock = Lock()
        self._closed = False
        self._users = 0
        self._owner: int | None = None

    def _require_open(self) -> None:
        if self._closed:
            raise SynchronizationError('Synchronization resource is closed.')

    def acquire(self) -> None:
        with self._state_lock:
            self._require_open()
            if self._owner == get_ident():
                raise SynchronizationError('Synchronization is not reentrant.')
            self._users += 1
        acquired = False
        try:
            self._acquire_resource()
            acquired = True
            with self._state_lock:
                self._owner = get_ident()
        except BaseException:
            with self._state_lock:
                if acquired:
                    self._release_resource()
                    self._owner = None
                self._users -= 1
            raise

    def release(self) -> None:
        with self._state_lock:
            self._require_open()
            if self._owner != get_ident():
                raise SynchronizationError('Only the acquiring thread may release synchronization.')
            self._release_resource()
            self._owner = None
            self._users -= 1

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            if self._users:
                raise SynchronizationError('Cannot close synchronization while held or awaited.')
            self._close_resource()
            self._closed = True

    @abstractmethod
    def _acquire_resource(self) -> None:
        pass

    @abstractmethod
    def _release_resource(self) -> None:
        pass

    @abstractmethod
    def _close_resource(self) -> None:
        pass
