"""One approved GTK renderer; exact locations remain in the parent runtime."""
from contextlib import contextmanager
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
from uuid import uuid4

from friday.desktop.registry import Application, ApplicationRegistry
from friday.tools.grants import directory_descriptor

MAX_HISTORY=16
MAX_PACKET=65536

class BrowserHealthUnavailable(ValueError):
    """Health unknown: do not destroy a live process or offer another launch."""
# Updated only with the reviewed worker source, never with model/user input.
WORKER_SHA256='30eee7b1b9e497e9015f1e47d863850fa6baeded5c242d320b39965a86fb27b8'


class BrowserTransport:
    def __init__(self, interpreters=None, profile_root=None):
        self.interpreters=interpreters or ApplicationRegistry((Application(
            'browser_runtime','FRIDAY Browser runtime',(),
            tuple(Path('/usr/bin')/name for name in ('python3.14','python3.13','python3.12')),''),))
        self.child=None;self.channel=None;self.sequence=0;self.current=None
        self.profile_root=Path(profile_root) if profile_root is not None else Path(__file__).parents[2]/'data/browser-profiles'
        self.profile_fd=None
        self.events=deque(maxlen=16);self.pending_command=None;self.broken=False;self.exit_code=None

    def _event(self,name): self.events.append(name)

    def diagnostics(self):
        return {'process_state':'absent' if self.child is None else 'exited' if self.child.poll() is not None else 'running_health_unverified' if self.broken or self.pending_command else 'running',
                'exit_code':self.exit_code,'events':list(self.events)}

    def failed(self):
        self._event('operation_unconfirmed')
        if self.child is not None and self.child.poll() is not None:
            self.exit_code=self.child.poll();self._event('worker_exited');self.close()

    def _private_profile(self):
        with directory_descriptor(self.profile_root,create=True) as root:
            info=os.fstat(root)
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
                raise ValueError('Browser profile root is not private.')
            name='gtk-'+uuid4().hex;os.mkdir(name,0o700,dir_fd=root)
            return os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root)

    @contextmanager
    def reviewed_launch(self):
        with self.interpreters.executable('browser_runtime') as binary:
            if self.interpreters.production:
                # Isolated system imports must not fall through to a writable
                # /usr/local site directory or untrusted GTK binding entrypoint.
                for dependency in (Path('/usr/lib/python3/dist-packages'),
                                   Path('/usr/lib/python3/dist-packages/gi/__init__.py'),
                                   Path('/usr/lib/x86_64-linux-gnu/girepository-1.0/Gtk-4.0.typelib')):
                    self.interpreters._trusted_path(dependency)
                local_site=Path('/usr/local/lib')/binary[1].name/'dist-packages'
                if local_site.exists(): self.interpreters._trusted_path(local_site)
            worker=Path(__file__).with_name('browser_worker.py')
            with directory_descriptor(worker.parent) as parent:
                fd=os.open(worker.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                try:
                    info=os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0,os.getuid()} or info.st_mode & 0o022 or info.st_size>32768:
                        raise ValueError('Untrusted browser source.')
                    source=os.read(fd,32769)
                    if hashlib.sha256(source).hexdigest()!=WORKER_SHA256: raise ValueError('Browser source changed.')
                    yield binary,source.decode('utf-8')
                finally: os.close(fd)

    def start(self, prepared, environment):
        if self.child is not None: raise ValueError('Browser process already exists.')
        binary,source=prepared
        with self.interpreters.executable('browser_runtime') as current:
            if current[1]!=binary[1] or current[3]!=binary[3]: raise ValueError('Interpreter changed.')
        held=os.fstat(binary[2])
        if (held.st_dev,held.st_ino,held.st_size,held.st_mtime_ns)!=binary[3]: raise ValueError('Interpreter changed.')
        parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        parent.settimeout(3)
        try:
            self.profile_fd=self._private_profile()
            private=f'/proc/self/fd/{self.profile_fd}'
            environment={**environment,'HOME':private,'XDG_CONFIG_HOME':private,'XDG_DATA_HOME':private,
                         'XDG_CACHE_HOME':private,'GIO_USE_VFS':'local','GSETTINGS_BACKEND':'memory','GTK_THEME':'Adwaita'}
            self.child=subprocess.Popen([str(binary[1]),'-I','-B','-c',source,str(child.fileno())],
                executable=f'/proc/self/fd/{binary[2]}',pass_fds=(binary[2],child.fileno(),self.profile_fd),
                close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                cwd='/',env=environment,start_new_session=True)
            self.channel=parent;self.sequence=0;self.pending_command=None;self.broken=False;self.exit_code=None
            if self.child.stderr is not None: os.set_blocking(self.child.stderr.fileno(),False)
            self._event('worker_started')
        except BaseException:
            parent.close()
            if self.profile_fd is not None: os.close(self.profile_fd);self.profile_fd=None
            raise
        finally: child.close()

    def request(self, op, **fields):
        if self.child is None or self.child.poll() is not None: raise OSError('Managed browser closed.')
        if self.broken or self.pending_command is not None: raise BrowserHealthUnavailable('Browser channel is not synchronized.')
        self.sequence+=1
        command={'id':self.sequence,'op':op,**fields}
        from friday.desktop.browser_worker import validate_command
        validate_command(command)
        packet=json.dumps(command,separators=(',',':')).encode()
        if len(packet)>MAX_PACKET: raise ValueError('Oversized browser request.')
        self.pending_command=command
        try: self.channel.send(packet)
        except OSError:
            self.broken=True;self._event('ipc_send_failed');raise
        return self._receive_response(command)

    def _receive_response(self,command):
        op=command['op']
        try: response_bytes=self.channel.recv(MAX_PACKET+1)
        except TimeoutError:
            self._event('ipc_timeout');raise BrowserHealthUnavailable('Browser response timed out.') from None
        except OSError:
            self.broken=True;self._event('ipc_receive_failed');raise
        if not response_bytes or len(response_bytes)>MAX_PACKET:
            self.broken=True;self._event('ipc_eof_or_oversize');raise ValueError('Invalid response size.')
        try: response=json.loads(response_bytes)
        except (ValueError,RecursionError):
            self.broken=True;self._event('malformed_response');raise ValueError('Invalid browser response.') from None
        expected_location=command.get('location',self.current)
        if (type(response) is not dict or set(response)!={'id','op','window','location','mapped'} or
                type(response['id']) is not int or response['id']!=command['id'] or response['op']!=op or
                response['window']!='managed' or type(response['mapped']) is not bool or (op!='ping' and not response['mapped']) or
                response['location']!=expected_location):
            self.broken=True;self._event('invalid_ack');raise ValueError('Unverified browser response.')
        self.pending_command=None
        self.current=expected_location
        self._event('health_ack' if op=='ping' else 'operation_ack')
        return response

    def alive(self):
        if self.child is None: return False
        if self.child.poll() is not None:
            self.exit_code=self.child.poll();self._event('worker_exited');self.close();return False
        try:
            self._drain_diagnostics()
            if self.broken: raise BrowserHealthUnavailable('Browser channel failed.')
            if self.pending_command is not None: self._receive_response(self.pending_command)
            self.request('ping');return True
        except (OSError,ValueError,TypeError,UnicodeError):
            self._event('health_unconfirmed');self._drain_diagnostics()
            if self.child.poll() is not None:
                self.exit_code=self.child.poll();self._event('worker_exited');self.close();return False
            raise BrowserHealthUnavailable('Browser process has not exited; health unconfirmed. Close the managed window manually before reopening.') from None

    def _drain_diagnostics(self):
        if self.child is None or self.child.stderr is None: return
        try: raw=os.read(self.child.stderr.fileno(),4096)
        except (OSError,ValueError): return
        allowed={'label_mismatch','ipc_send_failed','ipc_receive_failed','protocol_rejected','startup_or_event_loop_failed'}
        for line in raw.splitlines():
            if line.startswith(b'FRIDAY_BROWSER_DIAGNOSTIC:'):
                code=line[26:].decode('ascii',errors='ignore')
                if code in allowed: self._event('worker_'+code)

    def close(self):
        if self.channel is not None: self.channel.close();self.channel=None
        if self.child is not None:
            self._drain_diagnostics()
            # Only our isolated renderer, never Nautilus or another user window.
            if self.child.poll() is None: self.child.terminate()
            try: self.child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.child.kill();self.child.wait(timeout=1)
            if self.child.stderr is not None: self.child.stderr.close()
            self.child=None
        self.pending_command=None;self.broken=False
        self.current=None
        if self.profile_fd is not None: os.close(self.profile_fd);self.profile_fd=None


class ManagedBrowser:
    def __init__(self, transport=None, profile_root=None):
        self.transport=transport or BrowserTransport(profile_root=profile_root)
        self.history=[];self.cursor=-1

    @property
    def active(self): return bool(self.history)

    def history_target(self, direction):
        position=self.cursor+(-1 if direction=='back' else 1)
        if direction not in {'back','forward'} or not 0<=position<len(self.history):
            raise ValueError('No browser history in that direction.')
        return dict(self.history[position]),position

    def commit(self, target, position=None):
        if position is not None: self.cursor=position;return
        if self.cursor>=0 and self.history[self.cursor]==target: return
        self.history=self.history[:self.cursor+1]+[dict(target)]
        self.history=self.history[-MAX_HISTORY:];self.cursor=len(self.history)-1

    def close(self):
        self.transport.close();self.history.clear();self.cursor=-1
