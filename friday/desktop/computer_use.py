"""Exact request-local capabilities through the existing ToolManager gateway."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
from threading import Event, Lock
from time import monotonic

from friday.desktop.accessibility import AccessibilityBackend, Deadline, DesktopFailure
from friday.desktop.actions import DesktopAction, Operation
from friday.desktop.observation import APPLICATION_IDS, DesktopStatus, WindowSnapshot, WindowRef
from friday.tools.access import FolderDecision
from friday.tools.base import Tool
from friday.tools.models import ArgumentSpec, ArgumentType, RiskLevel, ToolSpec
from friday.security.owner import OwnerAuthenticationError

COMPUTER_TOOLS = frozenset({'computer_list_windows', 'computer_action'})


@dataclass(frozen=True)
class ComputerApproval:
    operation: str
    scope: str

    def prompt(self):
        return ('Permission required: computer use\nOperation: ' + self.operation +
                '\nExact scope: ' + self.scope +
                '\nAllow once for this request only; no capture, clipboard, filesystem, '
                'submission or future-action grant.\n[1] Allow once\n[3] Deny')


class ComputerUsePermissions:
    def __init__(self, backend, approval=None, *, clock=monotonic, owner_auth=None):
        if not isinstance(backend, AccessibilityBackend):
            raise ValueError('Typed accessibility backend required.')
        self.backend = backend
        self.approval = approval
        self.owner_auth = owner_auth
        self.clock = clock
        self.cancelled = Event()
        self._lease = ContextVar('computer_use_lease', default=None)
        self._executing = Lock()
        self._observations = 0
        self._observation_limit = 20
        self._task_expiry = None

    def handles(self, request):
        return request.tool_name in COMPUTER_TOOLS

    def stop(self):
        self.cancelled.set()
        self.backend.cancel()

    def close(self):
        self.stop()
        self.backend.close()

    def begin_task(self, expires, observation_limit=20):
        # Called only by the trusted single-task engine while no request runs.
        if self._executing.locked():
            raise ValueError('Computer-use request already executing.')
        self._observations = 0
        self._observation_limit = observation_limit
        self._task_expiry = expires

    def end_task(self):
        self._task_expiry = None

    def reset_stop(self):
        if self._executing.locked() or self._task_expiry is not None:
            raise ValueError('Cannot clear STOP during execution.')
        self.cancelled = Event()

    def _observe(self, window, deadline):
        deadline.check()
        if self._observations >= self._observation_limit:
            raise DesktopFailure(DesktopStatus.FAILED)
        self._observations += 1
        snapshot = self.backend.observe(window, deadline)
        deadline.check()
        if type(snapshot) is not WindowSnapshot or snapshot.window != window:
            raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
        if snapshot.sensitive:
            raise DesktopFailure(DesktopStatus.UNSUPPORTED)
        return snapshot

    @contextmanager
    def execution(self, request, *, persist_metadata=True):
        if not self._executing.acquire(blocking=False):
            raise PermissionError('Computer-use operation already running.')
        token = None
        try:
            action = None
            revision = None
            if request.tool_name == 'computer_action':
                action, revision = DesktopAction.from_arguments(request.arguments['action'])
                timeout = action.timeout
                if action.operation not in {Operation.OBSERVE, Operation.VERIFY} and revision is None:
                    raise ValueError('Actions require a fresh observation revision.')
            elif request.tool_name == 'computer_list_windows':
                if request.arguments['application_id'] not in APPLICATION_IDS:
                    raise ValueError('Unsupported application.')
                timeout = request.arguments['timeout']
                import math
                if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
                    raise ValueError('Invalid timeout.')
            else:
                raise ValueError('Unsupported operation.')
            expires = self.clock() + timeout
            if self._task_expiry is not None:
                expires = min(expires, self._task_expiry)
            deadline = Deadline(expires, self.cancelled, self.clock)
            # Real mutation is deliberately unavailable before observation or
            # prompting; this checkpoint cannot accidentally dispatch input.
            unavailable = (action is not None and action.operation not in
                           {Operation.OBSERVE, Operation.VERIFY} and not self.backend.supports_actions)
            if not unavailable:
                deadline_failed = False
                try:
                    deadline.check()
                    scope_data = dict(request.arguments)
                    mode = getattr(self.backend, 'observation_mode', None)
                    if mode is not None:
                        scope_data['observation_mode'] = mode
                    scope = json.dumps(scope_data, ensure_ascii=True,
                                       separators=(',', ':'), default=dict)
                    if action is not None and action.operation not in {Operation.OBSERVE, Operation.VERIFY} and self.owner_auth is not None:
                        from friday.security.owner import OwnerRequest, SensitiveOperation
                        self.owner_auth.authenticate(OwnerRequest(SensitiveOperation.DESKTOP_INPUT,
                            action.window.application_id,scope))
                    decision = (self.approval.request(ComputerApproval(
                        action.operation.value if action else 'list_windows', scope))
                        if self.approval is not None else FolderDecision.DENY)
                except OwnerAuthenticationError:
                    raise
                except DesktopFailure:
                    deadline_failed = True
                    decision = None
                except (Exception, KeyboardInterrupt):
                    decision = FolderDecision.DENY
                if not deadline_failed and decision is not FolderDecision.ALLOW_ONCE:
                    raise PermissionError('Computer-use permission denied.')
            token = self._lease.set((request, action, revision, deadline, unavailable, [False]))
            yield
        finally:
            if token is not None:
                self._lease.reset(token)
            self._executing.release()

    def execute(self, name, arguments):
        lease = self._lease.get()
        if lease is None or lease[0].tool_name != name or dict(lease[0].arguments) != dict(arguments):
            raise PermissionError('No exact computer-use lease.')
        _, action, revision, deadline, unavailable, used = lease
        if used[0]:
            raise PermissionError('Computer-use lease already consumed.')
        used[0] = True
        try:
            deadline.check()
            if unavailable:
                raise DesktopFailure(DesktopStatus.UNSUPPORTED)
            if action is None:
                if self._observations >= self._observation_limit:
                    raise DesktopFailure(DesktopStatus.FAILED)
                self._observations += 1
                windows = self.backend.list_windows(arguments['application_id'], deadline)
                deadline.check()
                if (type(windows) is not tuple or len(windows) > 20 or
                        any(type(w) is not WindowSnapshot or w.window.application_id != arguments['application_id']
                            or w.sensitive or w.elements for w in windows) or
                        len({w.window.window_id for w in windows}) != len(windows)):
                    raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
                return {'status': 'verified', 'windows': [w.to_data() for w in windows]}
            before = self._observe(action.window, deadline)
            if action.operation is Operation.OBSERVE:
                return {'status': 'verified', 'snapshot': before.to_data()}
            if action.operation is Operation.VERIFY:
                return {'status': ('verified' if action.expected.matches(before) else 'invoked_unverified')}
            if before.revision != revision:
                raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
            if action.operation is not Operation.FOCUS and not before.focused:
                raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
            if action.control_id is not None:
                control = before.control(action.control_id)
                if control is None or control.sensitive or not control.showing or not control.enabled:
                    raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
                # Effect is trusted backend/app-policy metadata, not a label
                # chosen by a model. General navigation/submission is excluded.
                if control.effect != 'local':
                    raise DesktopFailure(DesktopStatus.UNSUPPORTED)
                if action.operation is Operation.TYPE and (control.role != 'text' or not control.editable):
                    raise DesktopFailure(DesktopStatus.UNSUPPORTED)
                if action.operation is Operation.ACTIVATE and action.action_name not in control.actions:
                    raise DesktopFailure(DesktopStatus.UNSUPPORTED)
            deadline.check()
            invoked = self.backend.perform(action, deadline)
            deadline.check()
            if type(invoked) is not bool:
                raise DesktopFailure(DesktopStatus.FAILED)
            if not invoked:
                return {'status': 'invoked_unverified'}
            after = self._observe(action.window, deadline)
            if action.operation is not Operation.FOCUS and not after.focused:
                raise DesktopFailure(DesktopStatus.TARGET_CHANGED)
            return {'status': ('verified' if action.expected.matches(after) else 'invoked_unverified'),
                    'revision': after.revision}
        except DesktopFailure as failure:
            return {'status': failure.status.value}
        except Exception:
            return {'status': 'failed'}  # Never surface backend text/errors.


class ComputerTool(Tool):
    def __init__(self, name, permissions):
        schema = ({'action': ArgumentSpec(ArgumentType.OBJECT)} if name == 'computer_action' else
                  {'application_id': ArgumentSpec(ArgumentType.STRING), 'timeout': ArgumentSpec(ArgumentType.NUMBER)})
        super().__init__(ToolSpec(name, 'Exact scoped computer-use foundation operation.', schema,
                                 RiskLevel.EXECUTE))
        self.permissions = permissions

    def execute(self, arguments):
        return self.permissions.execute(self.spec.name, arguments)


def register_computer_tools(registry, permissions):
    for name in sorted(COMPUTER_TOOLS):
        registry.register(ComputerTool(name, permissions))
