"""Distinct reviewed handoffs; authentication never enables a missing verifier.

No production target-verification backend exists yet. The owner-website Snap
handoff can report request acceptance, explicitly without page-load verification.
Constructor-injected mock verifiers are not a runtime enablement setting.
"""
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re

from friday.desktop.observation import WindowRef
from friday.desktop.workflows import bounded_value, website


class HandoffOperation(StrEnum):
    PROJECT = 'open_project_in_vscode'
    FILE = 'open_file_in_vscode'
    NAVIGATE = 'navigate_firefox_to_exact_url'
    SEARCH = 'search_firefox_for_query'


HANDOFF_TOOLS = frozenset(operation.value for operation in HandoffOperation)
HANDOFF_FAILURE_MESSAGES = {
    'url_handoff_unavailable':'Reviewed Firefox URL handoff is unavailable or changed; no launch attempted.',
    'url_handoff_failed':'Firefox URL handoff failed or changed; page load was not independently verified. No retry was attempted.',
    'url_handoff_cancelled':'Firefox URL handoff cancelled. An already-started request may have reached Firefox; page load was not independently verified. No retry was attempted.',
    'url_handoff_timeout':'Firefox URL handoff timed out. The request may have reached Firefox; page load was not independently verified. No retry was attempted.',
    'unsupported_destination':'Browser destination or query is outside the reviewed policy; no launch or navigation attempted.',
    'window_unverified':'Firefox window attribution or visibility could not be verified; navigation was not attempted.',
    'navigation_unverified':'Firefox navigation was attempted, but the exact final destination was not verified. Completion is not claimed.',
    'unsupported_capability':'Application handoff is disabled: reviewed exact-target verification is unavailable. Owner authentication cannot enable it; no launch attempted.',
    'unsupported_target':'Application target handoff is blocked by the Snap app-only policy; no fallback or launch attempted.',
    'invalid_target':'Exact file/project target is invalid or has the wrong type; no launch attempted.',
    'invalid_selection':'Discovery receipt is missing, expired or already consumed; find and select the target again.',
    'needs_selection':'Target selection is incomplete or ambiguous; select one exact target before requesting a handoff.',
    'unavailable':'Application or exact target is unavailable, invalid or changed; no launch attempted.',
    'launch_limit_reached':'Session launch limit reached; no new launch attempted.',
    'handoff_unverified':'VS Code launch was attempted, but the exact displayed target was not verified. Task stopped; completion is not claimed.',
    'handoff_failed':'Application handoff failed safely; no exact displayed target was verified.',
    'cancelled':'Application handoff cancelled; no target completion is claimed.',
    'timeout':'Application handoff timed out; task stopped and no target completion is claimed.',
}


@dataclass(frozen=True)
class HandoffRequest:
    operation: HandoffOperation
    project_id: str | None = None
    token: str | None = None
    value: str | None = None

    def __post_init__(self):
        if type(self.operation) is not HandoffOperation:
            raise ValueError('Typed handoff required.')
        if self.operation in {HandoffOperation.PROJECT,HandoffOperation.FILE}:
            if self.value is not None or (self.project_id is None)==(self.token is None):
                raise ValueError('Exactly one trusted target reference is required.')
            if self.project_id is not None and (self.operation is not HandoffOperation.PROJECT or
                    type(self.project_id) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',self.project_id)):
                raise ValueError('Invalid registered project.')
            if self.token is not None and (type(self.token) is not str or not re.fullmatch(r'[a-f0-9]{32}',self.token)):
                raise ValueError('Invalid discovery receipt.')
        else:
            if self.project_id is not None or self.token is not None:
                raise ValueError('Unexpected browser target.')
            bounded_value(self.value)
            if self.operation is HandoffOperation.NAVIGATE and website(self.value)!=self.value:
                raise ValueError('An exact validated HTTPS URL is required; no guessed domain.')

    @classmethod
    def from_arguments(cls, name, arguments):
        operation=HandoffOperation(name)
        allowed=({'project_id','token'} if operation is HandoffOperation.PROJECT else
                 {'token'} if operation is HandoffOperation.FILE else
                 {'url'} if operation is HandoffOperation.NAVIGATE else {'query'})
        if not set(arguments)<=allowed:
            raise ValueError('Unreviewed handoff arguments.')
        if operation in {HandoffOperation.PROJECT,HandoffOperation.FILE}:
            return cls(operation,project_id=arguments.get('project_id'),token=arguments.get('token'))
        return cls(operation,value=arguments.get('url' if operation is HandoffOperation.NAVIGATE else 'query'))


@dataclass(frozen=True)
class HandoffTarget:
    operation: HandoffOperation
    path: str
    identity: tuple
    fingerprint: tuple
    executable_identity: tuple

    def __post_init__(self):
        if type(self.operation) is not HandoffOperation or self.operation not in {HandoffOperation.PROJECT,HandoffOperation.FILE}:
            raise ValueError('Unsupported verified handoff.')
        path=Path(self.path)
        if not path.is_absolute() or '..' in path.parts or str(path)!=self.path:
            raise ValueError('Canonical target required.')
        for value,length in ((self.identity,2),(self.fingerprint,4),(self.executable_identity,4)):
            if type(value) is not tuple or len(value)!=length or any(type(n) is not int or n<0 for n in value):
                raise ValueError('Pinned identity required.')


@dataclass(frozen=True)
class HandoffProof:
    target: HandoffTarget
    window: WindowRef
    showing: bool

    def matches(self, expected):
        return (type(self.target) is HandoffTarget and self.target==expected and
                type(self.window) is WindowRef and self.window.application_id=='vscode' and
                self.showing is True)


class HandoffVerifier:
    """Trusted adapter contract. Production default cannot certify exact targets.

    A future implementation must prove the actual displayed target, not echo
    argv, infer from a title or merely discover a running application process.
    Its observation must have its own reviewed, bounded permission contract.
    """
    def supports(self, operation):
        return False

    def verify(self, target, deadline):
        raise ValueError('Exact VS Code target verification is unavailable.')
