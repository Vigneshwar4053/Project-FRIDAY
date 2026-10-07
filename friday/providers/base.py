"""Provider-independent conversation interface."""
from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """An expected model service or response failure safe to show in the CLI."""


class ModelProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Return final answer text or raise ProviderError; do not mutate messages."""
        raise NotImplementedError
