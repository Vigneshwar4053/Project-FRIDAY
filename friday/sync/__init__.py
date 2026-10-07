"""Native-first selection at startup; never fallback after runtime failure."""
from pathlib import Path
from friday.sync.base import NativeUnavailable, Synchronization, SynchronizationError
from friday.sync.fallback import PythonSemaphore
from friday.sync.native import DEFAULT_LIBRARY_PATH, NativeSemaphore


def create_synchronization(library_path: str | Path = DEFAULT_LIBRARY_PATH) -> Synchronization:
    try:
        return NativeSemaphore(library_path)
    except NativeUnavailable as exc:
        return PythonSemaphore(fallback_reason=str(exc))


__all__ = ['Synchronization', 'SynchronizationError', 'NativeUnavailable',
           'NativeSemaphore', 'PythonSemaphore', 'create_synchronization']
