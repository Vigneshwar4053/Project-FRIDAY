"""Read-only inventory and exact, owner-approved reversible login migration."""
from pathlib import Path
import configparser
import hashlib
import os
import tempfile

LEGACY_EXEC = 'Exec=/home/vigneshwar/Projects/FRIDAY/.venv/bin/python -B -m friday.main --adaptive'


def entry(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
        return dict(parser['Desktop Entry'])
    except (configparser.Error, KeyError):
        return {}


def enabled(text):
    data = entry(text)
    return bool(data) and data.get('hidden', 'false').lower() != 'true' and data.get('x-gnome-autostart-enabled', 'true').lower() != 'false'


def read(path):
    if path.is_symlink():
        raise ValueError('Refusing symlink startup target.')
    return path.read_text() if path.is_file() else ''


def disable(text):
    lines = [line for line in text.splitlines() if not line.startswith(('Hidden=', 'X-GNOME-Autostart-enabled='))]
    return '\n'.join(lines)+'\nHidden=true\nX-GNOME-Autostart-enabled=false\n'


class Startup:
    def __init__(self, home=None):
        self.home = Path(home) if home else Path.home()
        self.directory = self.home/'.config/autostart'
        self.legacy = self.directory/'friday.desktop'
        self.managed = self.directory/'com.zorvyq.ZORVYQ.desktop'
        self.launcher = self.home/'.local/share/applications/com.zorvyq.ZORVYQ.desktop'

    def inventory(self):
        legacy, managed = read(self.legacy), read(self.managed)
        return dict(legacy=str(self.legacy), effect='Runs legacy friday.main --adaptive with Terminal=true',
                    identified=LEGACY_EXEC in legacy.splitlines() and entry(legacy).get('terminal') == 'true',
                    legacy_enabled=enabled(legacy), enabled=enabled(managed),
                    fingerprint=hashlib.sha256((legacy+'\0'+managed).encode()).hexdigest())

    @staticmethod
    def write(path, text):
        if path.is_symlink():
            raise ValueError('Refusing symlink startup target.')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def apply(self, enabled, *, approved=False, fingerprint=None):
        state = self.inventory()
        if not approved or fingerprint != state['fingerprint']:
            raise PermissionError('Review and approve the exact current startup entries first.')
        if type(enabled) is not bool:
            raise ValueError('Invalid login setting.')
        old, managed = read(self.legacy), read(self.managed)
        if state['legacy_enabled'] and not state['identified']:
            raise ValueError('Unrecognized legacy startup; manual review required.')
        if managed and entry(managed).get('name') != 'ZORVYQ':
            raise ValueError('Unrecognized managed startup; manual review required.')
        template = read(self.launcher) if enabled else ''
        if enabled:
            data = entry(template)
            if data.get('terminal') != 'false' or data.get('name') != 'ZORVYQ':
                raise ValueError('Install and verify the graphical launcher first.')
            # Reject a stale/missing installed wrapper before changing legacy startup.
            import shlex
            args = shlex.split(data.get('exec', ''))
            if len(args) != 1 or not os.access(args[0], os.X_OK):
                raise ValueError('Graphical launcher is unavailable.')
            expected = Path(__file__).resolve().parents[1]/'bin/zorvyq'
            actual = Path(args[0])
            if actual != expected:
                commands = [line for line in read(actual).splitlines() if line and not line.startswith('#')]
                if len(commands) != 1 or shlex.split(commands[0]) != ['exec', str(expected), '$@']:
                    raise ValueError('Installed launcher is stale or unrecognized. Reinstall and test it first.')
        backup = self.legacy.with_suffix('.desktop.zorvyq-backup')
        if state['legacy_enabled'] and backup.exists() and read(backup) != old:
            raise ValueError('Backup differs; review before changing startup.')
        new = (template.rstrip()+'\nX-GNOME-Autostart-enabled=true\n') if enabled else (disable(managed) if managed else '')
        # Prepare the verified replacement before disabling the old entry. Roll
        # back both files on ordinary I/O errors; the original backup is retained.
        try:
            if state['legacy_enabled']:
                self.write(backup, old)
                self.write(self.legacy, disable(old))
            if new:
                self.write(self.managed, new)
        except OSError:
            if old:
                self.write(self.legacy, old)
            if managed:
                self.write(self.managed, managed)
            raise

    def restore_legacy(self, *, approved=False):
        if not approved:
            raise PermissionError('Explicit restoration approval required.')
        backup = read(self.legacy.with_suffix('.desktop.zorvyq-backup'))
        if LEGACY_EXEC not in backup.splitlines() or read(self.legacy) != disable(backup):
            raise ValueError('Legacy entry changed; review before restoring.')
        managed = read(self.managed)
        if managed:
            self.write(self.managed, disable(managed))
        self.write(self.legacy, backup)
