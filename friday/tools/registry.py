"""Explicit per-instance registry with immutable registration metadata."""
from dataclasses import dataclass
from friday.tools.base import Tool
from friday.tools.models import ToolSpec


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    tool: Tool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool) or not isinstance(tool.spec, ToolSpec):
            raise ValueError('Only declared Tool instances can be registered.')
        spec = tool.spec
        if spec.name in self._tools:
            raise ValueError('A tool with this name is already registered.')
        # Dispatch and policy use this snapshot even if the implementation
        # later replaces its own metadata. Never expose the backing dictionary.
        self._tools[spec.name] = RegisteredTool(spec, tool)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_tools(self) -> tuple[ToolSpec, ...]:
        """Registration order, immutable metadata only."""
        return tuple(entry.spec for entry in self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
