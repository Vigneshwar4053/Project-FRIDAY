"""Explicitly installed user service; never modifies the existing GUI autostart."""
import os
from pathlib import Path
import subprocess
from .runtime import ROOT

NAME='zorvyq-awareness.service'


def unit_text(root=ROOT):
    # systemd values use their own quoting; percent must be escaped.
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    return '\n'.join(['[Unit]','Description=ZORVYQ opt-in local digital awareness',
        'After=graphical-session.target','PartOf=graphical-session.target','', '[Service]',
        'Type=simple','WorkingDirectory='+quote(root),
        'ExecStart='+quote(root/'.venv/bin/python')+' -B -m zorvyq.awareness --daemon',
        'Restart=on-failure','RestartSec=10','TimeoutStopSec=25','UMask=0077',
        'NoNewPrivileges=true','RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6',
        'IPAddressDeny=any','IPAddressAllow=localhost',
        'StandardOutput=null','StandardError=null','', '[Install]',
        'WantedBy=graphical-session.target',''])


class BackgroundService:
    def __init__(self,directory=None):
        base=os.environ.get('XDG_CONFIG_HOME','')
        self.directory=Path(directory) if directory else (Path(base) if base.startswith('/') else Path.home()/'.config')/'systemd/user'
        self.path=self.directory/NAME

    def apply(self,enable,*,approved=False):
        if not approved:raise PermissionError('Explicit independent background monitoring approval required')
        text=unit_text()
        if self.path.is_symlink():raise ValueError('Unsafe service path')
        if self.path.exists() and self.path.read_text()!=text:raise ValueError('Existing service differs; review it manually')
        if enable:
            self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(text)
            # Only named desktop environment values, never the whole environment.
            self.run('import-environment','DISPLAY','WAYLAND_DISPLAY','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP')
            self.run('daemon-reload');self.run('enable','--now',NAME)
        else:self.run('disable','--now',NAME)

    @staticmethod
    def run(*args):
        result=subprocess.run(['systemctl','--user',*args],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25,check=False)
        if result.returncode:raise OSError('User monitoring service unavailable')
