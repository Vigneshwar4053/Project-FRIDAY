"""Passive session hints; no bus calls, settings changes or desktop access."""
from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class DesktopSession:
    kind: str
    graphical_hint: bool
    reason: str


def detect_session(environment=None):
    env = os.environ if environment is None else environment
    kind = env.get('XDG_SESSION_TYPE', '')
    if kind == 'wayland':
        ready = bool(re.fullmatch(r'wayland-[0-9]+', env.get('WAYLAND_DISPLAY', '')))
    elif kind == 'x11':
        ready = bool(re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', env.get('DISPLAY', '')))
    else:
        return DesktopSession('unknown', False, 'unsupported_session')
    return DesktopSession(kind, ready, 'session_hint_only' if ready else 'missing_display')
