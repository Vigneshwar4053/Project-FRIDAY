"""Owner-registered Firefox Snap URL handoffs, without a page-load claim.

This adapter is separate from ReviewedSnap.arguments and the verified-window
browser controller. No AT-SPI, browser content, alternate browser or retry.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import subprocess
from threading import Lock
from types import MappingProxyType

from friday.desktop.accessibility import Deadline, DesktopFailure
from friday.desktop.browser_execution import BrowserTarget
from friday.desktop.handoffs import HandoffOperation
from friday.desktop.snap import ReviewedSnap
from friday.security.owner import OwnerAuthenticationError, OwnerRequest, SensitiveOperation
from friday.tools.access import FolderDecision
from friday.tools.grants import directory_descriptor
from friday.desktop.websites import WEBSITES, approved_url

YOUTUBE_URL = WEBSITES['youtube']
ACCEPTED_MESSAGE = 'Firefox navigation request accepted; page load not independently verified.'
LAUNCHER = Path('/usr/bin/snap')
ARGUMENT_PREFIX = ('run', 'firefox', '--new-window')
# Installed package code reviewed for this checkpoint. Updates fail closed until
# separately reviewed; never parse package Exec text into commands.
CHAIN_HASHES = MappingProxyType({
    ('firefox', 'meta/snap.yaml'): '754c3a40bd457ab2b3abe35f42a6497bc1503caef96a15b95c1632f20a71de5d',
    ('firefox', 'firefox.launcher'): 'f4cacc80e2c7d4341c51a7f699771d281e0036076699ec67c2287058ea733b22',
    ('firefox', 'snap/command-chain/desktop-launch'): 'bdf7e2223ca5b994d6c099382e76c64e3fd1d0eabb5d2e42fe2b6e771d550f9f',
    ('firefox', 'snap/command-chain/gpu-2404-wrapper'): '678e76eb1229462e28310b97817784d9ac24120b37eaf1eb2e19fa8d2aebc6d4',
    ('firefox', 'snap/command-chain/run'): '825d010dda56a302b730f5a6a999d87cf277d019c58a32640dc0d3500acbb2d6',
    ('gnome-46-2404', 'command-chain/desktop-launch'): '874c5adbd710c8f707e6b119d0a30de0efd5323f720904491ac52c746ac71bf8',
    ('mesa-2404', 'bin/gpu-2404-provider-wrapper'): 'd5f24da0f5edbb6c795ae30e2fba7c5ef8358c3bb3d5816f141867f2173fbcfc',
})


def supported(target):
    return (type(target) is BrowserTarget and target.operation is HandoffOperation.NAVIGATE
            and approved_url(target.url) and target.value == target.url)


@dataclass(frozen=True)
class UrlHandoffContext:
    binary_fd: int
    binary_identity: tuple
    snap_identity: tuple
    chain_identity: tuple
    environment: tuple


class UnavailableFirefoxUrlAdapter:
    def available(self, target):
        return False


class FirefoxSnapUrlAdapter:
    def __init__(self):
        self.snap = ReviewedSnap()

    @staticmethod
    def _environment():
        from friday.desktop.runtime import desktop_environment
        _, environment = desktop_environment()
        if environment is None or 'XDG_RUNTIME_DIR' not in environment:
            raise ValueError('Reviewed desktop session unavailable.')
        environment['SNAP_REEXEC'] = '0'
        return tuple(sorted(environment.items()))

    @staticmethod
    def _chain():
        identities = []
        for (package, relative), expected in CHAIN_HASHES.items():
            root = (Path('/snap') / package / 'current').resolve(strict=True)
            with directory_descriptor(root) as mount:
                mounted = os.fstat(mount)
                if mounted.st_uid != 0 or not os.fstatvfs(mount).f_flag & os.ST_RDONLY:
                    raise ValueError('Untrusted Snap mount.')
                path = root / relative
                with directory_descriptor(path.parent) as parent:
                    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                    try:
                        info = os.fstat(fd)
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                                info.st_dev != mounted.st_dev or info.st_size > 65536):
                            raise ValueError('Untrusted launcher chain.')
                        digest = hashlib.sha256(os.read(fd, 65537)).hexdigest()
                        if digest != expected:
                            raise ValueError('Launcher chain requires review.')
                        identities.append((str(path), info.st_dev, info.st_ino,
                                           info.st_size, info.st_mtime_ns, digest))
                    finally:
                        os.close(fd)
        return tuple(identities)

    def available(self, target):
        if not supported(target):
            return False
        try:
            with self.snap.executable('firefox') as binary:
                return binary[1] == LAUNCHER and bool(self._chain()) and bool(self._environment())
        except (OSError, ValueError, KeyError):
            return False

    def prepare(self, target, stack):
        if not supported(target):
            raise ValueError('Only exact owner-registered URL handoffs are reviewed.')
        binary = stack.enter_context(self.snap.executable('firefox'))
        if binary[1] != LAUNCHER:
            raise ValueError('Fixed Snap dispatcher required.')
        return UrlHandoffContext(binary[2], binary[3], binary[4], self._chain(), self._environment())

    def revalidate(self, context, deadline):
        deadline.check()
        if type(context) is not UrlHandoffContext:
            raise ValueError('Typed launcher context required.')
        with self.snap.executable('firefox') as current:
            if (current[1] != LAUNCHER or current[3] != context.binary_identity or
                    current[4] != context.snap_identity):
                raise ValueError('Reviewed installation changed.')
        info = os.fstat(context.binary_fd)
        if ((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != context.binary_identity or
                self._chain() != context.chain_identity or self._environment() != context.environment):
            raise ValueError('Adapter or session changed.')
        deadline.check()
        return True

    def handoff(self, context, target, deadline):
        if not supported(target):
            raise ValueError('Exact owner-registered target required.')
        self.revalidate(context, deadline)
        deadline.check()  # Cancellation prevents an unstarted handoff.
        child = subprocess.Popen([str(LAUNCHER), *ARGUMENT_PREFIX, target.url],
            executable=f'/proc/self/fd/{context.binary_fd}', pass_fds=(context.binary_fd,),
            shell=False, close_fds=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(context.environment), cwd='/', start_new_session=True)
        try:
            # A running Firefox can accept remote arguments and exit. A newly
            # launched Firefox may keep this process alive: timeout is then an
            # uncertain outcome, never a retry or page-load success.
            while True:
                deadline.check()
                try:
                    code = child.wait(timeout=min(.1, max(.001, deadline.expires - deadline.clock())))
                    break
                except subprocess.TimeoutExpired:
                    continue
            deadline.check()
            if code != 0:
                return {'status': 'url_handoff_failed'}
            self.revalidate(context, deadline)
            return {'status': 'request_accepted', 'message': ACCEPTED_MESSAGE,
                    'url': target.url, 'page_load_verified': False}
        finally:
            if child.poll() is None:
                # Stop only the invocation FRIDAY started, never an existing
                # Firefox, its process group, or a PID found by name.
                child.kill()
            child.wait(timeout=1)


class FirefoxUrlHandoff:
    def __init__(self, cancelled, clock, adapter=None):
        self.adapter = adapter if adapter is not None else FirefoxSnapUrlAdapter()
        self.cancelled = cancelled
        self.clock = clock
        self._busy = Lock()

    def available(self, target):
        return not self.cancelled.is_set() and supported(target) and self.adapter.available(target) is True

    def prepare(self, request, stack):
        if request.operation is not HandoffOperation.NAVIGATE or not approved_url(request.value):
            return {'result': {'status': 'unsupported_destination'}}
        target = BrowserTarget.from_request(request)
        if self.cancelled.is_set():
            return {'result': {'status': 'cancelled'}}
        if not self.available(target):
            return {'result': {'status': 'url_handoff_unavailable'}}
        context = self.adapter.prepare(target, stack)
        return {'url_handoff_target': target, 'url_handoff_context': context,
                'url_handoff_adapter': self.adapter, 'used': False}

    def authorize(self, lease, owner, approval, approval_type):
        target = lease['url_handoff_target']
        if not self.available(target) or self.adapter is not lease['url_handoff_adapter']:
            raise PermissionError('Reviewed URL handoff changed.')
        if owner is None:
            raise OwnerAuthenticationError('Owner authentication required.')
        owner.authenticate(OwnerRequest(SensitiveOperation.BROWSER_NAVIGATION, 'firefox', target.scope))
        if self.cancelled.is_set():
            raise PermissionError('URL handoff cancelled.')
        request = approval_type(target.operation.value, target.scope,
            'Send '+target.url+' to Firefox using the reviewed Snap launcher. '
            'Firefox may open a new window. Page load will not be independently verified.', 'execute')
        try:
            decision = approval.request(request) if approval is not None else FolderDecision.DENY
        except (Exception, KeyboardInterrupt):
            decision = FolderDecision.DENY
        if decision is not FolderDecision.ALLOW_ONCE:
            raise PermissionError('Exact URL handoff denied.')
        lease['authorized'] = (target, lease['url_handoff_context'], lease['url_handoff_adapter'])

    def execute(self, lease):
        target = lease['url_handoff_target']
        context = lease['url_handoff_context']
        adapter = lease['url_handoff_adapter']
        if lease.get('authorized') != (target, context, adapter) or lease['used']:
            raise PermissionError('Missing or consumed exact URL authorization.')
        lease['used'] = True
        if not self._busy.acquire(blocking=False):
            return {'status': 'url_handoff_failed'}
        deadline = Deadline(self.clock() + 5, self.cancelled, self.clock)
        try:
            deadline.check()
            if self.adapter is not adapter or not supported(target):
                raise ValueError('Adapter or target changed.')
            outcome = adapter.handoff(context, target, deadline)
            deadline.check()
            if (type(outcome) is not dict or outcome.get('status') != 'request_accepted' or
                    outcome.get('url') != target.url or outcome.get('page_load_verified') is not False):
                return {'status': 'url_handoff_failed'}
            # Never trust adapter error text or allow a stronger success claim.
            return {'status': 'request_accepted', 'message': ACCEPTED_MESSAGE,
                    'url': target.url, 'page_load_verified': False}
        except DesktopFailure as failure:
            return {'status': 'url_handoff_' + failure.status.value}
        except (Exception, KeyboardInterrupt):
            return {'status': 'url_handoff_failed'}
        finally:
            self._busy.release()
