"""Owner-authorized app-only Snap adapter. Native trust policy stays separate.

The owner explicitly accepts shell startup files sourced by these two installed
packages. This is NOT a general trusted-executable or target-argument exception.
"""
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import stat

from friday.desktop.registry import Application, ApplicationRegistry
from friday.tools.grants import directory_descriptor

PACKAGES = {
    'vscode': ('code', 'Ht0aUHi7ofh9Fbwh6m7jUN2pAy6kzBiu',
               'qXCsqdX95tRyVlJUKTKESXEAuNRPfJob', 'vscode', 'classic'),
    'firefox': ('firefox', '3wdHCAVyZEmYsCMFDE9qt92UV8rC8Wdk',
                'OgeoZuqQpVvSr9eGKJzNCrFGSaKXpkey', 'mozilla', 'strict'),
}
RUNTIMES={
    'core20':('DLqre5XGLbDqg9jPtiAhRRjDuPVa5X1q','base'),
    'core24':('dwTAh7MZZ01zyriOZErqd1JynQLiOGvM','base'),
    'gnome-46-2404':('ew7OxpbRTxfK7ImpIygRR85lkxvU7Pzt','app'),
    'mesa-2404':('HyhSEBPv3vHsW6uOHkQR384NgI7S6zpj','app'),
    'gtk-common-themes':('jZLfBRzf1cYlYysIjD2bwSzNtngY0qit','app'),
}
FIREFOX_CONTENT={
    'gnome-46-2404':('gnome-46-2404','gnome-46-2404'),
    'gpu-2404':('mesa-2404','gpu-2404'),
    'gtk-3-themes':('gtk-common-themes','gtk-3-themes'),
    'icon-themes':('gtk-common-themes','icon-themes'),
    'sound-themes':('gtk-common-themes','sound-themes'),
}


def administrator_path(path):
    """Host paths: no symlinks, root-owned, no group/world writes."""
    path = Path(path)
    with directory_descriptor(path.parent):
        for component in (Path('/'), *reversed(path.parents[:-1]), path):
            info = component.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                raise ValueError('Untrusted Snap installation component.')
    return path.lstat()


class SnapConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/run/snapd.socket')


class ReviewedSnap:
    def __init__(self):
        dispatcher = Application('snap', 'Snap dispatcher', (),
                                 (Path('/usr/bin/snap'),), '')
        self.dispatcher = ApplicationRegistry((dispatcher,))

    def _get(self, endpoint_path):
        # The daemon socket is intentionally writable; its administrator-owned
        # pathname and parents establish endpoint identity, not its mode bits.
        endpoint = Path('/run/snapd.socket')
        with directory_descriptor(endpoint.parent):
            parent = endpoint.parent.lstat(); info = endpoint.lstat()
            if parent.st_uid != 0 or parent.st_mode & 0o022 or info.st_uid != 0 or not stat.S_ISSOCK(info.st_mode):
                raise ValueError('Untrusted snapd endpoint.')
        connection = SnapConnection('localhost', timeout=3)
        try:
            connection.request('GET', endpoint_path)
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != 200 or len(body) > 65536:
                raise ValueError('Snap metadata unavailable or oversized.')
            return json.loads(body)['result']
        finally:
            connection.close()

    def metadata(self, package):
        return self._get('/v2/snaps/'+package)

    def review(self, application_id):
        if application_id not in PACKAGES:
            raise ValueError('Snap application is not approved.')
        package, snap_id, publisher_id, publisher, confinement = PACKAGES[application_id]
        application=self.package_review(package,snap_id,publisher_id,publisher,confinement,'app',desktop=True)
        providers=('core20',) if application_id=='vscode' else ('core24','gnome-46-2404','mesa-2404','gtk-common-themes')
        dependencies=tuple(self.package_review(name,RUNTIMES[name][0],'canonical','canonical','strict',RUNTIMES[name][1]) for name in providers)
        connections=()
        if application_id=='firefox':
            data=self._get('/v2/connections?snap=firefox')
            selected={}
            for connection in data['established']:
                if connection['plug']['snap']=='firefox' and connection['interface']=='content':
                    plug=connection['plug']['plug'];slot=connection['slot']
                    if plug in selected: raise ValueError('Duplicate Firefox runtime connection.')
                    selected[plug]=(slot['snap'],slot['slot'])
            if selected!=FIREFOX_CONTENT: raise ValueError('Firefox runtime provider registration changed.')
            connections=tuple(sorted(selected.items()))
        return application,dependencies,connections

    def package_review(self,package,snap_id,publisher_id,publisher,confinement,package_type,*,desktop=False):
        metadata = self.metadata(package)
        expected = {'name':package, 'id':snap_id, 'status':'active', 'type':'app',
                    'confinement':confinement}
        expected['type']=package_type
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError('Snap package identity mismatch.')
        author = metadata.get('publisher', {})
        if author.get('id') != publisher_id or author.get('username') != publisher or author.get('validation') != 'verified':
            raise ValueError('Snap publisher identity mismatch.')
        if metadata.get('devmode') or metadata.get('ignore-validation'):
            raise ValueError('Unreviewed Snap installation mode.')
        revision = metadata.get('revision')
        if type(revision) is not str or not revision.isascii() or not revision.isdecimal() or len(revision) > 12:
            raise ValueError('Unreviewed Snap revision.')
        image = Path('/var/lib/snapd/snaps') / (package + '_' + revision + '.snap')
        if metadata.get('mounted-from') != str(image):
            raise ValueError('Snap image registration mismatch.')
        image_info = administrator_path(image)
        if not stat.S_ISREG(image_info.st_mode):
            raise ValueError('Snap image is not a regular file.')
        administrator_path(Path('/snap') / package)
        current = Path('/snap') / package / 'current'
        info = current.lstat()
        if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or os.readlink(current) != revision:
            raise ValueError('Snap current revision changed.')
        mount = current.parent / revision
        # Immutable squashfs can have package-authored group-write mode bits.
        # Never apply that allowance to mutable host paths.
        hashes = []
        with directory_descriptor(mount) as fd:
            mounted = os.fstat(fd)
            if mounted.st_uid != 0 or not os.fstatvfs(fd).f_flag & os.ST_RDONLY:
                raise ValueError('Snap package mount is mutable or untrusted.')
            metadata_paths=('meta/snap.yaml','meta/gui/'+package+'.desktop') if desktop else ('meta/snap.yaml',)
            for relative in metadata_paths:
                with directory_descriptor(mount / Path(relative).parent) as parent:
                    file_fd = os.open(Path(relative).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                    try:
                        file_info = os.fstat(file_fd)
                        if not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != 0 or file_info.st_dev != mounted.st_dev or file_info.st_size > 65536:
                            raise ValueError('Untrusted Snap registration metadata.')
                        contents = os.read(file_fd, 65537)
                        hashes.append(hashlib.sha256(contents).hexdigest())
                    finally:
                        os.close(file_fd)
        # Registration is reviewed as package data, never parsed as executable
        # shell/desktop Exec text. Dispatch accepts only the fixed package name.
        for helper in ('snap-confine', 'snap-exec'):
            administrator_path(Path('/usr/lib/snapd') / helper)
        selected = {key:metadata.get(key) for key in (*expected, 'revision', 'version', 'mounted-from', 'publisher', 'devmode', 'ignore-validation')}
        return (json.dumps(selected, sort_keys=True), image_info.st_dev, image_info.st_ino,
                image_info.st_size, image_info.st_mtime_ns, mounted.st_dev, mounted.st_ino, *hashes)

    @contextmanager
    def executable(self, application_id):
        fingerprint = self.review(application_id)
        with self.dispatcher.executable('snap') as executable:
            yield (*executable, fingerprint)

    @staticmethod
    def arguments(application_id, *, path=None, url=None):
        if application_id not in PACKAGES or path is not None or url is not None:
            raise ValueError('Owner Snap exception permits app-only launches; target arguments are unsupported.')
        return ['run', PACKAGES[application_id][0]]
