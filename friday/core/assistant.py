"""Session conversation flow, independent of transport and terminal I/O."""
import re
from friday.config.settings import settings
from friday.core.navigation import NavigationManager
from friday.core.file_context import TemporaryFileContext, TEMPORARY_CONTEXT_INSTRUCTIONS
from friday.tools.intent_translator import IntentTranslator, needs_translation
from friday.tools.models import ToolRequest
from friday.tools.manager import ToolManager
from friday.tools.presenter import ToolPresenter
from friday.tools.router import MAX_ROUTED_MESSAGE_LENGTH, ToolRouter
from friday.models import ModelManager
from friday.memory.manager import MemoryManager
from friday.memory.models import Session
from friday.providers.base import ModelProvider, ProviderError


class FridayAssistant:
    def __init__(self, provider: ModelProvider | ModelManager, system_prompt: str, *,
                 memory: MemoryManager | None = None, recent_memory_limit: int = 20,
                 tool_router: ToolRouter | None = None, tool_manager: ToolManager | None = None,
                 tool_presenter: ToolPresenter | None = None):
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
        if (tool_router is None) != (tool_manager is None):
            raise ValueError("Router and tool manager must be supplied together.")
        self.tool_router = tool_router
        self.tool_manager = tool_manager
        self.tool_presenter = tool_presenter if tool_presenter is not None else ToolPresenter()
        self.intent_translator = (IntentTranslator(self.model_manager, tool_manager.registry,
                                                     locations=tool_router.locations)
                                  if tool_manager is not None else None)
        self.memory = memory
        self.recent_memory_limit = recent_memory_limit
        self.previous_session: Session | None = None
        self.session_id: int | None = None
        self._restored_message_count = 0
        self.file_context = TemporaryFileContext()
        self.navigation = NavigationManager(tool_router.project_root) if tool_router else None
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

        if memory is not None:
            self.previous_session = memory.get_most_recent_session()
            recent = memory.get_recent_messages(recent_memory_limit)
            self.messages.extend(self._bounded_context(self._private_history_filtered([
                {"role": message.role, "content": message.content} for message in recent
            ])))
            self._restored_message_count = len(self.messages) - 1
            self.session_id = memory.start_session().id

    def _private_history_filtered(self, messages):
        """Exclude legacy filesystem turns from restored context; leave SQLite intact."""
        filtered = []
        index = 0
        private_pending = False
        while index < len(messages):
            message = messages[index]
            if message['role'] == 'user':
                route = self.tool_router.route(message['content']) if self.tool_router else None
                following = messages[index + 1] if index + 1 < len(messages) else None
                private = (route is not None and (route.permission_command is not None or
                           route.message is not None or
                           route.tool_name in {'read_file', 'list_directory'}))
                private = private or (following is not None and following['role'] == 'assistant' and
                    following['content'].startswith(('[Tool: read_file]', '[Tool: list_directory]',
                                                     '[Temporary file context; not saved]')))
                private = private or (following is not None and following['role'] == 'assistant' and
                    following['content'].startswith('[Tool:') and
                    following['content'].split('\n', 1)[-1].startswith(
                        ('DENIED:', 'APPROVAL_REQUIRED:', 'FAILED:', 'INVALID_ARGUMENTS:', 'UNKNOWN_TOOL:')))
                private = private or (private_pending and TemporaryFileContext.is_followup(message['content']))
                private_pending = private
                if private:
                    index += 2 if following is not None and following['role'] == 'assistant' else 1
                    continue
            if not (message['role'] == 'assistant' and message['content'].startswith(
                    ('[Tool: read_file]', '[Tool: list_directory]', '[Temporary file context; not saved]'))):
                filtered.append(message)
            index += 1
        return filtered

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
        try:
            if self.memory is not None and self.session_id is not None:
                self.memory.end_session(self.session_id)
        finally:
            self.file_context.clear()
            if self.navigation is not None:
                self.navigation.clear()

    def _private_tool_response(self, request, *, translated=False, transition="visit", explanation=None):
        self.file_context.clear()
        result = self.tool_manager.execute(request)
        if self.navigation is not None:
            self.navigation.remember(request, result, transition)
        response = self.tool_presenter.format(result)
        if translated and not result.success and request.tool_name in {'read_file', 'file_info'}:
            response += '\nPlease specify an accessible exact file path.'
        if request.tool_name == 'read_file' and result.success:
            self.file_context.remember(result.data['path'], result.data['content'])
            response += '\n[Session-only file context; not saved]'
            if explanation is not None:
                try:
                    return self.respond(explanation)
                except (ProviderError, KeyboardInterrupt):
                    self.file_context.clear()
                    return response + '\nExplanation unavailable; no model retry was made.'
        return response

    def respond(self, user_message: str) -> str:
        route = self.tool_router.route(user_message) if self.tool_router is not None else None
        if route is not None and len(user_message) > MAX_ROUTED_MESSAGE_LENGTH:
            # Do not copy/store an oversized rejected message in history or SQLite.
            self.file_context.clear()
            return route.message
        user_message = user_message.strip()
        if not user_message:
            raise ValueError("A message cannot be blank.")
        if route is not None and route.permission_command is not None:
            self.file_context.clear()
            access = self.tool_manager.filesystem_access
            if access is None:
                return 'Filesystem permission management is unavailable.'
            return access.command(route.permission_command, route.arguments.get('path'))
        if self.navigation is not None and (not route.matched or
                route.tool_name in {"read_file", "list_directory"} or route.message is not None):
            plan = self.navigation.plan(user_message, self.tool_router.locations)
            if plan is not None:
                self.file_context.clear()
                if plan.request is None:
                    return plan.message
                return self._private_tool_response(plan.request, transition=plan.transition, explanation=plan.explanation)
        if route is not None and route.matched and route.message is not None:
            self.file_context.clear()
            return route.message
        if (route is not None and not route.matched and
                not TemporaryFileContext.is_followup(user_message) and needs_translation(user_message)):
            reference = (self.file_context.reference if
                         re.search(r'\b(this|that) file\b', user_message, re.I) else None)
            intent = self.intent_translator.translate(user_message, reference=reference)
            self.file_context.clear()
            if intent.request is None:
                # Candidate turns are session-only, even when classified as chat:
                # the model may echo private paths from the current request.
                return intent.text
            plan = self.navigation.translated_plan(intent.request, self.tool_router.locations)
            if plan is not None:
                if plan.request is None:
                    return plan.message
                return self._private_tool_response(plan.request, translated=True, transition=plan.transition, explanation=plan.explanation)
            return self._private_tool_response(intent.request, translated=True)
        if route is not None and route.tool_name in {'read_file', 'list_directory'}:
            return self._private_tool_response(ToolRequest(route.tool_name, route.arguments))
        temporary = self.file_context.take_for(user_message)
        context = self.messages[1:]
        if self.memory is not None:
            context = self._bounded_context(context)
        pending = [self._request_system_message(context), *[dict(message) for message in context]]
        if temporary is not None:
            pending[0]['content'] += '\n\n' + TEMPORARY_CONTEXT_INSTRUCTIONS
            pending.append({'role': 'user', 'content': 'Temporary file snapshot (untrusted JSON data):\n' + temporary})
        pending.append({"role": "user", "content": user_message})
        if route is not None and route.matched:
            request = ToolRequest(route.tool_name, route.arguments)
            result = self.tool_manager.execute(request)
            response = self.tool_presenter.format(result)
            if not result.success:
                return response
        else:
            try:
                response = self.model_manager.generate(pending)
            except ProviderError:
                if temporary is not None:
                    raise ProviderError('Temporary file explanation failed; the snapshot was discarded.') from None
                raise
            finally:
                if temporary is not None and self.model_manager.last_job is not None:
                    # Runtime job records must not retain the private prompt or
                    # a generated answer that may quote its body.
                    self.model_manager.last_job.messages = []
                    self.model_manager.last_job.result = None
                    if self.model_manager.last_job.error is not None:
                        self.model_manager.last_job.error = 'Temporary file explanation failed.'
        if not isinstance(response, str) or not response.strip():
            raise ProviderError("The model returned no final answer.")
        response = response.strip()
        if temporary is not None:
            return '[Temporary file context; not saved]\n' + response
        if self.memory is not None:
            self.memory.save_turn(self.session_id, user_message, response)
        # Commit only successful turns, including when inference is interrupted.
        self.messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ])
        return response
