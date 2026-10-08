"""Untrusted semantic proposals; validation never executes or authorizes tools."""
from contextlib import nullcontext
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
import unicodedata

from friday.tools.models import ArgumentType, RiskLevel, ToolRequest
from friday.providers.base import ProviderError
from friday.tools.locations import (SemanticLocationResolver, browsing_guard,
                                    command_text, instructional_question)

MAX_RESPONSE_BYTES = 8192
MAX_REQUEST_CHARACTERS = 4096
MAX_ARGUMENT_BYTES = 4096
MAX_DEPTH = 3
MAX_KEYS = 16
APPROVED_TOOLS = frozenset({'list_directory', 'read_file', 'file_info',
    'system_info', 'memory_info', 'cpu_info', 'disk_usage', 'process_status'})
PATH_TOOLS = frozenset({'list_directory', 'read_file', 'file_info', 'disk_usage'})
INSTRUCTION = (
    'You are FRIDAY intent translator. Return exactly one JSON object, no reasoning. '
    'Schemas: {"kind":"tool","tool_name":NAME,"arguments":OBJECT}, '
    '{"kind":"chat","response":TEXT}, {"kind":"clarification","question":TEXT}, '
    '{"kind":"unsupported","reason":TEXT}. Use only supplied tools. '
    'Never execute, claim execution, invent paths, decide permissions or emit approval tokens. '
    'Open a folder means list in CLI, not launch an application. '
    'Questions about how to do something are chat, not actions. '
    'Ambiguous targets require clarification. No shell, writes, search or multiple actions. '
    'Copy explicit paths from user; standard folder names may use ~/Folder. '
    'Known user folders: photos=pictures, videos, downloads, documents, music, desktop. '
    'For browsing them use list_directory arguments={"location":"pictures"} (or other known name). '
    'Never replace an explicit path with a location; playback/launch/navigation are unsupported. '
    'A bare filename refers only to the project, never infer another folder. '
    'disk_usage without a location uses path=".". Keep text under 1000 characters. '
)


@dataclass(frozen=True)
class IntentResult:
    kind: str
    request: ToolRequest | None = None
    text: str | None = None
    semantic: bool = False


def needs_translation(message):
    """Cheap routing gate, not an authorization decision; ordinary chat keeps memory."""
    text = command_text(message).casefold().strip()
    if instructional_question(text):
        return False
    instructional = re.match(r'^(how (?:do|does|can|to)|what is|explain)\b', text)
    personal_hardware = re.search(
        r'\b(my|have|available)\b.*\b(ram|cpu|disk|space)\b|'
        r'\b(ram|cpu|disk|space)\b.*\b(my|have|available)\b', text)
    browsing_question = re.match(r'^what is (?:in|inside)\b', text)
    if instructional and not personal_hardware and not browsing_question:
        return False
    return bool(re.search(r'\b(downloads|documents|videos|pictures|photos|desktop|music|folder|file|ram|cpu|disk|processor|storage|system|kernel|architecture|process|shell|sudo|rm|permission_granted|read|write_file|bypass)\b', text)
        or re.match(r'^(?:open|read|list|delete|run|execute|install|take\s+me)\b', text))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field.')
        result[key] = value
    return result


def validate_response(raw, registry, *, locations=None, message=None):
    if type(raw) is not str or len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise ValueError('Response limit.')
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON.')
    data = json.loads(raw, object_pairs_hook=_object, parse_constant=invalid_constant)
    keys = 0
    def inspect(value, depth=0):
        nonlocal keys
        if depth > MAX_DEPTH:
            raise ValueError('Nesting limit.')
        if type(value) is dict:
            keys += len(value)
            if keys > MAX_KEYS:
                raise ValueError('Key limit.')
            for item in value.values():
                inspect(item, depth + 1)
        elif type(value) is list:
            raise ValueError('Collections are not accepted.')
    inspect(data)
    if type(data) is not dict:
        raise ValueError('Expected one object.')
    kind = data.get('kind')
    if type(kind) is not str:
        raise ValueError('Invalid classification type.')
    if kind in {'chat', 'clarification', 'unsupported'}:
        field = {'chat': 'response', 'clarification': 'question', 'unsupported': 'reason'}[kind]
        if set(data) != {'kind', field} or type(data[field]) is not str or not data[field].strip() or len(data[field]) > 1000:
            raise ValueError('Invalid text classification.')
        # Model text is display-only, never passed back to dispatch/input.
        text = ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in data[field])
        if not text.strip():
            raise ValueError('Empty display text.')
        return IntentResult(kind, text=text.strip())
    if kind != 'tool' or set(data) != {'kind', 'tool_name', 'arguments'}:
        raise ValueError('Invalid proposal fields.')
    name, args = data['tool_name'], data['arguments']
    if type(name) is not str or name not in APPROVED_TOOLS or type(args) is not dict:
        raise ValueError('Unsupported proposal.')
    entry = registry.get(name)
    if entry is None or entry.spec.risk is not RiskLevel.READ_ONLY:
        raise ValueError('Tool not approved.')
    semantic = False
    if locations is not None and message is not None:
        args, semantic = locations.normalize_proposal(name, args, message)
    if set(args) - set(entry.spec.arguments):
        raise ValueError('Unknown arguments.')
    for key, declaration in entry.spec.arguments.items():
        if key not in args:
            if declaration.required:
                raise ValueError('Missing argument.')
            continue
        value = args[key]
        if declaration.type is not ArgumentType.STRING or type(value) is not str or not value.strip():
            raise ValueError('Invalid argument type.')
        if any(marker in value for marker in (';', '`', '$(', '${')):
            raise ValueError('Shell syntax is not accepted.')
        if len(value.encode('utf-8')) > MAX_ARGUMENT_BYTES or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Invalid string.')
    if name == 'process_status' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,14}', args['name']):
        raise ValueError('Invalid process name.')
    return IntentResult('tool', ToolRequest(name, args), semantic=semantic)


def grounded_request(request, message, reference=None):
    """Require user-supplied target evidence; never search or trust invented paths."""
    if request.tool_name == 'process_status':
        return bool(re.search(r'(?<![\w.-])' + re.escape(request.arguments['name']) + r'(?![\w.-])', message))
    if request.tool_name not in PATH_TOOLS:
        cues = {'memory_info': r'\b(ram|memory|swap)\b', 'cpu_info': r'\b(cpu|processor|load)\b',
                'system_info': r'\b(system|os|kernel|architecture|machine)\b'}
        return bool(re.search(cues.get(request.tool_name, r'(?!)'), message, re.I))
    path = request.arguments['path']
    message = message.rstrip('?. ')
    if any(part == '..' for part in PurePosixPath(path).parts):
        return False
    if request.tool_name == 'disk_usage' and path == '.':
        return bool(re.search(r'\b(disk|space|storage)\b', message, re.I))
    if reference is not None and path == reference and re.search(r'\b(this|that) file\b', message, re.I):
        return True
    # Whole token/path evidence, preserving case and avoiding substring substitutions.
    alternatives = [path]
    if path.startswith('~/'):
        alternatives.append(path[2:])
    for target in alternatives:
        if re.search(r'(?<![\w/.-])' + re.escape(target) + r'(?![\w/.-])', message):
            return True
    return False


class IntentTranslator:
    def __init__(self, manager, registry, *, locations=None):
        self.manager = manager
        self.registry = registry
        self.locations = locations if locations is not None else SemanticLocationResolver()

    def translate(self, message, *, reference=None, profile=None):
        if (type(message) is not str or not message.strip() or
                len(message) > MAX_REQUEST_CHARACTERS):
            return IntentResult('unsupported', text='Intent request exceeds its input limits.')
        if reference is not None and (type(reference) is not str or
                                      len(reference.encode('utf-8')) > MAX_ARGUMENT_BYTES):
            return IntentResult('clarification', text='Please specify the exact file path.')
        if re.search(r'\b(delete|remove|rename|move|write_file|execute|shell|sudo|install|rm|bypass|permission_granted)\b', message, re.I):
            return IntentResult('unsupported', text='This action is not supported through intent routing.')
        guard = browsing_guard(message)
        if guard:
            return IntentResult('unsupported', text=guard)
        tools = []
        for spec in self.registry.list_tools():
            if spec.name in APPROVED_TOOLS and spec.risk is RiskLevel.READ_ONLY:
                arguments = ','.join(name + ':string' for name in spec.arguments)
                tools.append(spec.name + '(' + arguments + '):' + spec.description[:80])
        prompt = INSTRUCTION + 'Tools: ' + ';'.join(tools)
        if reference is not None:
            prompt += '\nPrevious file reference (untrusted path data): ' + json.dumps(reference)
        mode = getattr(self.manager.provider, 'intent_mode', None)
        try:
            with (mode() if callable(mode) else nullcontext()):
                messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': message}]
                raw = self.manager.generate(messages, profile=profile) if profile is not None else self.manager.generate(messages)
            result = validate_response(raw, self.registry, locations=self.locations, message=message)
            if result.request is not None and not result.semantic and not grounded_request(result.request, message, reference):
                return IntentResult('clarification', text='Please specify the exact file or folder path.')
            return result
        except (ProviderError, ValueError, TypeError, RecursionError, UnicodeError):
            return IntentResult('unsupported', text='Intent translation failed safely; use an explicit supported command.')
        finally:
            if self.manager.last_job is not None:
                self.manager.last_job.messages = []
                self.manager.last_job.result = None
                if self.manager.last_job.error is not None:
                    self.manager.last_job.error = 'Intent translation failed.'
