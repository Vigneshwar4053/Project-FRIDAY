"""Immutable JSON-compatible requests, schemas, metadata, and results."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import math
import re
from types import MappingProxyType
from typing import TypeAlias
from uuid import uuid4

JSONValue: TypeAlias = str | int | float | bool | None | list['JSONValue'] | tuple['JSONValue', ...] | Mapping[str, 'JSONValue']
_NAME = re.compile(r'[a-z][a-z0-9_]*\Z')


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _freeze(value, depth: int = 0) -> JSONValue:
    """Copy JSON data into immutable containers; reject executable/custom values."""
    if depth > 64:
        raise ValueError('Tool data is cyclic or exceeds the maximum nesting depth.')
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if not all(type(key) is str for key in value):
            raise ValueError('Tool object keys must be strings.')
        return MappingProxyType({key: _freeze(item, depth + 1) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(item, depth + 1) for item in value)
    raise ValueError('Tool data must contain only finite JSON-compatible values.')


class ArgumentType(StrEnum):
    STRING = 'string'
    INTEGER = 'integer'
    NUMBER = 'number'
    BOOLEAN = 'boolean'
    OBJECT = 'object'
    ARRAY = 'array'


class RiskLevel(StrEnum):
    READ_ONLY = 'read_only'
    WRITE = 'write'
    EXECUTE = 'execute'
    PRIVILEGED = 'privileged'


@dataclass(frozen=True)
class ArgumentSpec:
    type: ArgumentType
    required: bool = True

    def __post_init__(self):
        if not isinstance(self.type, ArgumentType) or type(self.required) is not bool:
            raise ValueError('Argument declarations need an ArgumentType and boolean required flag.')


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: Mapping[str, ArgumentSpec]
    risk: RiskLevel

    def __post_init__(self):
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise ValueError('Tool names must be lowercase identifiers.')
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError('A tool needs a description.')
        if not isinstance(self.risk, RiskLevel):
            raise ValueError('A tool needs an explicit RiskLevel.')
        if not isinstance(self.arguments, Mapping):
            raise ValueError('A tool needs an argument schema mapping.')
        for name, spec in self.arguments.items():
            if not isinstance(name, str) or not _NAME.fullmatch(name) or not isinstance(spec, ArgumentSpec):
                raise ValueError('Invalid tool argument declaration.')
        object.__setattr__(self, 'arguments', MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True)
class DirectoryIdentity:
    """A trusted listing's identity hint, never an authorization grant."""
    path: str
    device: int
    inode: int

    def __post_init__(self):
        from pathlib import PurePosixPath
        if (type(self.path) is not str or not self.path.startswith('/') or
                '\x00' in self.path or '..' in PurePosixPath(self.path).parts or
                len(self.path.encode('utf-8')) > 4096 or
                any(type(value) is not int or value < 0 for value in (self.device, self.inode))):
            raise ValueError('Invalid directory identity.')


@dataclass(frozen=True)
class DirectoryGuard:
    """Request-local stale-target check; cannot expand roots or permissions."""
    target: DirectoryIdentity
    parent: DirectoryIdentity | None = None
    operation: str = "list_directory"

    def __post_init__(self):
        from pathlib import PurePosixPath
        if self.operation not in {"list_directory", "read_file"}:
            raise ValueError("Listing guards support only read/list operations.")
        if not isinstance(self.target, DirectoryIdentity):
            raise ValueError('A directory guard needs a typed target.')
        if self.parent is not None and (not isinstance(self.parent, DirectoryIdentity) or
                PurePosixPath(self.target.path).parent != PurePosixPath(self.parent.path)):
            raise ValueError('Directory guard parent must be the immediate parent.')


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: Mapping[str, JSONValue]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=_now, init=False)
    directory_guard: DirectoryGuard | None = None

    def __post_init__(self):
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            raise ValueError('A request needs a tool name.')
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError('A request needs an identifier.')
        if not isinstance(self.arguments, Mapping):
            raise ValueError('Tool arguments must be an object.')
        if self.directory_guard is not None and (not isinstance(self.directory_guard, DirectoryGuard) or
                self.tool_name != self.directory_guard.operation or
                self.arguments.get('path') != self.directory_guard.target.path):
            raise ValueError('Listing guards bind only an exact read/list request.')
        object.__setattr__(self, 'arguments', _freeze(self.arguments))


class ToolStatus(StrEnum):
    SUCCESS = 'success'
    FAILED = 'failed'
    UNKNOWN_TOOL = 'unknown_tool'
    INVALID_ARGUMENTS = 'invalid_arguments'
    DENIED = 'denied'
    APPROVAL_REQUIRED = 'approval_required'


class ToolErrorCategory(StrEnum):
    PERMISSION_DENIED = 'permission_denied'
    UNAVAILABLE_PATH = 'unavailable_path'
    NOT_DIRECTORY = 'not_directory'
    BLOCKED_PATH = 'blocked_path'
    UNSUPPORTED_CONTENT = 'unsupported_content'


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    request_id: str
    status: ToolStatus
    requested_at: datetime
    started_at: datetime
    finished_at: datetime
    data: JSONValue = None
    error: str | None = None
    error_category: ToolErrorCategory | None = None

    def __post_init__(self):
        if self.error_category is not None and (not isinstance(self.error_category, ToolErrorCategory) or
                                                self.status is ToolStatus.SUCCESS):
            raise ValueError('Only failures may contain a typed error category.')
        if not isinstance(self.status, ToolStatus):
            raise ValueError('A tool result needs a ToolStatus.')
        if self.status is ToolStatus.SUCCESS:
            if self.error is not None:
                raise ValueError('Successful results cannot contain an error.')
        elif not isinstance(self.error, str) or not self.error or self.data is not None:
            raise ValueError('Unsuccessful results need an error and no data.')
        object.__setattr__(self, 'data', _freeze(self.data))

    @property
    def success(self) -> bool:
        return self.status is ToolStatus.SUCCESS
