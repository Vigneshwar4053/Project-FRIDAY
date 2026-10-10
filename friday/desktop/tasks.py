"""Single bounded deterministic task; no model, file, network or GUI dispatch."""
from dataclasses import dataclass
import math
from threading import Lock
from time import monotonic
from friday.desktop.actions import DesktopAction, Operation
from friday.desktop.observation import WindowSnapshot
from friday.tools.manager import ToolManager
from friday.tools.models import ToolRequest, ToolStatus


@dataclass(frozen=True)
class TaskPlan:
    actions: tuple[DesktopAction, ...]
    action_limit: int = 8
    observation_limit: int = 20
    timeout: float = 60

    def __post_init__(self):
        if type(self.actions) is not tuple or not 1 <= len(self.actions) <= 8 or any(type(a) is not DesktopAction for a in self.actions):
            raise ValueError('A bounded typed deterministic plan is required.')
        if type(self.action_limit) is not int or not 1 <= self.action_limit <= 8:
            raise ValueError('Invalid action bound.')
        if type(self.observation_limit) is not int or not 1 <= self.observation_limit <= 20:
            raise ValueError('Invalid observation bound.')
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 60:
            raise ValueError('Invalid task timeout.')
        # Initial scope is exactly one application/window; no silent expansion.
        if any(a.window != self.actions[0].window for a in self.actions):
            raise ValueError('A task must target one exact window.')

    def preview(self):
        # Exact text/effects shown only to the owner, never retained in receipts.
        return tuple(action.arguments() for action in self.actions)


@dataclass(frozen=True)
class TaskReport:
    status: str
    completed: int
    attempted: int
    steps: tuple[str, ...]


class DesktopTaskEngine:
    def __init__(self, manager, *, clock=monotonic):
        if not isinstance(manager, ToolManager) or manager.computer_access is None:
            raise ValueError('Existing permission gateway with computer adapter required.')
        self.manager = manager
        self.permissions = manager.computer_access
        self.clock = clock
        self._running = Lock()

    def stop(self):
        self.permissions.stop()

    def reset_stop(self):
        if not self._running.acquire(blocking=False):
            raise ValueError('Task already running.')
        try:
            self.permissions.reset_stop()
        finally:
            self._running.release()

    def _request(self, action, revision=None):
        result = self.manager.execute(ToolRequest('computer_action', {'action': action.arguments(revision)}),
                                      persist_metadata=False)
        if not result.success:
            return ('denied' if result.error_category and result.error_category.value == 'permission_denied'
                    or result.status in {ToolStatus.DENIED, ToolStatus.APPROVAL_REQUIRED} else 'failed'), None
        return result.data['status'], result.data

    def run(self, plan):
        if type(plan) is not TaskPlan:
            raise ValueError('Model text/JSON is not a task plan.')
        if not self._running.acquire(blocking=False):
            return TaskReport('busy', 0, 0, ())
        completed = attempted = 0
        receipts = []
        try:
            if self.permissions.cancelled.is_set():
                return TaskReport('cancelled', 0, 0, ())
            mutations = sum(a.operation not in {Operation.OBSERVE, Operation.VERIFY} for a in plan.actions)
            if mutations > plan.action_limit:
                return TaskReport('action_limit', 0, 0, ())
            expires = self.clock() + plan.timeout
            self.permissions.begin_task(expires, plan.observation_limit)
            previous_revision = None
            for action in plan.actions:
                if self.permissions.cancelled.is_set():
                    return TaskReport('cancelled', completed, attempted, tuple(receipts))
                if self.clock() >= expires:
                    return TaskReport('timeout', completed, attempted, tuple(receipts))
                revision = None
                if action.operation not in {Operation.OBSERVE, Operation.VERIFY}:
                    observed, data = self._request(DesktopAction(Operation.OBSERVE, action.window, timeout=action.timeout))
                    if observed != 'verified':
                        return TaskReport(observed, completed, attempted, tuple(receipts))
                    revision = WindowSnapshot.from_data(data['snapshot']).revision
                    if previous_revision is not None and revision != previous_revision:
                        return TaskReport('target_changed', completed, attempted, tuple(receipts))
                attempted += 1
                status, data = self._request(action, revision)
                receipts.append(status)
                if status != 'verified':
                    return TaskReport(status, completed, attempted, tuple(receipts))
                completed += 1
                if data is not None:
                    previous_revision = data.get('revision', previous_revision)
            return TaskReport('verified', completed, attempted, tuple(receipts))
        except KeyboardInterrupt:
            self.stop()
            return TaskReport('cancelled', completed, attempted, tuple(receipts))
        except Exception:
            return TaskReport('failed', completed, attempted, tuple(receipts))
        finally:
            self.permissions.end_task()
            self._running.release()
