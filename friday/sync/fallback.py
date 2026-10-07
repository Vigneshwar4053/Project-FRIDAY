"""Standard-library binary gate; no native dependency or background workers."""
from threading import Lock
from friday.sync.base import ManagedSynchronization


class PythonSemaphore(ManagedSynchronization):
    backend_name = 'Python fallback'

    def __init__(self, *, fallback_reason: str | None = None):
        super().__init__()
        self._lock = Lock()
        self.fallback_reason = fallback_reason

    def _acquire_resource(self) -> None:
        self._lock.acquire()

    def _release_resource(self) -> None:
        self._lock.release()

    def _close_resource(self) -> None:
        pass  # No native allocation; closed-state checks forbid later use.
