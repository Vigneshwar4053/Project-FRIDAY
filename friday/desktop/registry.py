"""Reviewed native application identities; no PATH lookup or desktop Exec parsing."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import MappingProxyType


@dataclass(frozen=True)
class Application:
    application_id: str
    display_name: str
    aliases: tuple[str, ...]
    candidates: tuple[Path, ...]
    desktop_id: str
    risk: str = 'execute'
    launch_method: str = 'verified_native_elf'


APPLICATIONS = (
    Application('vscode','Visual Studio Code',('vs code','visual studio code','code'),
                (Path('/usr/share/code/code'),Path('/usr/lib/code/code')),'code.desktop'),
    Application('files','Ubuntu Files',('files','ubuntu files','file manager','nautilus'),
                (Path('/usr/bin/nautilus'),),'org.gnome.Nautilus.desktop'),
    Application('firefox','Firefox',('firefox',),
                (Path('/usr/lib/firefox/firefox'),Path('/usr/lib/firefox/firefox-bin'),Path('/usr/bin/firefox')),'firefox.desktop'),
)


class ApplicationRegistry:
    def __init__(self, entries=APPLICATIONS, *, trusted_root=Path('/usr'), trusted_uid=0):
        # Alternate roots/UIDs are constructor injection for isolated tests only.
        self.entries=MappingProxyType({entry.application_id:entry for entry in entries})
        if len(self.entries)!=len(entries): raise ValueError('Duplicate application identity.')
        self.root=Path(trusted_root); self.uid=trusted_uid
        self.production = self.root == Path('/usr') and self.uid == 0
        aliases={}
        for entry in entries:
            for alias in entry.aliases:
                aliases.setdefault(alias.casefold(),[]).append(entry.application_id)
        self.aliases=MappingProxyType({k:tuple(v) for k,v in aliases.items()})

    def resolve(self, alias):
        matches=self.aliases.get(alias.casefold(),())
        return matches[0] if len(matches)==1 else None

    def _trusted_path(self, path):
        if not path.is_absolute() or not path.is_relative_to(self.root):
            raise ValueError('Application is outside reviewed installation roots.')
        # All symlinks are refused, including installation-root ancestors.
        # Production trusts the root administrator, never a PATH name/wrapper.
        from friday.tools.grants import directory_descriptor
        with directory_descriptor(self.root): pass
        if self.production:
            root_info=Path('/').lstat()
            if root_info.st_uid != 0 or root_info.st_mode & 0o022:
                raise ValueError('Untrusted filesystem root ownership or writable mode.')
        walked=self.root
        metadata=walked.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid!=self.uid or metadata.st_mode & 0o022:
            raise ValueError('Installation root must be root-owned and not group/world writable.' if self.production else 'Untrusted installation directory.')
        for part in path.relative_to(self.root).parts:
            walked/=part
            metadata=walked.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError('Symlink installation components are not supported.')
            if metadata.st_uid!=self.uid or metadata.st_mode & 0o022:
                raise ValueError('Application components must have trusted ownership and no group/world write access.')
            if walked != path and not stat.S_ISDIR(metadata.st_mode):
                raise ValueError('Installation parent is not a directory.')

    @contextmanager
    def executable(self, application_id):
        entry=self.entries.get(application_id)
        if entry is None: raise ValueError('Application is not registered.')
        fd=None
        for candidate in entry.candidates:
            try:
                self._trusted_path(candidate)
                path=candidate.resolve(strict=True)
                self._trusted_path(path)
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                info=os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.uid or info.st_mode & 0o022
                        or not info.st_mode & 0o111 or os.read(fd,4)!=b'\x7fELF'):
                    raise ValueError('Trusted native executable required.')
                os.lseek(fd,0,os.SEEK_SET)
                break
            except (OSError,ValueError):
                if fd is not None: os.close(fd);fd=None
        if fd is None: raise FileNotFoundError('Approved native application unavailable.')
        try: yield entry,path,fd,(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        finally: os.close(fd)

    def availability(self, application_id):
        try:
            with self.executable(application_id): return True
        except (OSError,ValueError): return False

    def unavailable_reason(self, application_id):
        """Fixed diagnostics for reviewed identities; never probe with execution."""
        entry=self.entries.get(application_id)
        if entry is None: return 'Application identity is not registered; no launch attempted.'
        reasons=[]
        for candidate in entry.candidates:
            try:
                if not candidate.exists():
                    reasons.append('Reviewed native executable is missing.'); continue
                self._trusted_path(candidate)
                with candidate.open('rb') as stream:
                    if stream.read(4) != b'\x7fELF':
                        reasons.append('Reviewed path contains a script/wrapper, not a native ELF executable.')
                    else: reasons.append('Native executable failed execution-mode or identity verification.')
            except ValueError as error: reasons.append(str(error))
            except OSError: reasons.append('Reviewed installation metadata is unavailable.')
        reason=' '.join(dict.fromkeys(reasons))
        if self.production and application_id in {'vscode','firefox'}:
            wrapper=Path('/snap/bin') / ('code' if application_id=='vscode' else 'firefox')
            if wrapper.is_symlink() or wrapper.exists():
                reason+=' Snap launcher detected: reviewed Snap dispatch is unsupported by this backend. The installed launch chains may source user-writable startup shell files and cannot preserve its pinned executable/target handoff. No unsafe fallback was attempted.'
        return ('Approved native application is unavailable or its installation is untrusted; no launch attempted. '+reason+
                ' Owner action: provision a reviewed administrator-owned native installation; do not relax ownership checks or substitute a PATH executable.')
