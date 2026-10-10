"""Lazy pinned system interpreter for observation only. No helper is started on import."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Lock

from friday.desktop.accessibility import AccessibilityBackend, DesktopFailure
from friday.desktop.observation import APPLICATION_IDS, DesktopStatus, WindowSnapshot, METADATA_ONLY, METADATA_ROLES
from friday.desktop.registry import Application, ApplicationRegistry
from friday.desktop.runtime import desktop_environment
from friday.desktop.snap import ReviewedSnap

# Recomputed explicitly only when reviewed worker source changes.
WORKER_SHA256 = 'e1e96dcfcee218b885c4ed707d94c673f063d10e4ed9c2225e3a1c548b21c41a'


class AtspiBackend(AccessibilityBackend):
    # No focus, click, text entry, shortcut or synthetic-event implementation.
    supports_actions = False
    observation_mode = METADATA_ONLY

    def __init__(self):
        self.interpreter = ApplicationRegistry((Application('atspi_runtime', 'System AT-SPI runtime', (),
                                               (Path('/usr/bin/python3.14'),), ''),))
        self.applications = ApplicationRegistry()
        self.snap = ReviewedSnap()
        self._child = None
        self._child_lock = Lock()

    def cancel(self):
        with self._child_lock:
            if self._child is not None and self._child.poll() is None:
                try:
                    self._child.terminate()  # Only FRIDAY's observation worker.
                except ProcessLookupError:
                    pass

    def _executables(self, application_id):
        try:
            with self.applications.executable(application_id) as native:
                return [list(native[3])], ('native', native[1], native[3])
        except (OSError, ValueError):
            if application_id not in {'vscode', 'firefox'}:
                raise DesktopFailure(DesktopStatus.UNSUPPORTED) from None
        review = self.snap.review(application_id)
        package = 'code' if application_id == 'vscode' else 'firefox'
        root = (Path('/snap') / package / 'current').resolve(strict=True)
        candidates = ([root / 'usr/share/code/code'] if package == 'code' else
                      [root / 'usr/lib/firefox/firefox', root / 'usr/lib/firefox/firefox-bin'])
        fingerprints = []
        for candidate in candidates:
            try:
                path = candidate.resolve(strict=True)
                if not path.is_relative_to(root):
                    continue
                info = path.stat()
                if info.st_uid != 0 or not path.is_file():
                    continue
                fingerprints.append([info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns])
            except OSError:
                continue
        if not fingerprints:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED)
        return fingerprints, ('snap', review)

    def _request(self, operation, application_id, window, deadline):
        deadline.check()
        if application_id not in APPLICATION_IDS:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED)
        _, environment = desktop_environment()
        if environment is None or 'XDG_RUNTIME_DIR' not in environment:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED)
        try:
            executables, review = self._executables(application_id)
            deadline.check()
            worker = Path(__file__).with_name('accessibility_worker.py')
            from friday.tools.grants import directory_descriptor
            with directory_descriptor(worker.parent) as parent:
                fd = os.open(worker.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    import stat
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
                        raise ValueError('Untrusted worker.')
                    source = os.read(fd, 32769)
                    if len(source) > 32768 or hashlib.sha256(source).hexdigest() != WORKER_SHA256:
                        raise ValueError('Worker source changed.')
                finally:
                    os.close(fd)
            with self.interpreter.executable('atspi_runtime') as binary:
                for dependency in (Path('/usr/lib/python3/dist-packages'),
                                   Path('/usr/lib/python3/dist-packages/gi/__init__.py'),
                                   Path('/usr/lib/x86_64-linux-gnu/girepository-1.0/Atspi-2.0.typelib')):
                    self.interpreter._trusted_path(dependency)
                local_site = Path('/usr/local/lib/python3.14/dist-packages')
                if local_site.exists():
                    self.interpreter._trusted_path(local_site)
                deadline.check()
                child = subprocess.Popen([str(binary[1]), '-I', '-B', '-c', source.decode('utf-8')],
                    executable=f'/proc/self/fd/{binary[2]}', pass_fds=(binary[2],), close_fds=True,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=environment, cwd='/', start_new_session=True)
            with self._child_lock:
                self._child = child
            try:
                payload = json.dumps({'operation': operation, 'application_id': application_id,
                    'window': asdict(window) if window else None, 'executables': executables,
                    'mode': METADATA_ONLY}).encode('utf-8')
                while True:
                    deadline.check()
                    try:
                        output, _ = child.communicate(input=payload, timeout=min(.1, max(.001, deadline.expires - deadline.clock())))
                        break
                    except subprocess.TimeoutExpired:
                        payload = None
                deadline.check()
                if child.returncode != 0 or len(output) > 65536:
                    raise ValueError('Invalid worker response.')
                if self._executables(application_id)[1] != review:
                    raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
                result = json.loads(output)
                expected_fields = {'status', 'windows' if operation == 'list' else 'snapshot'}
                if type(result) is not dict or 'status' not in result:
                    raise ValueError('Invalid worker response.')
                status = DesktopStatus(result['status'])
                if status is not DesktopStatus.VERIFIED:
                    if set(result) != {'status'}:
                        raise ValueError('Invalid failure response.')
                    raise DesktopFailure(status)
                if set(result) != expected_fields:
                    raise ValueError('Unexpected worker fields.')
                return result
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=1)
                with self._child_lock:
                    self._child = None
        except DesktopFailure:
            raise
        except Exception:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED) from None

    def list_windows(self, application_id, deadline):
        result = self._request('list', application_id, None, deadline)
        snapshots = tuple(self._metadata_snapshot(value) for value in result['windows'])
        if any(s.elements or s.window.application_id != application_id for s in snapshots):
            raise DesktopFailure(DesktopStatus.UNSUPPORTED)
        return snapshots

    def observe(self, window, deadline):
        result = self._request('observe', window.application_id, window, deadline)
        snapshot = self._metadata_snapshot(result['snapshot'])
        if snapshot.window != window:
            raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
        return snapshot

    @staticmethod
    def _metadata_snapshot(value):
        try:
            snapshot = WindowSnapshot.from_data(value)
            if snapshot.sensitive or any(e.role not in METADATA_ROLES or e.label or
                    e.text is not None or e.actions or e.editable or e.sensitive or
                    e.effect != 'unknown' for e in snapshot.elements):
                raise ValueError('Metadata contract violated.')
            return snapshot
        except Exception:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED) from None
