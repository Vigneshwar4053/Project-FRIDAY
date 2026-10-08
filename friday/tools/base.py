"""Trusted typed tool interface; application dispatch uses ToolManager."""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from friday.tools.models import JSONValue, ToolSpec


class Tool(ABC):
    def __init__(self, spec: ToolSpec):
        if not isinstance(spec, ToolSpec):
            raise ValueError('Tools require declared metadata.')
        self._spec = spec

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    @abstractmethod
    def execute(self, arguments: Mapping[str, JSONValue]) -> JSONValue:
        """Return JSON-compatible data; ToolManager owns permissions and results.

        Implementations are trusted Python code. Application invocation must
        go through ToolManager, never call this method directly.
        """
