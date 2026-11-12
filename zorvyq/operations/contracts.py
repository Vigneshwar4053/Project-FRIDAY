"""Immutable operation policy and plan types; no executable code supplied by models."""
from dataclasses import dataclass, field, asdict
from enum import StrEnum
import hashlib
import json

class Permission(StrEnum):
    LOCAL = 'READ-ONLY LOCAL'
    NETWORK = 'NETWORK-ACTIVE'
    PRIVILEGED = 'PRIVILEGED'
    CHANGE = 'STATE-CHANGING'
    DESTRUCTIVE = 'DESTRUCTIVE'

@dataclass(frozen=True)
class Stage:
    stage_id: str
    purpose: str
    tool: str = ''
    arguments: tuple[str, ...] = ()
    collector: str = ''
    parser: str = 'text'
    timeout: float = 8
    output_limit: int = 32768
    expected_codes: tuple[int, ...] = (0,)

@dataclass(frozen=True)
class Operation:
    operation_id: str
    name: str
    purpose: str
    permission: Permission = Permission.LOCAL
    stages: tuple[Stage,...] = ()
    input_schema: str = 'No inputs; local machine only'
    target_scope: str = 'Local system metadata; no file contents'
    time_limit: float = 90
    output_limit: int = 262144
    resource_budget: str = 'Sequential; 256 MiB per command, CPU 10s, no parallel generation'
    cancellation: str = 'Stop current owned process group, reap; retain partial report'
    privacy: str = 'Local sensitive metadata; session-only; explicit export'
    side_effects: tuple[str,...] = ()
    privileges: bool = False
    dry_run: str = 'Preview exact commands and metric collectors; execute nothing'
    report_schema: str = 'zorvyq.operation-report.v1'
    verification: str = 'Experimental — mocked tests only; owner acceptance pending'
    implemented: bool = True

    @property
    def required_tools(self):
        tools = {s.tool for s in self.stages if s.tool}
        if self.operation_id == 'network.discovery': tools.add('nmap')
        if tools: tools.add('prlimit')
        return tuple(sorted(tools))

    @property
    def required_permissions(self):
        return (self.permission,)

@dataclass(frozen=True)
class Plan:
    operation_id: str
    target: str
    purpose: str
    stages: tuple[Stage,...]
    permission: Permission
    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()

@dataclass
class StageResult:
    stage_id: str
    status: str
    exit_code: int | None = None
    elapsed: float = 0
    stdout: str = ''
    stderr: str = ''
    metrics: dict = field(default_factory=dict)
    limitation: str = ''
