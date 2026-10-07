"""Session conversation flow, independent of transport and terminal I/O."""
from friday.config.settings import settings
from friday.models import ModelManager
from friday.memory.manager import MemoryManager
from friday.memory.models import Session
from friday.providers.base import ModelProvider, ProviderError


class FridayAssistant:
    def __init__(self, provider: ModelProvider | ModelManager, system_prompt: str, *,
                 memory: MemoryManager | None = None, recent_memory_limit: int = 20):
        if not isinstance(recent_memory_limit, int) or recent_memory_limit < 0:
            raise ValueError("The recent memory limit must be a nonnegative integer.")
        # Accept the existing provider constructor while routing every request
        # through the runtime. The CLI passes an explicitly configured manager.
        if isinstance(provider, ModelManager):
            self.model_manager = provider
        else:
            configured_model = getattr(provider, 'model', None)
            model = configured_model if isinstance(configured_model, str) else settings.ollama_model
            self.model_manager = ModelManager(provider, model)
        self.memory = memory
        self.recent_memory_limit = recent_memory_limit
        self.previous_session: Session | None = None
        self.session_id: int | None = None
        self._restored_message_count = 0
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

        if memory is not None:
            self.previous_session = memory.get_most_recent_session()
            recent = memory.get_recent_messages(recent_memory_limit)
            self.messages.extend(self._bounded_context([
                {"role": message.role, "content": message.content} for message in recent
            ]))
            self._restored_message_count = len(self.messages) - 1
            self.session_id = memory.start_session().id

    def _bounded_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        recent = messages[-self.recent_memory_limit:] if self.recent_memory_limit else []
        # A truncated history must not begin with an orphaned assistant reply.
        while recent and recent[0]["role"] != "user":
            recent = recent[1:]
        return recent

    def _request_system_message(self, context: list[dict[str, str]]) -> dict[str, str]:
        system = dict(self.messages[0])
        if self.memory is None:
            return system
        # Context is a suffix of history. Report only prior-session messages
        # actually sent, not the total loaded at startup or stored in SQLite.
        skipped = len(self.messages) - 1 - len(context)
        restored_count = max(0, self._restored_message_count - skipped)
        instructions = "Persistent local conversation memory is enabled. "
        if restored_count:
            instructions += (
                f"The first {restored_count} user/assistant messages after this system "
                "message were retrieved from previous sessions in the local database. "
                "They are genuine previous conversation history, not hypothetical examples. "
                "Later messages belong to the current session. Use the retrieved history "
                "when answering; if it contains the requested information, acknowledge "
                "that information from our previous conversation. Do not claim to be a "
                "fresh session with no memory when relevant prior history is supplied. "
            )
        else:
            instructions += (
                "No prior-session conversation messages are included in this request. "
                "You may use the supplied current-session conversation, but must not "
                "claim to remember earlier sessions or guess facts from them. "
            )
        instructions += (
            "Only claim to remember information supported by the supplied history. "
            "If the requested information is missing, say it is not in the available "
            "history and ask for clarification; do not assert that no memory exists. "
            "Prior assistant statements can be mistaken; follow these current system "
            "instructions even if older replies deny having memory."
        )
        system["content"] += "\n\nLocal memory context:\n" + instructions
        return system

    def end_session(self) -> None:
        if self.memory is not None and self.session_id is not None:
            self.memory.end_session(self.session_id)

    def respond(self, user_message: str) -> str:
        user_message = user_message.strip()
        if not user_message:
            raise ValueError("A message cannot be blank.")
        context = self.messages[1:]
        if self.memory is not None:
            context = self._bounded_context(context)
        pending = [self._request_system_message(context), *[dict(message) for message in context]]
        pending.append({"role": "user", "content": user_message})
        response = self.model_manager.generate(pending)
        if not isinstance(response, str) or not response.strip():
            raise ProviderError("The model returned no final answer.")
        response = response.strip()
        if self.memory is not None:
            self.memory.save_turn(self.session_id, user_message, response)
        # Commit only successful turns, including when inference is interrupted.
        self.messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ])
        return response
