"""Session conversation flow, independent of transport and terminal I/O."""
import re
import resource
import sys
from collections import deque
from time import perf_counter_ns, process_time_ns
from friday.config.settings import settings, Settings
from friday.core.context import select_context
from friday.core.workload import classify, WorkloadLevel, WorkloadDecision, ResponseMetrics
from friday.core.response import (ResponseMetadata, ResponseCategory, ResponseProvenance,
    public_conversation_request, message_fingerprint, speech_text_has_sensitive_structure)
from friday.core.navigation import NavigationManager
from friday.models.profile import STANDARD_RESPONSE_INSTRUCTIONS, DEEP_RESPONSE_INSTRUCTIONS
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
                 tool_presenter: ToolPresenter | None = None,
                 workload_configuration: Settings | None = None):
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
        self.workload_configuration = workload_configuration if workload_configuration is not None else settings
        if not isinstance(self.workload_configuration, Settings):
            raise ValueError('Workload configuration must be validated settings.')
        self.adaptive_workloads = self.workload_configuration.adaptive_workloads
        self.last_performance = None
        self._measurement = None
        self.last_response_metadata = ResponseMetadata()  # Never retains response text.
        self._speech_public_history = deque(maxlen=40)  # Session-only public fingerprints.
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
            self._speech_public_history.clear()
            self.last_response_metadata = ResponseMetadata()
            self.file_context.clear()
            desktop=getattr(self.tool_manager,'desktop_access',None)
            if desktop is not None and desktop.discovery is not None:
                desktop.discovery.clear()
            if self.navigation is not None:
                self.navigation.clear()

    def _private_tool_response(self, request, *, translated=False, transition="visit", explanation=None):
        self.last_response_metadata = ResponseMetadata(ResponseCategory.TOOL, ResponseProvenance.TOOL_RUNTIME)
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
                finally:
                    self.last_response_metadata = ResponseMetadata(ResponseCategory.PRIVATE, ResponseProvenance.PRIVATE_CONTEXT)
        return response

    def _choose_workload(self, message, *, deterministic=False, explanation=False):
        if not self.adaptive_workloads:
            return None
        started = perf_counter_ns()
        try:
            decision = classify(message, deterministic=deterministic, explanation=explanation,
                assistant_name=self.workload_configuration.assistant_name,
                user_name=self.workload_configuration.user_name)
            if not isinstance(decision, WorkloadDecision):
                raise ValueError('Invalid workload classification.')
            self._measurement['decision'] = decision
            return decision
        except Exception:
            self.file_context.clear()
            raise ProviderError('Workload selection failed safely; no alternate action was attempted.') from None
        finally:
            self._measurement['classification_ns'] += max(0, perf_counter_ns() - started)

    def respond(self, user_message: str, *, persist: bool = True) -> str:
        """A private turn neither saves nor enters reusable conversation history."""
        if type(persist) is not bool:
            raise ValueError('Persistence must be a boolean.')
        self.last_response_metadata = ResponseMetadata()
        try:
            return self._respond_measured(user_message, persist=persist)
        except BaseException:
            self.last_response_metadata = ResponseMetadata(ResponseCategory.ERROR, ResponseProvenance.UNKNOWN)
            raise
        finally:
            if not persist and self.model_manager.last_job is not None:
                self.model_manager.last_job.messages = []
                self.model_manager.last_job.result = None
                if self.model_manager.last_job.error is not None:
                    self.model_manager.last_job.error = 'Private turn failed.'

    def _respond_measured(self, user_message: str, *, persist: bool) -> str:
        if not self.adaptive_workloads:
            return self._respond(user_message, persist=persist)
        if self._measurement is not None:
            return self._respond(user_message, persist=persist)  # Existing one-use file explanation, one outer measurement.
        started, cpu = perf_counter_ns(), process_time_ns()
        count, model_time = self.model_manager.invocation_count, self.model_manager.model_request_ns
        self._measurement = {'decision': WorkloadDecision(WorkloadLevel.STANDARD, 'pending', 'standard', True),
                             'classification_ns': 0, 'routing_ns': 0}
        try:
            decision = self._choose_workload(user_message)
            if decision.level is WorkloadLevel.MINIMAL:
                self.file_context.clear()
                self.last_response_metadata = ResponseMetadata(ResponseCategory.GREETING, ResponseProvenance.LOCAL_GREETING)
                return decision.response
            return self._respond(user_message, persist=persist)
        finally:
            measure = self._measurement
            try:
                peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) if sys.platform.startswith('linux') else None
            except (OSError, ValueError):
                peak = None  # Optional observability must never break a response.
            self.last_performance = ResponseMetrics(str(measure['decision'].level), measure['decision'].profile,
                measure['classification_ns'], measure['routing_ns'], self.model_manager.model_request_ns - model_time,
                max(0, perf_counter_ns() - started), self.model_manager.invocation_count - count,
                max(0, process_time_ns() - cpu), peak)
            self._measurement = None

    def _respond(self, user_message: str, *, persist: bool = True) -> str:
        started_routing = perf_counter_ns()
        route = self.tool_router.route(user_message) if self.tool_router is not None else None
        if self._measurement is not None:
            self._measurement['routing_ns'] += max(0, perf_counter_ns() - started_routing)
        if route is not None and len(user_message) > MAX_ROUTED_MESSAGE_LENGTH:
            # Do not copy/store an oversized rejected message in history or SQLite.
            self.file_context.clear()
            return route.message
        user_message = user_message.strip()
        if not user_message:
            raise ValueError("A message cannot be blank.")
        if route is not None and (route.workflow is not None or route.reference_message):
            if user_message.casefold() in {'stop','/stop'}:
                computer=getattr(self.tool_manager,'computer_access',None)
                if computer is not None: computer.stop()
                desktop=getattr(self.tool_manager,'desktop_access',None)
                if desktop is not None: desktop.stop_handoffs()
            self.last_response_metadata = ResponseMetadata(ResponseCategory.TOOL, ResponseProvenance.TOOL_RUNTIME)
            self._choose_workload(user_message,deterministic=True)
            self.file_context.clear()
            if route.workflow is not None:
                from friday.desktop.browser_execution import compile_browser_plan, BrowserTarget
                desktop=getattr(self.tool_manager,'desktop_access',None)
                available=getattr(desktop,'browser_available',None)
                try:
                    request=compile_browser_plan(route.workflow)
                    if request is not None and available is not None and available(BrowserTarget.from_request(request)):
                        result=self.tool_manager.execute(ToolRequest(request.operation.value,{'url' if request.operation.value=='navigate_firefox_to_exact_url' else 'query':request.value}),persist_metadata=False)
                        return self.tool_presenter.format(result)
                    if request is not None:
                        handoff = getattr(desktop,'firefox_url_handoff',None)
                        reason = getattr(getattr(handoff,'adapter',None),'reason',None)
                        if reason:
                            return reason
                except ValueError:
                    return 'This browser destination or query is outside the reviewed policy. No workflow steps were executed.'
            return route.message
        if route is not None and route.permission_command is not None:
            self.last_response_metadata = ResponseMetadata(ResponseCategory.TOOL, ResponseProvenance.TOOL_RUNTIME)
            self._choose_workload(user_message, deterministic=True)
            self.file_context.clear()
            access = self.tool_manager.filesystem_access
            if access is None:
                return 'Filesystem permission management is unavailable.'
            return access.command(route.permission_command, route.arguments.get('path'))
        from friday.desktop.routing import DESKTOP_TOOLS
        if (route is not None and route.tool_name=='discover_target' and self.navigation is not None and
                self.navigation.current is not None and route.arguments.get('action')=='open' and
                'scope' not in route.arguments and 'application_id' not in route.arguments):
            # Preserve the existing explicit terminal-listing reference workflow.
            # Destination/scope-qualified requests always use new discovery.
            plan=self.navigation.plan(user_message,self.tool_router.locations)
            name=route.arguments['name'].casefold()
            variants={name,re.sub(r'^(?:my|the)\s+','',name)}
            variants|={re.sub(r'\s+(?:folder|directory|file)$','',item) for item in tuple(variants)}
            listed={key.casefold() for key in self.navigation.children}
            if name.endswith(' file'):
                from pathlib import Path
                listed|={Path(key).stem.casefold() for key in self.navigation.children}
            if plan is not None and (plan.request is not None or variants & listed):
                self._choose_workload(user_message,deterministic=True,explanation=plan.explanation is not None)
                self.file_context.clear()
                if plan.request is None: return plan.message
                return self._private_tool_response(plan.request,transition=plan.transition,explanation=plan.explanation)
        if route is not None and route.tool_name in DESKTOP_TOOLS:
            self.last_response_metadata = ResponseMetadata(ResponseCategory.TOOL, ResponseProvenance.TOOL_RUNTIME)
            self._choose_workload(user_message, deterministic=True)
            self.file_context.clear()
            result = self.tool_manager.execute(ToolRequest(route.tool_name, route.arguments), persist_metadata=persist)
            # Desktop paths/session facts stay out of chat history and speech.
            return self.tool_presenter.format(result)
        if self.navigation is not None and (not route.matched or
                route.tool_name in {"read_file", "list_directory"} or route.message is not None):
            started_routing = perf_counter_ns()
            plan = self.navigation.plan(user_message, self.tool_router.locations)
            if self._measurement is not None:
                self._measurement['routing_ns'] += max(0, perf_counter_ns() - started_routing)
            if plan is not None:
                self._choose_workload(user_message, deterministic=True, explanation=plan.explanation is not None)
                self.file_context.clear()
                if plan.request is None:
                    return plan.message
                return self._private_tool_response(plan.request, transition=plan.transition, explanation=plan.explanation)
        if route is not None and route.matched and route.message is not None:
            self._choose_workload(user_message, deterministic=True)
            self.file_context.clear()
            return route.message
        deep = self.adaptive_workloads and self._measurement['decision'].level is WorkloadLevel.DEEP
        if deep and (re.search(r'\b(?:read|open|list|execute|write_file|bypass)\s+(?:[^\s]*[/\.]|that file|this file)', user_message, re.I) or
                     re.search(r'\b(?:and|then)\s+(?:read|open|list|show|run|execute|delete|write_file|bypass)\b', user_message, re.I)):
            self.file_context.clear()
            return 'Use an explicit supported filesystem command first; deep analysis does not authorize file access.'
        if (not deep and route is not None and not route.matched and
                not TemporaryFileContext.is_followup(user_message) and needs_translation(user_message)):
            reference = (self.file_context.reference if
                         re.search(r'\b(this|that) file\b', user_message, re.I) else None)
            intent = (self.intent_translator.translate(user_message, reference=reference,
                      profile=self.workload_configuration.standard_inference_profile) if self.adaptive_workloads
                      else self.intent_translator.translate(user_message, reference=reference))
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
            self._choose_workload(user_message, deterministic=True)
            return self._private_tool_response(ToolRequest(route.tool_name, route.arguments))
        temporary = self.file_context.take_for(user_message)
        context = self.messages[max(1, len(self.messages) - 40):] if self.adaptive_workloads else self.messages[1:]
        if self.memory is not None:
            context = self._bounded_context(context)
        profile = None
        if self.adaptive_workloads and not (route is not None and route.matched):
            decision = self._measurement['decision']
            profile = (self.workload_configuration.deep_inference_profile if decision.level is WorkloadLevel.DEEP
                       else self.workload_configuration.standard_inference_profile)
            def system_builder(recent):
                system = self._request_system_message(recent)
                if decision.level is WorkloadLevel.STANDARD:
                    system['content'] += '\n\n' + STANDARD_RESPONSE_INSTRUCTIONS
                else:
                    system['content'] += '\n\n' + DEEP_RESPONSE_INSTRUCTIONS
                if temporary is not None:
                    system['content'] += '\n\n' + TEMPORARY_CONTEXT_INSTRUCTIONS
                return system
            pending = select_context(context, user_message, profile, system_builder, temporary=temporary)
        else:
            pending = [self._request_system_message(context), *[dict(message) for message in context]]
            if temporary is not None:
                pending[0]['content'] += '\n\n' + TEMPORARY_CONTEXT_INSTRUCTIONS
                pending.append({'role': 'user', 'content': 'Temporary file snapshot (untrusted JSON data):\n' + temporary})
            pending.append({"role": "user", "content": user_message})
        if route is not None and route.matched:
            self.last_response_metadata = ResponseMetadata(ResponseCategory.TOOL, ResponseProvenance.TOOL_RUNTIME)
            self._choose_workload(user_message, deterministic=True)
            request = ToolRequest(route.tool_name, route.arguments)
            result = self.tool_manager.execute(request)
            response = self.tool_presenter.format(result)
            if not result.success:
                return response
        else:
            try:
                response = (self.model_manager.generate(pending, profile=profile) if profile is not None
                            else self.model_manager.generate(pending))
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
            self.last_response_metadata = ResponseMetadata(ResponseCategory.PRIVATE, ResponseProvenance.PRIVATE_CONTEXT)
            return '[Temporary file context; not saved]\n' + response
        if route is None or not route.matched:
            # Actual model inputs, not workload level or labels in model output,
            # determine speech safety. Restored/manual/untrusted context has no
            # current-session public provenance and therefore fails closed.
            recent = pending[1:-1]
            clean = all(message_fingerprint(message) in self._speech_public_history for message in recent)
            eligible = (clean and public_conversation_request(user_message, has_public_context=bool(recent))
                        and not speech_text_has_sensitive_structure(response))
            self.last_response_metadata = ResponseMetadata(
                ResponseCategory.CONVERSATION if eligible else ResponseCategory.PRIVATE,
                ResponseProvenance.PUBLIC_MODEL_CONTEXT if eligible else ResponseProvenance.PRIVATE_CONTEXT)
        if persist and self.memory is not None:
            self.memory.save_turn(self.session_id, user_message, response)
        # Commit only successful turns, including when inference is interrupted.
        if persist:
            committed = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response},
            ]
            self.messages.extend(committed)
            if self.last_response_metadata.speech_eligible:
                self._speech_public_history.extend(message_fingerprint(message) for message in committed)
        return response
