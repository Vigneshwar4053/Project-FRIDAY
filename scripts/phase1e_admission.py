"""Fail-closed Phase 1E admission and owned-session watchdog.

Monitored admission is supplementary: it never substitutes for an aggregate
storage quota or an isolated memory domain covering the embedding process.
No document, storage backend, model or application runtime is opened here.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import stat
import subprocess
from threading import Event, Thread
from time import monotonic

MIB = 1024 ** 2
GIB = 1024 ** 3


class AdmissionDenied(RuntimeError):
    """Fixed diagnostics only; never include document or process contents."""


@dataclass(frozen=True)
class ResourceSample:
    storage_bytes: int
    additional_rss_bytes: int
    available_ram_bytes: int

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in
               (self.storage_bytes, self.additional_rss_bytes, self.available_ram_bytes)):
            raise AdmissionDenied('Resource measurements unavailable or malformed.')


def admit(sample, *, reserved_storage=0, reserved_rss=0):
    if type(sample) is not ResourceSample or any(type(v) is not int or v < 0
                                                for v in (reserved_storage, reserved_rss)):
        raise AdmissionDenied('Invalid resource admission request.')
    if sample.storage_bytes + reserved_storage > 100 * MIB:
        raise AdmissionDenied('Aggregate storage admission denied.')
    if sample.additional_rss_bytes + reserved_rss > 2 * GIB:
        raise AdmissionDenied('Additional RAM admission denied.')
    if sample.available_ram_bytes - reserved_rss < 2 * GIB:
        raise AdmissionDenied('Available host RAM admission denied.')


def available_ram():
    try:
        entries = [line for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith('MemAvailable:')]
        if len(entries) != 1 or entries[0].split()[2] != 'kB':
            raise ValueError()
        value = int(entries[0].split()[1]) * 1024
        if value < 0:
            raise ValueError()
        return value
    except (OSError, ValueError, IndexError):
        raise AdmissionDenied('Available host RAM could not be measured.') from None


def private_storage_size(root):
    """Count logical and allocated bytes; never repair existing permissions."""
    logical = allocated = 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        for path in [Path(folder), *[Path(folder) / n for n in dirs + files]]:
            info = path.lstat()
            directory = stat.S_ISDIR(info.st_mode)
            if (path.name == '.env' or path.name.startswith('.env.') or
                    info.st_uid != os.getuid() or stat.S_ISLNK(info.st_mode) or
                    not (directory or stat.S_ISREG(info.st_mode)) or
                    stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
                    (not directory and info.st_nlink != 1)):
                raise AdmissionDenied('Owned storage identity or privacy check failed.')
            if not directory:
                logical += info.st_size
                allocated += info.st_blocks * 512
    if not root.exists() or not root.is_dir():
        raise AdmissionDenied('Owned storage directory is unavailable.')
    return max(logical, allocated)


def require_enforced_bounds(*, aggregate_storage_quota_verified,
                            isolated_embedding_memory_limit_verified):
    # Only trusted platform code may supply these findings after establishing
    # and verifying the relevant kernel controls, not a CLI flag or document.
    if aggregate_storage_quota_verified is not True:
        raise AdmissionDenied('No verified aggregate 100 MiB storage quota; indexing must not start.')
    if isolated_embedding_memory_limit_verified is not True:
        raise AdmissionDenied('No verified isolated embedding memory limit; indexing must not start.')


class OwnedSessionWatchdog:
    """Bound a runner that this process spawned, without signalling Ollama.

    The runner must own its worker lifecycle; this watchdog does not claim that
    terminating an HTTP client cancels inference in a separate Ollama daemon.
    """
    def __init__(self, process, cancelled, *, seconds=300):
        if (not isinstance(process, subprocess.Popen) or not isinstance(cancelled, Event) or
                type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300):
            raise AdmissionDenied('Invalid owned-session watchdog.')
        try:
            fields = Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[1]) != os.getpid() or process.poll() is not None:
                raise ValueError()
        except (OSError, ValueError, IndexError):
            raise AdmissionDenied('Watchdog requires a live direct child of this runner.') from None
        self.process = process
        self.cancelled = cancelled
        self.deadline = monotonic() + seconds
        self.stopped = Event()
        self.expired = Event()
        self.thread = Thread(target=self._watch, daemon=True)

    def _watch(self):
        if self.stopped.wait(max(0, self.deadline - monotonic())):
            return
        self.expired.set()
        self.cancelled.set()
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
            except ProcessLookupError:
                pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(2)
