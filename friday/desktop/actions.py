"""Deterministic action and postcondition definitions; no executable proposals."""
from dataclasses import dataclass
from enum import StrEnum
from friday.desktop.observation import WindowRef, identifier, safe_text


class Operation(StrEnum):
    OBSERVE = 'observe'
    FOCUS = 'focus'
    ACTIVATE = 'activate'
    TYPE = 'type'
    SHORTCUT = 'shortcut'
    VERIFY = 'verify'


SHORTCUTS = frozenset({'ENTER', 'ESCAPE', 'CTRL_L', 'ALT_LEFT'})


@dataclass(frozen=True)
class UIState:
    focused: bool | None = None
    control_id: str | None = None
    text: str | None = None
    showing: bool | None = None

    def __post_init__(self):
        if self.focused is not None and type(self.focused) is not bool:
            raise ValueError('Invalid focus predicate.')
        if self.showing is not None and type(self.showing) is not bool:
            raise ValueError('Invalid visibility predicate.')
        if self.control_id is not None:
            identifier(self.control_id)
        if self.text is not None:
            safe_text(self.text)
        if (self.text is not None or self.showing is not None) and self.control_id is None:
            raise ValueError('Control predicates require a control.')
        if self.focused is None and self.text is None and self.showing is None:
            raise ValueError('An explicit postcondition is required.')

    def matches(self, snapshot):
        if snapshot.sensitive or (self.focused is not None and snapshot.focused != self.focused):
            return False
        if self.control_id is None:
            return True
        control = snapshot.control(self.control_id)
        return (control is not None and not control.sensitive and
                (self.text is None or (control.showing and control.text == self.text)) and
                (self.showing is None or control.showing == self.showing))


@dataclass(frozen=True)
class DesktopAction:
    operation: Operation
    window: WindowRef
    expected: UIState | None = None
    control_id: str | None = None
    text: str | None = None
    action_name: str | None = None
    shortcut: str | None = None
    timeout: float = 3.0

    def __post_init__(self):
        import math
        if type(self.operation) is not Operation or type(self.window) is not WindowRef:
            raise ValueError('Typed action and window required.')
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 10:
            raise ValueError('Invalid timeout.')
        if self.expected is not None and type(self.expected) is not UIState:
            raise ValueError('Typed postcondition required.')
        if self.operation is not Operation.OBSERVE and self.expected is None:
            raise ValueError('Verification required.')
        if self.operation in {Operation.ACTIVATE, Operation.TYPE}:
            identifier(self.control_id)
        elif self.control_id is not None:
            raise ValueError('Unexpected control.')
        if self.operation is Operation.TYPE:
            safe_text(self.text)
            if not self.text:
                raise ValueError('Empty input is not approved text entry.')
        elif self.text is not None:
            raise ValueError('Unexpected text.')
        if self.operation is Operation.ACTIVATE:
            identifier(self.action_name)
        elif self.action_name is not None:
            raise ValueError('Unexpected action name.')
        if self.operation is Operation.SHORTCUT:
            if self.shortcut not in SHORTCUTS:
                raise ValueError('Unapproved shortcut.')
        elif self.shortcut is not None:
            raise ValueError('Unexpected shortcut.')

    def arguments(self, revision=None):
        from dataclasses import asdict
        return {**asdict(self), 'operation': self.operation.value, 'revision': revision}

    @classmethod
    def from_arguments(cls, args):
        fields = {'operation', 'window', 'expected', 'control_id', 'text', 'action_name', 'shortcut', 'timeout', 'revision'}
        if set(args) != fields:
            raise ValueError('Unexpected action fields.')
        data = dict(args)
        revision = data.pop('revision')
        if revision is not None:
            identifier(revision)
        data['operation'] = Operation(data['operation'])
        data['window'] = WindowRef(**data['window'])
        data['expected'] = UIState(**data['expected']) if data['expected'] is not None else None
        return cls(**data), revision
