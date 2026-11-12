"""Reviewed Nmap discovery adapter; never accepts model-generated commands."""
from dataclasses import dataclass
import ipaddress
import re
import shutil
import subprocess
from threading import Event
import tempfile
import time

SPECIALIST = 'dr-ry/foundation-sec-8b-instruct-chat-GGUF:latest'


def validate_target(value):
    if type(value) is not str or len(value) > 253 or value != value.strip():
        raise ValueError('Enter one IP, small CIDR or hostname.')
    try:
        network = ipaddress.ip_network(value, strict=True)
        if network.num_addresses > 256:
            raise ValueError('Discovery is limited to at most 256 addresses.')
        if network.is_multicast or network.is_unspecified:
            raise ValueError('Multicast and unspecified targets are unsupported.')
        return str(network) if '/' in value else str(network.network_address)
    except ValueError:
        if '/' in value or ':' in value or re.fullmatch(r'[0-9.]+', value):
            raise ValueError('Invalid or oversized IP scope.') from None
    if not re.fullmatch(r'(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', value):
        raise ValueError('Invalid hostname.')
    return value.lower()

@dataclass(frozen=True)
class ScanScope:
    target: str
    purpose: str
    arguments: tuple


def discovery_arguments(target):
    """Shared reviewed flags for the original adapter and Operation Engine."""
    target = validate_target(target)
    return ('-sn', '-n', '--unprivileged', '--max-retries', '1', '--host-timeout', '5s') + (('-6',) if ':' in target else ()) + (target,)

class Nmap:
    def __init__(self):
        self.cancelled = Event()
        self.pending = None
        self.last_status = 'Never executed; installation only inspected'

    def inventory(self):
        installed = bool(shutil.which('nmap'))
        bounded = bool(shutil.which('prlimit'))
        return dict(name='Nmap', purpose='Bounded host discovery; educational command explanations in chat',
                    installed=installed, permission='Exact scope, purpose and owner authorization every time',
                    actions='Unprivileged host discovery (-sn); no port/service/exploit scans',
                    verification=self.last_status, available=installed and bounded)

    def prepare(self, target, purpose):
        self.pending = None
        self.cancelled.clear()
        target = validate_target(target)
        if not purpose.strip() or len(purpose) > 512:
            raise ValueError('Provide a short assessment purpose.')
        binary, limiter = shutil.which('nmap'), shutil.which('prlimit')
        if not binary or not limiter:
            raise ValueError('Nmap and util-linux prlimit are required. Installation needs owner approval.')
        args = [limiter, '--cpu=15', '--as=536870912', '--fsize=1048576', '--', binary, *discovery_arguments(target)]
        self.pending = ScanScope(target, purpose.strip(), tuple(args))
        self.deadline = time.monotonic()+120
        return self.pending

    def execute(self, scope, *, authorized=False, confirmed=False):
        pending, self.pending = self.pending, None
        if pending is None or scope is not pending or not authorized or not confirmed or time.monotonic() > self.deadline:
            raise PermissionError('Explicit current scope approval and target authorization required.')
        validate_target(scope.target)
        self.last_status = 'Running authorized discovery'
        with tempfile.TemporaryFile() as output:
            child = subprocess.Popen(list(scope.arguments), shell=False, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic()+30
                while child.poll() is None:
                    if self.cancelled.wait(.1) or time.monotonic() > deadline:
                        self.last_status = 'Cancelled or timed out'
                        child.terminate()
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            child.kill()
                        break
                child.wait(timeout=2)
                if self.last_status == 'Running authorized discovery':
                    self.last_status = 'Discovery completed' if child.returncode == 0 else 'Discovery failed'
                output.seek(0)
                return self.last_status+'\n'+output.read(65536).decode(errors='replace')
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()
