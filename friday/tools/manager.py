"""Synchronous validation -> permission -> execution; errors fail closed."""
from collections.abc import Mapping
from friday.tools.models import ArgumentType, ToolRequest, ToolResult, ToolSpec, ToolStatus, _now
from friday.tools.permissions import PermissionDecision, PermissionPolicy, RiskPermissionPolicy
from friday.tools.registry import ToolRegistry


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
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy | None = None):
        self.registry = registry
        self.policy = policy if policy is not None else RiskPermissionPolicy()

    def execute(self, request: ToolRequest) -> ToolResult:
        if not isinstance(request, ToolRequest):
            raise TypeError('ToolManager requires a ToolRequest.')
        started_at = _now()

        def result(status: ToolStatus, *, data=None, error: str | None = None) -> ToolResult:
            return ToolResult(tool_name=request.tool_name, request_id=request.request_id,
                              status=status, requested_at=request.created_at,
                              started_at=started_at, finished_at=_now(), data=data, error=error)

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
            data = entry.tool.execute(request.arguments)
            return result(ToolStatus.SUCCESS, data=data)
        except Exception:
            # Neither exception messages nor traceback details become results.
            return result(ToolStatus.FAILED, error='Tool execution failed.')
        # KeyboardInterrupt/SystemExit intentionally propagate from policy or tool.
