"""Provider-independent conversation interface."""
from abc import ABC, abstractmethod
from friday.diagnostics import safe_category


class ProviderError(RuntimeError):
    """An expected model service or response failure safe to show in the CLI."""

    def __init__(self, message, *, category='provider_failure'):
        super().__init__(message)
        self.category = safe_category(category, 'provider_failure')


class ModelProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Return final answer text or raise ProviderError; do not mutate messages."""
        raise NotImplementedError
