"""One-use exact-plan approval. No passwords, persistent grants or auto-elevation."""
from dataclasses import dataclass
from time import monotonic
from .contracts import Permission

@dataclass(frozen=True)
class Approval:
    fingerprint: str
    expires: float
    authorized_target: bool

class Permissions:
    def __init__(self):
        self.pending = {}
    def approve(self, plan, *, confirmed=False, authorized_target=False):
        if not confirmed or plan.permission not in (Permission.LOCAL,Permission.NETWORK):
            raise PermissionError('Explicit scope approval required; privileged/change operations are not enabled.')
        if plan.permission == Permission.NETWORK and not authorized_target:
            raise PermissionError('Explicit network target authorization required.')
        ticket=Approval(plan.fingerprint,monotonic()+120,authorized_target)
        self.pending[id(ticket)]=ticket
        return ticket
    def consume(self, plan, ticket):
        stored=self.pending.pop(id(ticket),None)
        if stored is None or stored is not ticket or ticket.fingerprint != plan.fingerprint or monotonic()>ticket.expires:
            raise PermissionError('Approval is missing, changed, already consumed or expired.')
    def clear(self):
        self.pending.clear()
