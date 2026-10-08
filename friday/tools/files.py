"""Bounded file tools; register explicitly and invoke only via ToolManager."""
from datetime import datetime, timezone
import json
import os
import stat

from friday.tools.base import Tool
from friday.tools.filesystem import FileSystemPolicy, regular_file
from friday.tools.models import ArgumentSpec, ArgumentType, RiskLevel, ToolSpec


def _type(mode):
    if stat.S_ISREG(mode):
        return 'file'
    if stat.S_ISDIR(mode):
        return 'directory'
    if stat.S_ISLNK(mode):
        return 'symlink'
    return 'other'


class _FileTool(Tool):
    def __init__(self, policy, name, description, risk=RiskLevel.READ_ONLY, extra=None):
        if not isinstance(policy, FileSystemPolicy):
            raise ValueError('An explicit filesystem policy is required.')
        schema = {'path': ArgumentSpec(ArgumentType.STRING)}
        schema.update(extra or {})
        super().__init__(ToolSpec(name, description, schema, risk))
        self.policy = policy


class ListDirectoryTool(_FileTool):
    def __init__(self, policy):
        super().__init__(policy, 'list_directory', 'List names and types in an allowed directory.')

    def execute(self, arguments):
        with self.policy.open(arguments['path'], os.O_RDONLY | os.O_DIRECTORY) as (fd, path):
            with os.scandir(fd) as entries:
                data = []
                truncated = False
                for index, entry in enumerate(entries):
                    if index == self.policy.max_directory_entries:
                        truncated = True
                        break
                    if self.policy.sensitive.excluded(os.path.join(path, entry.name)):
                        continue
                    # JSON quoting escapes controls, surrogates and line breaks.
                    name = json.dumps(entry.name, ensure_ascii=True)[1:-1]
                    data.append({'name': name,
                                 'type': _type(entry.stat(follow_symlinks=False).st_mode)})
                data.sort(key=lambda entry: entry['name'])
        return {'path': path, 'entries': data, 'truncated': truncated,
                'limit': self.policy.max_directory_entries}


class ReadFileTool(_FileTool):
    def __init__(self, policy):
        super().__init__(policy, 'read_file', 'Read a bounded regular UTF-8 text file.')

    def execute(self, arguments):
        with self.policy.open(arguments['path'], os.O_RDONLY) as (fd, path):
            if regular_file(fd).st_size > self.policy.max_file_size:
                raise ValueError('File exceeds the size limit.')
            chunks = []
            remaining = self.policy.max_file_size + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b''.join(chunks)
            if len(content) > self.policy.max_file_size or b'\x00' in content:
                raise ValueError('Oversized or non-text file.')
            if self.policy.sensitive.excluded_content(content):
                raise ValueError('Content is excluded by privacy policy.')
            text = content.decode('utf-8', errors='strict')
        return {'path': path, 'content': text, 'size': len(content), 'encoding': 'utf-8'}


class FileInfoTool(_FileTool):
    def __init__(self, policy):
        super().__init__(policy, 'file_info', 'Return type, size and UTC modification time.')

    def execute(self, arguments):
        with self.policy.parent(arguments['path']) as (parent, name, path):
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError('Symlinks are not allowed.')
        return {'path': path, 'type': _type(metadata.st_mode), 'size': metadata.st_size,
                'modified_at': datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat()}


class WriteFileTool(_FileTool):
    def __init__(self, policy):
        super().__init__(policy, 'write_file', 'Write UTF-8 text; overwrite requires explicit intent.',
                         RiskLevel.WRITE, {'content': ArgumentSpec(ArgumentType.STRING),
                                           'overwrite': ArgumentSpec(ArgumentType.BOOLEAN, required=False)})

    def execute(self, arguments):
        content = arguments['content'].encode('utf-8')
        if len(content) > self.policy.max_file_size or b'\x00' in content:
            raise ValueError('Oversized or non-text content.')
        overwrite = arguments.get('overwrite', False)
        flags = os.O_WRONLY | os.O_CREAT
        if not overwrite:
            flags |= os.O_EXCL
        with self.policy.open(arguments['path'], flags) as (fd, path):
            regular_file(fd)  # Do not truncate special files or shared hard links.
            os.ftruncate(fd, 0)
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError('Write made no progress.')
                view = view[written:]
        return {'path': path, 'bytes_written': len(content), 'overwrite': overwrite}


def register_file_tools(registry, policy):
    """Explicit composition; does not change permissions or enable chat tools."""
    for tool_class in (ListDirectoryTool, ReadFileTool, FileInfoTool, WriteFileTool):
        registry.register(tool_class(policy))
