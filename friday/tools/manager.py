"""Synchronous validation -> permission -> execution; errors fail closed."""
from collections.abc import Mapping
from contextlib import nullcontext
from friday.tools.models import ArgumentType, ToolRequest, ToolResult, ToolSpec, ToolStatus, ToolErrorCategory, _now
from friday.tools.permissions import PermissionDecision, PermissionPolicy, RiskPermissionPolicy
from friday.tools.registry import ToolRegistry
from friday.tools.access import FilesystemAuthorizationDenied
from friday.tools.files import UnsupportedFileContent


def _valid_arguments(spec: ToolSpec, arguments: Mapping) -> bool:
    if any(name not in spec.arguments for name in arguments):
        return False
    for name, declaration in spec.arguments.items():
        if name not in arguments:
            if declaration.required:
                return False
            continue
        value = arguments[name]
        expected = declaration.type
        valid = {
            ArgumentType.STRING: type(value) is str,
            ArgumentType.INTEGER: type(value) is int,
            ArgumentType.NUMBER: type(value) in (int, float),
            ArgumentType.BOOLEAN: type(value) is bool,
            ArgumentType.OBJECT: isinstance(value, Mapping),
            ArgumentType.ARRAY: type(value) is tuple,
        }[expected]
        if not valid:
            return False
    return True


class ToolManager:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy | None = None, *, filesystem_access=None):
        self.registry = registry
        self.policy = policy if policy is not None else RiskPermissionPolicy()
        self.filesystem_access = filesystem_access

    def execute(self, request: ToolRequest) -> ToolResult:
        if not isinstance(request, ToolRequest):
            raise TypeError('ToolManager requires a ToolRequest.')
        started_at = _now()

        def result(status: ToolStatus, *, data=None, error: str | None = None, error_category=None) -> ToolResult:
            return ToolResult(tool_name=request.tool_name, request_id=request.request_id,
                              status=status, requested_at=request.created_at,
                              started_at=started_at, finished_at=_now(), data=data, error=error, error_category=error_category)

        entry = self.registry.get(request.tool_name)
        if entry is None:
            return result(ToolStatus.UNKNOWN_TOOL, error='The requested tool is not registered.')
        if not _valid_arguments(entry.spec, request.arguments):
            return result(ToolStatus.INVALID_ARGUMENTS, error='Arguments do not match the tool schema.')
        try:
            decision = self.policy.evaluate(entry.spec, request)
        except Exception:
            return result(ToolStatus.FAILED, error='Tool permission evaluation failed.')
        if decision is PermissionDecision.DENY:
            return result(ToolStatus.DENIED, error='Tool execution was denied by policy.')
        if decision is PermissionDecision.REQUIRE_USER_APPROVAL:
            return result(ToolStatus.APPROVAL_REQUIRED, error='User approval is required; the tool was not executed.')
        if decision is not PermissionDecision.ALLOW:
            return result(ToolStatus.FAILED, error='Tool permission policy returned an invalid decision.')
        try:
            authorization = (self.filesystem_access.execution(request)
                             if self.filesystem_access is not None else nullcontext())
            with authorization:
                data = entry.tool.execute(request.arguments)
            return result(ToolStatus.SUCCESS, data=data)
        except UnsupportedFileContent:
            return result(ToolStatus.FAILED, error="Tool execution failed.",
                          error_category=ToolErrorCategory.UNSUPPORTED_CONTENT)
        except (FilesystemAuthorizationDenied, PermissionError):
            return result(ToolStatus.FAILED, error='Tool execution failed.',
                          error_category=ToolErrorCategory.PERMISSION_DENIED)
        except FileNotFoundError:
            return result(ToolStatus.FAILED, error='Tool execution failed.',
                          error_category=ToolErrorCategory.UNAVAILABLE_PATH)
        except NotADirectoryError:
            return result(ToolStatus.FAILED, error='Tool execution failed.',
                          error_category=ToolErrorCategory.NOT_DIRECTORY)
        except (ValueError, OSError):
            category = (ToolErrorCategory.BLOCKED_PATH if request.tool_name in
                        {'list_directory', 'read_file', 'file_info', 'write_file', 'disk_usage'} else None)
            return result(ToolStatus.FAILED, error='Tool execution failed.', error_category=category)
        except Exception:
            # Neither exception messages nor traceback details become results.
            return result(ToolStatus.FAILED, error='Tool execution failed.')
        # KeyboardInterrupt/SystemExit intentionally propagate from policy or tool.
