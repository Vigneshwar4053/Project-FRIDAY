"""Filesystem-only approval orchestration; never interpret model/tool output."""
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import sys

from friday.tools.filesystem import OutsideRoots, regular_file
from friday.tools.grants import FolderGrant, approved_folder, directory_descriptor


class FolderDecision(StrEnum):
    ALLOW_ONCE = 'allow_once'
    ALLOW_PERSISTENT = 'allow_persistent'
    DENY = 'deny'


@dataclass(frozen=True)
class FileApproval:
    operation: str
    target: Path
    folder: FolderGrant
    identity: tuple[int, int]

    def prompt(self):
        return ('Permission required:\n'
                f'Operation: {self.operation}\n'
                f'Folder: {json.dumps(str(self.folder.folder), ensure_ascii=True)}\n'
                'Access: READ_ONLY\n'
                f'Target: {json.dumps(str(self.target), ensure_ascii=True)}\n\n'
                'Allow once: exact target and operation only.\n'
                'Always allow: this folder and descendants, read/list only.\n\n'
                '[1] Allow once\n[2] Always allow this folder\n[3] Deny')


class CLIFileApproval:
    """Only direct input during this synchronous CLI prompt can approve."""
    def request(self, approval):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return FolderDecision.DENY
        print(approval.prompt(), flush=True)
        try:
            answer = input('Permission choice: ').strip().casefold()
        except (Exception, KeyboardInterrupt):
            return FolderDecision.DENY
        return {'1': FolderDecision.ALLOW_ONCE, 'allow once': FolderDecision.ALLOW_ONCE,
                '2': FolderDecision.ALLOW_PERSISTENT,
                'always allow this folder': FolderDecision.ALLOW_PERSISTENT,
                '3': FolderDecision.DENY, 'deny': FolderDecision.DENY}.get(answer, FolderDecision.DENY)


class FilesystemAccess:
    """Trusted application component; an approval never mutates static roots."""
    def __init__(self, boundary, store, approval=None):
        self.boundary = boundary
        self.store = store
        self.approval = approval

    def _target(self, request):
        path = self.boundary.candidate(request.arguments['path'],
                                       include_persistent=True, home_aliases=True)
        folder = path if request.tool_name == 'list_directory' else path.parent
        grant = approved_folder(folder, self.boundary.sensitive)
        if request.tool_name == 'list_directory':
            identity = (grant.device, grant.inode)
        else:
            with directory_descriptor(folder) as parent:
                # Linux O_PATH inspects identity/type without read access,
                # device activation, or reading content before approval.
                fd = os.open(path.name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    metadata = regular_file(fd)
                    if metadata.st_size > self.boundary.max_file_size:
                        raise ValueError('File exceeds limit.')
                    identity = (metadata.st_dev, metadata.st_ino)
                finally:
                    os.close(fd)
        return FileApproval(request.tool_name, path, grant, identity)

    def _decision(self, target):
        if self.approval is None:
            return FolderDecision.DENY
        try:
            decision = self.approval.request(target)
        except (Exception, KeyboardInterrupt):
            return FolderDecision.DENY
        return decision if isinstance(decision, FolderDecision) else FolderDecision.DENY

    @contextmanager
    def execution(self, request):
        if request.tool_name not in {'read_file', 'list_directory'}:
            yield
            return
        with self.boundary.request_access(request.tool_name):
            try:
                self.boundary.resolve(request.arguments['path'])
            except OutsideRoots:
                target = self._target(request)
                decision = self._decision(target)
                if decision is FolderDecision.DENY:
                    raise ValueError('Filesystem authorization denied.')
                if decision is FolderDecision.ALLOW_PERSISTENT:
                    self.store.add(target.folder)
                # Even permanent approval binds this execution to the prompted
                # target and inode. The grant disappears on every exit path.
                with self.boundary.request_access(request.tool_name, target):
                    yield
                return
            yield

    def command(self, action, path=None):
        """Deterministic CLI commands; results never enter conversation history."""
        try:
            grants = self.store.load()
            if action == 'show':
                lines = ['Authorized folders (READ_ONLY):',
                         *[json.dumps(str(root), ensure_ascii=True) + ' [configured; not revocable here]'
                           for root in self.boundary.allowed_roots],
                         *[json.dumps(str(g.folder), ensure_ascii=True) + ' [persistent]'
                           for g in grants]]
                return '\n'.join(lines)
            folder = self.boundary.candidate(path, include_persistent=True, home_aliases=True)
            if folder in self.boundary.allowed_roots:
                return 'Folder is configured access; change Settings to remove it. Built-in project access is preserved.'
            if action == 'revoke':
                if self.store.revoke(folder):
                    return 'Revoked READ_ONLY access to ' + json.dumps(str(folder), ensure_ascii=True)
                return 'No explicit persistent grant exists for that folder.'
            if action == 'authorize':
                grant = approved_folder(folder, self.boundary.sensitive)
                target = FileApproval('list_directory', folder, grant, (grant.device, grant.inode))
                if self._decision(target) is FolderDecision.ALLOW_PERSISTENT:
                    self.store.add(grant)
                    return 'Saved READ_ONLY access to ' + json.dumps(str(folder), ensure_ascii=True)
                return 'No persistent authorization was saved.'
            return 'Unsupported filesystem permission command.'
        except (OSError, ValueError, UnicodeError, RuntimeError):
            return 'Filesystem permission command could not be completed safely.'
