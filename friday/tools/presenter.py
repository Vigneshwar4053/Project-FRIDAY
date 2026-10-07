"""Deterministic bounded presentation; never send live tool results to a model."""
import json
from friday.tools.models import ToolStatus

MAX_PRESENTED_CHARACTERS = 12000
MAX_LISTED_ENTRIES = 100


def safe_text(text):
    # Escape terminal control sequences and Unicode format/control characters.
    return ''.join(character if character.isprintable() or character in '\n\t'
                   else json.dumps(character)[1:-1] for character in text)


def _bytes(value):
    return 'unavailable' if value is None else f'{value / (1024 ** 3):.2f} GiB ({value} bytes)'


class ToolPresenter:
    def format(self, result):
        prefix = f'[Tool: {result.tool_name}]\n'
        if result.status is not ToolStatus.SUCCESS:
            return prefix + f'{result.status.name}: Request could not be completed; no model fallback was used.'
        data = result.data
        name = result.tool_name
        if name == 'memory_info':
            body = '\n'.join(f'{label}: {_bytes(data[key])}' for label, key in
                             [('Total', 'total'), ('Available', 'available'), ('Used', 'used'),
                              ('Swap total', 'swap_total'), ('Swap free', 'swap_free')])
        elif name == 'list_directory':
            entries = data['entries'][:MAX_LISTED_ENTRIES]
            body = 'Project entries:\n' + '\n'.join(f'{entry["name"]} ({entry["type"]})' for entry in entries)
            if len(data['entries']) > len(entries):
                body += '\n[Additional entries omitted]'
        elif name == 'read_file':
            body = data['content'][:MAX_PRESENTED_CHARACTERS]
            if len(data['content']) > MAX_PRESENTED_CHARACTERS:
                body += '\n[File display truncated]'
        elif name == 'disk_usage':
            body = '\n'.join(f'{key.title()}: {_bytes(data[key])}' for key in ('total', 'used', 'free'))
        elif name == 'calculate':
            body = f'{data["operation"]}: {json.dumps(data["result"] if not isinstance(data["result"], tuple) else list(data["result"]))}\nInput count: {data["input_count"]}'
        else:
            body = '\n'.join(f'{key}: {value}' for key, value in data.items())
        body = safe_text(body)
        if len(body) > MAX_PRESENTED_CHARACTERS:
            body = body[:MAX_PRESENTED_CHARACTERS] + '\n[Display truncated]'
        return prefix + body
