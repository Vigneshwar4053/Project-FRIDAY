"""Exact browser evidence contracts. The production URL verifier is unavailable.

The separately reviewed owner-website handoff lives in firefox_url_handoff;
it reports request acceptance without using these window/page-load contracts.

Constructor-injected backends are trusted code, not model output or a setting.
A future backend must independently prove executable/process, window and URL
identity, bound every call, and support cancellation without killing user apps.
"""
from dataclasses import dataclass
from threading import Lock

from friday.desktop.accessibility import Deadline, DesktopFailure
from friday.desktop.handoffs import HandoffOperation, HandoffRequest
from friday.desktop.observation import WindowRef, identifier
from friday.desktop.workflows import WorkflowAction, WorkflowPlan, bounded_value
from friday.security.owner import OwnerRequest, SensitiveOperation, OwnerAuthenticationError
from friday.tools.access import FolderDecision
from friday.desktop.websites import WEBSITES, approved_url, site_destination, search_url, SEARCH_PROVIDER

SITES = WEBSITES


def exact_destination(value):
    """Only owner-registered destinations; never guess domains or resolve DNS."""
    bounded_value(value)
    destination = site_destination(value)
    if destination is not None:
        return destination
    if approved_url(value):
        return value
    # Preserve the historical compiler form; the handoff still rejects a raw
    # noncanonical tool URL and only receives the canonical resolved destination.
    if value == 'https://www.youtube.com':
        return SITES['youtube']
    raise ValueError('Destination is not in the reviewed browser registry.')


@dataclass(frozen=True)
class BrowserTarget:
    operation: HandoffOperation
    value: str
    url: str

    def __post_init__(self):
        if self.operation is HandoffOperation.NAVIGATE:
            if self.value != exact_destination(self.value) or self.url != self.value:
                raise ValueError('Canonical reviewed destination required.')
        elif self.operation is HandoffOperation.SEARCH:
            bounded_value(self.value)
            if self.url != search_url(self.value):
                raise ValueError('Fixed search provider and exact encoding required.')
        else:
            raise ValueError('Typed browser operation required.')

    @classmethod
    def from_request(cls, request):
        if type(request) is not HandoffRequest:
            raise ValueError('Typed browser request required.')
        if request.operation is HandoffOperation.NAVIGATE:
            value = exact_destination(request.value)
            return cls(request.operation, value, value)
        return cls(request.operation, request.value, search_url(request.value))

    @property
    def scope(self):
        # Both authentication and approval bind query, provider and operation.
        return self.operation.value + ' [firefox] ' + self.url + ' | value: ' + self.value


def compile_browser_plan(plan):
    """Collapse one reviewed six-step plan into one atomic authorization request.

    No generic step interpreter and no partial app launch. All other plans stay
    non-executable. Compilation does not consult a model or inspect the desktop.
    """
    if type(plan) is not WorkflowPlan or plan.clarification or len(plan.steps) != 6:
        return None
    steps = plan.steps
    expected = (WorkflowAction.LAUNCH, WorkflowAction.VERIFY_WINDOW,
                WorkflowAction.ADDRESS, steps[3].action, WorkflowAction.SUBMIT,
                WorkflowAction.VERIFY_NAVIGATION)
    if steps[3].action not in {WorkflowAction.URL, WorkflowAction.SEARCH}:
        return None
    if any(s.action is not a or s.application != 'firefox' or s.scope is not None or
           (i != 3 and s.value is not None) for i, (s, a) in enumerate(zip(steps, expected))):
        return None
    operation = (HandoffOperation.NAVIGATE if steps[3].action is WorkflowAction.URL
                 else HandoffOperation.SEARCH)
    request = HandoffRequest(operation, value=steps[3].value)
    target = BrowserTarget.from_request(request)
    return HandoffRequest(operation, value=target.value)


@dataclass(frozen=True)
class BrowserContext:
    """Reviewed adapter/executable/session fingerprint, not a window title."""
    backend_id: str
    executable_identity: tuple[int, int, int, int]
    session_id: str

    def __post_init__(self):
        identifier(self.backend_id); identifier(self.session_id)
        if (type(self.executable_identity) is not tuple or len(self.executable_identity) != 4 or
                any(type(v) is not int or v < 0 for v in self.executable_identity)):
            raise ValueError('Invalid reviewed executable fingerprint.')


@dataclass(frozen=True)
class BrowserWindow:
    context: BrowserContext
    window: WindowRef
    showing: bool
    launch_attempted: bool

    def __post_init__(self):
        if (type(self.context) is not BrowserContext or type(self.window) is not WindowRef or
                self.window.application_id != 'firefox' or type(self.showing) is not bool or
                type(self.launch_attempted) is not bool):
            raise ValueError('Exact attributed Firefox window required.')


@dataclass(frozen=True)
class NavigationReceipt:
    target: BrowserTarget
    window: BrowserWindow
    navigation_id: str

    def __post_init__(self):
        if type(self.target) is not BrowserTarget or type(self.window) is not BrowserWindow:
            raise ValueError('Typed navigation receipt required.')
        identifier(self.navigation_id)


@dataclass(frozen=True)
class NavigationProof:
    receipt: NavigationReceipt
    final_url: str
    completed: bool

    def matches(self, receipt):
        return (type(self.receipt) is NavigationReceipt and self.receipt == receipt and
                type(self.final_url) is str and self.final_url == receipt.target.url and
                self.completed is True)


class UnavailableFirefoxBackend:
    """Fail-closed production backend: no import-time worker or browser I/O."""
    def supports(self, target):
        return False

    def context(self, target):
        # Must be metadata-only static preparation, never launch/observe/read.
        raise ValueError('No reviewed Firefox navigation verifier.')

    def revalidate(self, context, deadline):
        raise ValueError('Unavailable backend.')

    def acquire(self, context, target, deadline):
        raise ValueError('Unavailable backend.')

    def revalidate_window(self, window, deadline):
        # Recheck process start/executable attribution, exact window and showing
        # state immediately before navigation and after evidence collection.
        raise ValueError('Unavailable backend.')

    def navigate(self, window, target, deadline):
        raise ValueError('Unavailable backend.')

    def verify(self, receipt, deadline):
        raise ValueError('Unavailable backend.')


class BrowserExecution:
    """One-use leases, independent auth/permission, bounded three-call workflow.

    Backends must impose OS-level timeouts in addition to cooperative checks.
    This controller cannot preempt a blocking backend or synchronous CLI input.
    No automatic retries, continuous polling, global keyboard or shell fallback.
    """
    def __init__(self, cancelled, clock, backend=None):
        self.backend = backend if backend is not None else UnavailableFirefoxBackend()
        self.cancelled = cancelled
        self.clock = clock
        self._busy = Lock()

    def available(self, target):
        try:
            return not self.cancelled.is_set() and self.backend.supports(target) is True
        except Exception:
            return False

    def prepare(self, request):
        try:
            target = BrowserTarget.from_request(request)
        except ValueError:
            return {'result': {'status': 'unsupported_destination'}}
        if self.cancelled.is_set():
            return {'result': {'status': 'cancelled'}}
        if not self.available(target):
            return {'result': {'status': 'unsupported_capability'}}
        context = self.backend.context(target)
        if type(context) is not BrowserContext:
            raise ValueError('Missing reviewed Firefox execution context.')
        return {'browser_target': target, 'browser_context': context,
                'browser_backend': self.backend, 'used': False}

    def authorize(self, lease, owner, approval, approval_type):
        target = lease['browser_target']
        if not self.available(target) or self.backend is not lease['browser_backend']:
            raise PermissionError('Capability changed before authorization.')
        if owner is None:
            raise OwnerAuthenticationError('Owner authentication is required.')
        owner.authenticate(OwnerRequest(SensitiveOperation.BROWSER_NAVIGATION,
                                       'firefox', target.scope))
        if self.cancelled.is_set():
            raise PermissionError('Browser task cancelled.')
        request = approval_type(target.operation.value, target.scope,
            'Navigate only to the exact approved URL/query in attributed Firefox. '
            'Verify the exact final URL. No content reads, desktop input, downloads or submissions.',
            'execute')
        try:
            decision = approval.request(request) if approval is not None else FolderDecision.DENY
        except (Exception, KeyboardInterrupt):
            decision = FolderDecision.DENY
        if decision is not FolderDecision.ALLOW_ONCE:
            raise PermissionError('Exact browser action denied.')
        lease['authorized'] = (target, lease['browser_context'], lease['browser_backend'])

    def execute(self, lease):
        target = lease['browser_target']
        if lease.get('authorized') != (target,lease['browser_context'],lease['browser_backend']) or lease['used']:
            raise PermissionError('Missing or consumed exact browser authorization.')
        lease['used'] = True
        if not self._busy.acquire(blocking=False):
            return {'status': 'handoff_failed'}
        phases = ['authenticated', 'permission_approved']
        deadline = Deadline(self.clock() + 10, self.cancelled, self.clock)
        try:
            context = lease['browser_context']
            backend = lease['browser_backend']
            def check():
                deadline.check()
                if (lease['browser_target'] != target or lease['browser_context'] != context or
                        lease.get('authorized') != (target,context,backend)):
                    raise ValueError('Exact authorization context changed.')
                if self.backend is not backend or not self.available(target):
                    raise ValueError('Reviewed capability changed.')
                if BrowserTarget.from_request(HandoffRequest(target.operation, value=target.value)) != target:
                    raise ValueError('Target changed.')
                if backend.revalidate(context, deadline) is not True:
                    raise ValueError('Reviewed executable/session changed.')
                deadline.check()
            check()
            window = backend.acquire(context, target, deadline)
            deadline.check()
            if type(window) is not BrowserWindow or window.context != context or not window.showing:
                return {'status': 'window_unverified', 'phases': tuple(phases)}
            if window.launch_attempted:
                phases.append('launch_attempted')
            phases.append('firefox_window_attributed')
            check()
            if backend.revalidate_window(window, deadline) is not True:
                return {'status': 'window_unverified', 'phases': tuple(phases)}
            deadline.check()
            receipt = backend.navigate(window, target, deadline)
            phases.append('navigation_attempted')
            deadline.check()
            if (type(receipt) is not NavigationReceipt or receipt.target != target or
                    receipt.window != window):
                return {'status': 'navigation_unverified', 'phases': tuple(phases)}
            proof = backend.verify(receipt, deadline)
            deadline.check()
            check()
            if backend.revalidate_window(window, deadline) is not True:
                return {'status': 'navigation_unverified', 'phases': tuple(phases)}
            deadline.check()
            if type(proof) is not NavigationProof or not proof.matches(receipt):
                return {'status': 'navigation_unverified', 'phases': tuple(phases)}
            phases.append('navigation_verified')
            return {'status': 'verified', 'phases': tuple(phases),
                    'message': 'Verified: attributed Firefox completed navigation to the exact approved destination.',
                    'url': target.url}
        except DesktopFailure as failure:
            return {'status': failure.status.value, 'phases': tuple(phases)}
        except (Exception, KeyboardInterrupt):
            # Never propagate backend content, guessed URLs or authentication details.
            return {'status': 'handoff_failed', 'phases': tuple(phases)}
        finally:
            self._busy.release()
