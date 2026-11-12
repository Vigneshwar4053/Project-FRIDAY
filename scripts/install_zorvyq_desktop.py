"""Install only user-local launch metadata. Never installs dependencies or moves data."""
import argparse
import os
from pathlib import Path
import shlex
import stat

ROOT = Path(__file__).resolve().parents[1]


def xdg(name, fallback):
    raw = os.environ.get(name)
    return Path(raw) if raw and Path(raw).is_absolute() else Path.home()/fallback


def desktop_quote(path):
    # Desktop Entry Exec is not a shell; preserve literal paths and field markers.
    value = str(path).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\'+char)
    return '"'+value+'"'


def install(prefix=None):
    data = Path(prefix)/'share' if prefix else xdg('XDG_DATA_HOME', '.local/share')
    binaries = Path(prefix)/'bin' if prefix else Path.home()/'.local/bin'
    launcher = binaries/'zorvyq'
    icon = data/'icons/hicolor/scalable/apps/com.zorvyq.ZORVYQ.svg'
    desktop = data/'applications/com.zorvyq.ZORVYQ.desktop'
    for path in (launcher, icon, desktop):
        if path.is_symlink():
            raise ValueError('Refusing symlink installation target.')
        path.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/bin/sh\nexec '+shlex.quote(str(ROOT/'bin/zorvyq'))+' "$@"\n')
    launcher.chmod(0o755)
    icon.write_bytes((ROOT/'assets/zorvyq.svg').read_bytes())
    template = (ROOT/'desktop/com.zorvyq.ZORVYQ.desktop.in').read_text()
    desktop.write_text(template.replace('@LAUNCHER@', desktop_quote(launcher)).replace('@ICON@', str(icon)))
    desktop.chmod(0o644)
    return desktop, launcher

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install ZORVYQ in user-local XDG applications')
    parser.add_argument('--prefix', type=Path, help='Alternative prefix for isolated verification')
    args = parser.parse_args()
    desktop, launcher = install(args.prefix)
    print('Desktop entry:', desktop)
    print('Launcher:', launcher)
