"""Bounded deterministic intent recognition; decisions are data, not execution."""
from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from types import MappingProxyType

from friday.tools.computation import MAX_VALUES
from friday.tools.models import JSONValue

MAX_ROUTED_MESSAGE_LENGTH = 4096
MAX_NUMBER_TOKEN_LENGTH = 32
ROUTABLE_TOOLS = frozenset({'memory_info', 'system_info', 'cpu_info', 'list_directory',
                            'read_file', 'disk_usage', 'process_status', 'calculate'})
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')


@dataclass(frozen=True)
class RouteDecision:
    matched: bool
    tool_name: str | None = None
    arguments: Mapping[str, JSONValue] = field(default_factory=lambda: MappingProxyType({}))
    message: str | None = None
    permission_command: str | None = None

    def __post_init__(self):
        if self.tool_name is not None and self.tool_name not in ROUTABLE_TOOLS:
            raise ValueError('Tool is not routable.')
        if self.permission_command not in {None, 'show', 'revoke', 'authorize'}:
            raise ValueError('Unsupported filesystem permission command.')
        # Router builds only bounded scalar arguments or immutable numeric tuples.
        object.__setattr__(self, 'arguments', MappingProxyType(dict(self.arguments)))


class ToolRouter:
    def __init__(self, project_root):
        self.project_root = str(Path(project_root).resolve(strict=True))

    def route(self, message):
        if len(message) > MAX_ROUTED_MESSAGE_LENGTH:
            return RouteDecision(True, message='Request is too long; maximum is 4096 characters.')
        text = message.strip().rstrip('?').strip()
        normalized = ' '.join(text.lower().split())
        if normalized in {'show authorized folders', 'list authorized folders'}:
            return RouteDecision(True, permission_command='show')
        permission = re.fullmatch(r'(revoke\s+access\s+to|always\s+allow)\s+(.+)', text,
                                  re.IGNORECASE | re.DOTALL)
        if permission:
            return RouteDecision(True, arguments={'path': permission.group(2)},
                                 permission_command='revoke' if permission.group(1).split()[0].lower() == 'revoke' else 'authorize')
        if normalized in {'revoke access to', 'always allow'}:
            return RouteDecision(True, permission_command='revoke' if normalized.startswith('revoke') else 'authorize')
        routes = {
            'memory_info': {'check my ram', 'show memory usage', 'how much ram is available', 'check swap'},
            'system_info': {'system info', 'what os am i running', 'show kernel information', 'what architecture is this machine'},
            'cpu_info': {'check cpu', 'show cpu information', 'what processor am i using', 'system load'},
            'list_directory': {'what files are in this project', 'list project files', 'show files in the project'},
            'disk_usage': {'check disk space', 'how much disk space is available', 'disk usage for this project'},
        }
        for name, phrases in routes.items():
            if normalized in phrases:
                args = {'path': self.project_root} if name in {'list_directory', 'disk_usage'} else {}
                return RouteDecision(True, name, args)
        if re.match(r'^(?:run|call|execute)\s+tool\b', normalized):
            return RouteDecision(True, message='Generic tool dispatch is not supported; writes are not enabled through chat.')
        listing = re.fullmatch(
            r'(?:list(?:\s+files(?:\s+in)?)?|show\s+files\s+in|what\s+files\s+are\s+in)\s+(.+)',
            text, re.IGNORECASE | re.DOTALL)
        if listing:
            return RouteDecision(True, 'list_directory', {'path': listing.group(1)})
        write = re.fullmatch(r'(?:write|overwrite|create|save|modify|edit|delete|rename)\s+(.+)', normalized)
        if write and ('file' in write.group(1).split() or
                      any('.' in token or '/' in token for token in write.group(1).split())):
            return RouteDecision(True, message='File changes require approval and are not enabled through chat.')
        match = re.fullmatch(r'(?:is ([A-Za-z0-9][A-Za-z0-9_.-]{0,14}) running|check ([A-Za-z0-9][A-Za-z0-9_.-]{0,14}) process)', text, re.IGNORECASE)
        if match:
            return RouteDecision(True, 'process_status', {'name': match.group(1) or match.group(2)})
        match = re.fullmatch(r'(read|show|open)\s+(.+)', text, re.IGNORECASE | re.DOTALL)
        if match:
            path = match.group(2)
            if '.' in path or '/' in path or (match.group(1).lower() == 'read' and not any(c.isspace() for c in path)):
                return RouteDecision(True, 'read_file', {'path': path})
        percent = re.fullmatch(r'what is (\S+) percent of (\S+)', text, re.IGNORECASE)
        calculation = re.fullmatch(r'(?:calculate\s+)?(?:the\s+)?(add|subtract|multiply|divide|power|sum|mean|median|min|max|count|sort|percentage)(?:\s+of)?\s+(.+)', text, re.IGNORECASE)
        if percent or calculation:
            operation = calculation.group(1).lower() if calculation else 'percentage'
            payload = ','.join(percent.groups()) if percent else calculation.group(2)
            tokens = payload.split(',')
            if len(tokens) > MAX_VALUES:
                return RouteDecision(True, message='Too many calculation values.')
            values = []
            for token in tokens:
                token = token.strip()
                if len(token) > MAX_NUMBER_TOKEN_LENGTH:
                    return RouteDecision(True, message='Calculation numeric token is too long.')
                if not _NUMBER.fullmatch(token):
                    if (token.lower() in {'nan', 'inf', 'infinity', '-inf', '+inf'} or
                            any(marker in payload for marker in ('__', '(', ')', '$', ';', '"', "'"))):
                        return RouteDecision(True, message='Calculation requires finite numbers; source code is not accepted.')
                    # Ordinary ambiguous prose is not a guessed calculation.
                    return RouteDecision(False)
                value = float(token)
                if not math.isfinite(value):
                    return RouteDecision(True, message='Calculation requires finite numbers.')
                values.append(value)
            return RouteDecision(True, 'calculate', {'operation': operation, 'values': tuple(values)})
        if normalized.startswith('calculate '):
            return RouteDecision(True, message='Unsupported calculation syntax; use an operation and comma-separated numbers.')
        return RouteDecision(False)
