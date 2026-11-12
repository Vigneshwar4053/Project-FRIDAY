"""Verify paths and dependencies without inference, audio, private reads or GUI startup."""
import argparse
import configparser
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import shlex

ROOT = Path(__file__).resolve().parents[1]


def verify(desktop=None):
    checks = {'checkout_launcher': os.access(ROOT/'bin/zorvyq', os.X_OK),
              'venv_python': os.access(ROOT/'.venv/bin/python', os.X_OK),
              'product_icon': (ROOT/'assets/zorvyq.svg').is_file(),
              'qt_widgets_dependency': importlib.util.find_spec('PySide6') is not None,
              'public_package': (ROOT/'zorvyq/__main__.py').is_file()}
    if desktop is not None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(desktop)
        section = parser['Desktop Entry'] if parser.has_section('Desktop Entry') else {}
        try:
            command = shlex.split(section.get('Exec', ''))
            executable = Path(command[0].replace('%%', '%')) if len(command) == 1 else Path('/missing')
        except ValueError:
            executable = Path('/missing')
        checks.update(desktop_name=section.get('Name') == 'ZORVYQ', terminal_hidden=section.get('Terminal') == 'false',
                      desktop_exec=executable.is_absolute() and executable.is_file() and os.access(executable,os.X_OK),
                      installed_icon=Path(section.get('Icon','/missing')).is_file())
        if Path('/usr/bin/desktop-file-validate').is_file():
            checks['desktop_spec_validation'] = subprocess.run(['/usr/bin/desktop-file-validate', str(desktop)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    return checks

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', type=Path)
    args = parser.parse_args()
    checks = verify(args.desktop)
    for key, passed in checks.items():
        print(('PASS' if passed else 'FAIL')+' '+key)
    sys.exit(0 if all(checks.values()) else 1)
