"""Trusted host approval callback; never use retrieved text as a decision."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from friday.intelligence.models import KnowledgeError, check_hash


class KnowledgePurpose(StrEnum):
    READ_DOCUMENT = 'document_read'
    RETAIN = 'knowledge_retention'
    INDEX = 'embedding_indexing'
    RETRIEVE = 'knowledge_retrieval'
    REVOKE = 'knowledge_revocation'


class KnowledgeDecision(StrEnum):
    ALLOW_ONCE = 'allow_once'
    DENY = 'deny'


class KnowledgeAuthorizationDenied(PermissionError):
    """A fixed authorization failure, distinct from OS path permission errors."""


@dataclass(frozen=True)
class AuthorizationRequest:
    purpose: KnowledgePurpose
    targets: tuple[str,...]
    scope_sha256: str

    def __post_init__(self):
        check_hash(self.scope_sha256)
        if (type(self.purpose) is not KnowledgePurpose or type(self.targets) is not tuple or
                not self.targets or len(self.targets)>100 or
                any(type(t) is not str or not t or len(t.encode('utf-8'))>4096 or
                    any(ord(c)<32 or 127<=ord(c)<=159 for c in t) for t in self.targets) or
                len(set(self.targets))!=len(self.targets)):
            raise KnowledgeError('Invalid exact knowledge authorization.')


class KnowledgeAuthorization:
    """Each call asks afresh; no read-grant promotion or persisted approvals.

    Constructor injection is trusted host code, not a model-controlled setting.
    A later CLI must show the exact scope and use the existing owner interaction.
    """
    def __init__(self, approve: Callable[[AuthorizationRequest],KnowledgeDecision] | None = None):
        self._approve=approve

    def require(self, request):
        if type(request) is not AuthorizationRequest:
            raise KnowledgeAuthorizationDenied('Exact knowledge authorization required.')
        try:
            decision=self._approve(request) if self._approve else KnowledgeDecision.DENY
        except Exception:
            raise KnowledgeAuthorizationDenied('Knowledge authorization denied.') from None
        if decision is not KnowledgeDecision.ALLOW_ONCE:
            raise KnowledgeAuthorizationDenied('Knowledge authorization denied.')
