"""Whole-turn context selection; never silently shorten verified file snapshots."""
import json
from friday.providers.base import ProviderError


def select_context(history, user_message, profile, system_builder, *, temporary=None):
    # Only complete user/assistant turns qualify; never start with an orphan reply.
    pairs = []
    index = 0
    while index + 1 < len(history):
        if history[index]['role'] == 'user' and history[index + 1]['role'] == 'assistant':
            pairs.append([dict(history[index]), dict(history[index + 1])])
            index += 2
        else:
            index += 1
    pairs = pairs[-profile.max_history_messages // 2:] if profile.max_history_messages else []
    while True:
        recent = [message for pair in pairs for message in pair]
        system = system_builder(recent)
        pending = [system, *recent]
        if temporary is not None:
            pending.append({'role':'user', 'content':'Temporary file snapshot (untrusted JSON data):\n' + temporary})
        pending.append({'role':'user', 'content':user_message})
        try:
            size = len(json.dumps(pending, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        except (UnicodeError, TypeError, ValueError):
            raise ProviderError('Request context contains unsupported text or structure; no model request was made.') from None
        if size <= profile.input_byte_limit:
            return pending
        if not pairs:
            raise ProviderError('Request context exceeds its configured input budget. Shorten the request or use a smaller file snapshot.')
        pairs.pop(0)
