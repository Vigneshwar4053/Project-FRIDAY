"""Session conversation flow, independent of transport and terminal I/O."""
from friday.providers.base import ModelProvider, ProviderError


class FridayAssistant:
    def __init__(self, provider: ModelProvider, system_prompt: str):
        self.provider = provider
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

    def respond(self, user_message: str) -> str:
        user_message = user_message.strip()
        if not user_message:
            raise ValueError("A message cannot be blank.")
        pending = [dict(message) for message in self.messages]
        pending.append({"role": "user", "content": user_message})
        response = self.provider.chat(pending)
        if not isinstance(response, str) or not response.strip():
            raise ProviderError("The model returned no final answer.")
        response = response.strip()
        # Commit only successful turns, including when inference is interrupted.
        self.messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ])
        return response
