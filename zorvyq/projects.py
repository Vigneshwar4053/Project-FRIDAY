"""Explicit project chooser; shares the original validated recent-work database."""
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
from time import monotonic
from friday.desktop.recent import RecentWorkQueue
from friday.memory.manager import MemoryManager

PROJECT_ROOT = Path('/home/vigneshwar/Projects')

def greeting(now=None):
    hour = (now or datetime.now().astimezone()).hour
    return 'Good '+('morning' if 5 <= hour < 12 else 'afternoon' if 12 <= hour < 17 else 'evening')+'! Welcome back.'

class Projects:
    def __init__(self, database, root=PROJECT_ROOT, *, hidden=False):
        self.root = Path(root).resolve()
        self.database = Path(database)
        self.hidden = hidden
        self.choices = ()
        self.expires = 0

    def validate(self, path):
        lexical = Path(path)
        if '..' in lexical.parts or any(not c.isprintable() for c in str(lexical)):
            raise ValueError('Invalid project path.')
        resolved = lexical.resolve(strict=True)
        if not resolved.is_dir() or lexical.parent != self.root or resolved.parent != self.root:
            raise ValueError('Project must be a direct child inside the approved project root.')
        if lexical.name.startswith('.') and not self.hidden:
            raise ValueError('Hidden projects are disabled.')
        return resolved

    def enumerate(self):
        self.cancel()
        if not shutil.which('code'):
            raise ValueError('VS Code launcher unavailable. Install/configure code with owner approval.')
        rows = []
        for path in self.root.iterdir():
            try:
                self.validate(path)
                rows.append(path)
            except (ValueError, OSError):
                continue
        self.choices = tuple(sorted(rows, key=lambda p: (p.name.casefold(), p.name)))
        self.expires = monotonic()+120
        return self.choices

    def cancel(self):
        self.choices = ()
        self.expires = 0

    def select(self, number):
        rows, deadline = self.choices, self.expires
        self.cancel()
        if monotonic() > deadline or type(number) is not int or not 1 <= number <= len(rows):
            raise ValueError('Invalid or expired project selection. Choose projects again.')
        return self.open(rows[number-1])

    def select_snapshot(self, number, snapshot):
        if snapshot is not self.choices:
            raise ValueError('This project list is stale. Choose projects again.')
        return self.select(number)

    def open(self, path):
        path = self.validate(path)
        binary = shutil.which('code')
        if not binary:
            raise ValueError('VS Code launcher unavailable.')
        result = subprocess.run([binary, '--new-window', str(path)], shell=False,
                                timeout=20, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise ValueError('VS Code rejected the launch; no recent entry saved.')
        identity = path.stat()
        scope = self.root.stat()
        lease = dict(record_operation='open_resolved_target', record_arguments=dict(application_id='vscode',
            scope=str(self.root), scope_identity=[scope.st_dev, scope.st_ino], directory=True),
            application_id='vscode', path=path, identity=[identity.st_dev, identity.st_ino], url=None)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        # Owner-only on first creation; leave existing database permissions intact.
        try:
            import os
            fd = os.open(self.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        with MemoryManager(self.database, recent_limit=10) as memory:
            RecentWorkQueue(memory).record(lease, 'launch_accepted')
        return str(path)

    def recent(self):
        if not self.database.exists():
            return ()
        result = []
        with MemoryManager(self.database, recent_limit=10) as memory:
            queue = RecentWorkQueue(memory)
            for row in queue.rows(limit=10):
                try:
                    descriptor = queue.decode(row)
                    path = descriptor['path']
                    if path and not Path(path).is_dir():
                        continue
                    result.append((row, descriptor))
                except (ValueError, OSError, KeyError, TypeError):
                    continue
        return tuple(result)

    def remove(self, entry_id=None):
        if self.database.exists():
            with MemoryManager(self.database) as memory:
                with memory._database.transaction() as db:
                    if entry_id is None:
                        db.execute('DELETE FROM recent_work')
                    else:
                        db.execute('DELETE FROM recent_work WHERE entry_id=?', (entry_id,))
