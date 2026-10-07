"""Explicit permission decisions; no approval tokens or interactive flow yet."""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from friday.tools.models import RiskLevel, ToolRequest, ToolSpec


class PermissionDecision(StrEnum):
    ALLOW = 'allow'
    DENY = 'deny'
    REQUIRE_USER_APPROVAL = 'require_user_approval'


class PermissionPolicy(ABC):
    @abstractmethod
    def evaluate(self, spec: ToolSpec, request: ToolRequest) -> PermissionDecision:
        """Decide using registered metadata and immutable request arguments."""


class RiskPermissionPolicy(PermissionPolicy):
    """Conservative defaults; overrides are trusted application configuration."""
    def __init__(self, overrides: Mapping[RiskLevel, PermissionDecision] | None = None):
        decisions = {
            RiskLevel.READ_ONLY: PermissionDecision.ALLOW,
            RiskLevel.WRITE: PermissionDecision.REQUIRE_USER_APPROVAL,
            RiskLevel.EXECUTE: PermissionDecision.REQUIRE_USER_APPROVAL,
            RiskLevel.PRIVILEGED: PermissionDecision.DENY,
        }
        if overrides is not None:
            for risk, decision in overrides.items():
                if not isinstance(risk, RiskLevel) or not isinstance(decision, PermissionDecision):
                    raise ValueError('Policy overrides require explicit risk and decision enums.')
                decisions[risk] = decision
        self._decisions = MappingProxyType(decisions)

    def evaluate(self, spec: ToolSpec, request: ToolRequest) -> PermissionDecision:
        return self._decisions[spec.risk]
