"""Conservative workload choice and redacted session-only measurements."""
from dataclasses import asdict, dataclass
from enum import StrEnum
import re


class WorkloadLevel(StrEnum):
    MINIMAL = 'L0'
    LIGHT = 'L1'
    STANDARD = 'L2'
    DEEP = 'L3'


@dataclass(frozen=True)
class WorkloadDecision:
    level: WorkloadLevel
    reason: str
    profile: str
    inference_needed: bool
    response: str | None = None

    def __post_init__(self):
        profiles = {WorkloadLevel.MINIMAL: 'minimal', WorkloadLevel.LIGHT: 'light',
                    WorkloadLevel.STANDARD: 'standard', WorkloadLevel.DEEP: 'deep'}
        if (not isinstance(self.level, WorkloadLevel) or self.profile != profiles[self.level] or
                type(self.inference_needed) is not bool):
            raise ValueError('Invalid structured workload decision.')


def classify(message, *, deterministic=False, explanation=False, assistant_name='FRIDAY', user_name='Vigneshwar'):
    if type(message) is not str:
        raise ValueError('A workload request must be text.')
    if deterministic:
        if explanation:
            return WorkloadDecision(WorkloadLevel.STANDARD, 'verified_file_explanation', 'standard', True)
        return WorkloadDecision(WorkloadLevel.LIGHT, 'deterministic_route', 'light', False)
    if len(message) > 4096:
        return WorkloadDecision(WorkloadLevel.STANDARD, 'bounded_input_check', 'standard', True)
    text = ' '.join(message.casefold().strip().rstrip('.!?').split())
    name = assistant_name.casefold()
    greetings = {'hello', 'hi', 'good morning', 'hello ' + name, 'hi ' + name}
    if text in greetings:
        return WorkloadDecision(WorkloadLevel.MINIMAL, 'exact_greeting', 'minimal', False, f'Hello, {user_name}!')
    if text in {'thanks', 'thank you'}:
        return WorkloadDecision(WorkloadLevel.MINIMAL, 'exact_gratitude', 'minimal', False, "You're welcome.")
    if text == 'goodbye':
        return WorkloadDecision(WorkloadLevel.MINIMAL, 'exact_farewell', 'minimal', False, 'Goodbye.')
    if re.match(r'^(?:please\s+)?(?:think\s+deeply\b|perform\s+a\s+detailed\s+technical\s+analysis\b|compare\s+.+\s+thoroughly[.!?]*$)', message.strip(), re.I):
        return WorkloadDecision(WorkloadLevel.DEEP, 'explicit_deep_request', 'deep', True)
    return WorkloadDecision(WorkloadLevel.STANDARD, 'ordinary_or_hybrid_request', 'standard', True)


@dataclass(frozen=True)
class ResponseMetrics:
    level: str
    profile: str
    classification_ns: int
    routing_ns: int
    model_request_ns: int
    total_response_ns: int
    model_invocations: int
    python_cpu_ns: int
    python_peak_rss_kib: int | None

    def public(self):
        # No request text, tool names/results, paths, decisions, or timestamps.
        return asdict(self)
