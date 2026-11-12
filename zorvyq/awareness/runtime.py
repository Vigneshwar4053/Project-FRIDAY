"""Reviewed, opt-in child processes. Never launches aw-qt or input watchers."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from time import monotonic
from .adapter import ActivityWatch, Unavailable
from .privacy import SENSITIVE

ROOT=Path(__file__).resolve().parents[2]


def discover(root=ROOT):
    manifest=json.loads((root/'third_party/activitywatch-manifest.json').read_text())
    result={}
    for name,record in manifest['executables'].items():
        path=root/record['path']
        if path.is_symlink() or not path.is_file() or not os.access(path,os.X_OK):
            raise ValueError('ActivityWatch executable unavailable')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=record['sha256']:raise ValueError('ActivityWatch executable checksum mismatch')
        result[name]=path
    return result


def session_type():
    # Inherited from the actual desktop; unknown is deliberately unsupported.
    return os.environ.get('XDG_SESSION_TYPE','unknown').lower()


def gnome_ready():
    try:
        result=subprocess.run(['gdbus','introspect','--session','--dest','org.gnome.Shell',
            '--object-path','/org/gnome/shell/extensions/FocusedWindow','--xml'],
            capture_output=True,timeout=2,check=False)
        return result.returncode==0 and b'org.gnome.shell.extensions.FocusedWindow' in result.stdout
    except (OSError,subprocess.TimeoutExpired):return False


def watcher_config(preferences):
    # Rules run BEFORE upstream persistence. Titles never leave awatcher in managed mode.
    lines=['[server]','host = "127.0.0.1"','port = 5600','', '[awatcher]',
           'poll-time-window-seconds = 1','poll-time-idle-seconds = 5','idle-timeout-seconds = 180']
    for key,pattern in [('match-title','(?i).*('+SENSITIVE.pattern+').*')]+[
            ('match-title','(?i).*'+re.escape(x)+'.*') for x in preferences['exclusions']]+[
            ('match-app-id','(?i).*'+re.escape(x)+'.*') for x in preferences['exclusions']]:
        lines+=['','[[awatcher.filters]]',key+' = '+json.dumps(pattern),
                'replace-app-id = "__zorvyq_excluded__"','replace-title = ""']
    for app in preferences['applications']:
        lines+=['','[[awatcher.filters]]','match-app-id = '+json.dumps('(?i)'+re.escape(app)),
                'replace-app-id = '+json.dumps(app),'replace-title = ""']
    # A neutral transition closes the preceding approved interval without revealing
    # the excluded application/title. ZORVYQ never persists this marker as usage.
    lines+=['','[[awatcher.filters]]','match-app-id = ".*"',
            'replace-app-id = "__zorvyq_excluded__"','replace-title = ""','']
    return '\n'.join(lines)


def external_watcher_present():
    """Identity check only, never read command lines or retain process metadata."""
    import itertools
    with os.scandir('/proc') as entries:
        for entry in itertools.islice((e for e in entries if e.name.isdecimal()),4096):
            try:
                path=Path(entry.path)
                if path.stat().st_uid==os.getuid() and (path/'exe').resolve().name in ('aw-awatcher','awatcher','aw-watcher-window'):
                    return True
            except OSError:continue
    return False


class LocalRuntime:
    def __init__(self,directory,adapter=None):
        self.directory=Path(directory);self.adapter=adapter or ActivityWatch()
        self.server=None;self.watcher=None;self.lease=None;self.paths=None
        self.settings=None;self.last_attempt=0;self.state='OFF'

    def _environment(self):
        env={k:v for k,v in os.environ.items() if 'proxy' not in k.lower() and k!='AW_API_KEY'}
        for variable,leaf in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:
            path=self.directory/leaf;path.mkdir(parents=True,mode=0o700,exist_ok=True);env[variable]=str(path)
        env['NO_PROXY']='*';return env

    def _spawn(self,args):
        return subprocess.Popen([str(a) for a in args],env=self._environment(),stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,umask=0o077)

    @staticmethod
    def _stop(process):
        if process is None or process.poll() is not None:return
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)

    def ensure(self,p):
        if not p['enabled'] or p['paused'] or not p['managed_runtime']:
            self.stop();return
        if self.paths is None:self.paths=discover()
        if self.lease is None:
            self.directory.mkdir(parents=True,mode=0o700,exist_ok=True)
            fd=os.open(self.directory/'runtime.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:os.close(fd);raise Unavailable('runtime_owned_elsewhere') from None
            self.lease=fd
        config=watcher_config(p)
        if config!=self.settings:
            self._stop(self.watcher);self.watcher=None
            file=self.directory/'awatcher.toml'
            fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(config)
            self.settings=config
        try:buckets=self.adapter.buckets()
        except Unavailable:
            if self.server is None or self.server.poll() is not None:
                if monotonic()-self.last_attempt<10:return
                self.last_attempt=monotonic()
                self.server=self._spawn([self.paths['server'],'--host','127.0.0.1','--port','5600'])
            self.state='STARTING';return
        self.state='WATCHER UNAVAILABLE'
        if self.watcher is None and external_watcher_present():
            # An independently configured watcher owns this stream; never overlap it.
            return
        if session_type()!='wayland' or 'GNOME' not in os.environ.get('XDG_CURRENT_DESKTOP','').upper():return
        if self.watcher is None or self.watcher.poll() is not None:
            if monotonic()-self.last_attempt<10:return
            self.last_attempt=monotonic()
            if not gnome_ready():return
            self.watcher=self._spawn([self.paths['wayland'],'--host','127.0.0.1','--port','5600',
                '--config',self.directory/'awatcher.toml'])
        # Only the consumer may promote to ON after actual event validation.

    def stop(self):
        self._stop(self.watcher);self._stop(self.server)
        self.watcher=self.server=None;self.state='OFF'
        if self.lease is not None:os.close(self.lease);self.lease=None
