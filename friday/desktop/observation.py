"""Bounded immutable desktop data, never execution or authorization."""
from dataclasses import dataclass
from enum import StrEnum
import re

APPLICATION_IDS = frozenset({'firefox', 'vscode', 'files'})
METADATA_ONLY = 'METADATA_ONLY'
METADATA_ROLES = frozenset({'frame', 'window', 'tool_bar', 'menu_bar', 'menu', 'popup_menu',
    'push_button', 'toggle_button', 'check_box', 'radio_button', 'menu_item',
    'check_menu_item', 'radio_menu_item', 'entry', 'label', 'status_bar'})
ROLES = METADATA_ROLES | frozenset({'button', 'text', 'dialog', 'document', 'other'})


def identifier(value):
    if type(value) is not str or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value):
        raise ValueError('Invalid opaque identifier.')
    return value


def safe_text(value, limit=2048):
    if (type(value) is not str or len(value.encode('utf-8')) > limit or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid bounded single-line text.')
    return value


@dataclass(frozen=True)
class WindowRef:
    application_id: str
    window_id: str
    identity: str

    def __post_init__(self):
        if self.application_id not in APPLICATION_IDS:
            raise ValueError('Unsupported application.')
        identifier(self.window_id)
        identifier(self.identity)


@dataclass(frozen=True)
class UIElement:
    control_id: str
    role: str
    label: str = ''
    text: str | None = None
    enabled: bool = True
    showing: bool = True
    editable: bool = False
    sensitive: bool = False
    actions: tuple[str, ...] = ()
    effect: str = 'unknown'
    focusable: bool = False

    def __post_init__(self):
        identifier(self.control_id)
        if self.role not in ROLES:
            raise ValueError('Unsupported role.')
        safe_text(self.label, 256)
        if self.text is not None:
            safe_text(self.text)
        if any(type(v) is not bool for v in
               (self.enabled, self.showing, self.editable, self.sensitive, self.focusable)):
            raise ValueError('Invalid UI state.')
        if type(self.actions) is not tuple or len(self.actions) > 8:
            raise ValueError('Invalid action list.')
        for value in self.actions:
            identifier(value)
        if self.effect not in {'unknown', 'local', 'navigation', 'submission', 'editing', 'credential', 'security'}:
            raise ValueError('Invalid control effect.')
        if self.sensitive and (self.text is not None or self.label):
            raise ValueError('Sensitive controls cannot contain observed text.')


@dataclass(frozen=True)
class WindowSnapshot:
    window: WindowRef
    revision: str
    focused: bool
    elements: tuple[UIElement, ...]
    sensitive: bool = False

    def __post_init__(self):
        if type(self.window) is not WindowRef:
            raise ValueError('Typed window required.')
        identifier(self.revision)
        if type(self.focused) is not bool or type(self.sensitive) is not bool:
            raise ValueError('Invalid window state.')
        if type(self.elements) is not tuple or len(self.elements) > 200:
            raise ValueError('Observation bound exceeded.')
        if any(type(e) is not UIElement for e in self.elements):
            raise ValueError('Typed controls required.')
        if len({e.control_id for e in self.elements}) != len(self.elements):
            raise ValueError('Duplicate control identity.')
        from dataclasses import asdict
        import json
        if len(json.dumps(asdict(self), ensure_ascii=True).encode('utf-8')) > 65536:
            raise ValueError('Serialized observation bound exceeded.')

    def control(self, control_id):
        return next((e for e in self.elements if e.control_id == control_id), None)

    def to_data(self):
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_data(cls, value):
        if set(value) != {'window', 'revision', 'focused', 'elements', 'sensitive'}:
            raise ValueError('Invalid observation fields.')
        return cls(WindowRef(**value['window']), value['revision'], value['focused'],
                   tuple(UIElement(**{**dict(e), 'actions': tuple(e['actions'])})
                         for e in value['elements']), value['sensitive'])


class DesktopStatus(StrEnum):
    VERIFIED = 'verified'
    UNSUPPORTED = 'unsupported'
    TARGET_CHANGED = 'target_changed'
    TIMEOUT = 'timeout'
    CANCELLED = 'cancelled'
    UNVERIFIED = 'invoked_unverified'
    FAILED = 'failed'
