"""Trusted response provenance for presentation; model text cannot set it."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import re

from friday.tools.sensitive import SensitivePaths


class ResponseCategory(Enum):
    GREETING = 'greeting'
    CONVERSATION = 'conversation'
    PRIVATE = 'private_or_untrusted'
    TOOL = 'tool'
    ERROR = 'error'
    UNKNOWN = 'unknown'


class ResponseProvenance(Enum):
    LOCAL_GREETING = 'trusted_local_greeting'
    PUBLIC_MODEL_CONTEXT = 'public_conversation_context'
    PRIVATE_CONTEXT = 'private_or_unknown_context'
    TOOL_RUNTIME = 'tool_runtime'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ResponseMetadata:
    category: ResponseCategory = ResponseCategory.UNKNOWN
    provenance: ResponseProvenance = ResponseProvenance.UNKNOWN

    @property
    def speech_eligible(self):
        return ((self.category is ResponseCategory.GREETING and
                 self.provenance is ResponseProvenance.LOCAL_GREETING) or
                (self.category is ResponseCategory.CONVERSATION and
                 self.provenance is ResponseProvenance.PUBLIC_MODEL_CONTEXT))


# Positive public-topic catalog and whole-request grammar, rather than guessing
# that arbitrary pasted text/personal requests are public. Unknown requests are
# still answered normally in text. This can be extended through reviewed code.
PUBLIC_TOPICS = frozenset({
    'python', 'a python decorator', 'python decorators', 'programming', 'software engineering',
    'machine learning', 'artificial intelligence', 'ai', 'deep learning', 'neural networks',
    'linux', 'ubuntu', 'operating systems', 'computer science', 'algorithms', 'data structures',
    'recursion', 'object oriented programming', 'object-oriented programming', 'functions',
    'classes', 'databases', 'sql', 'git', 'version control', 'testing', 'unit testing',
    'javascript', 'typescript', 'java', 'c', 'c++', 'rust', 'go', 'html', 'css',
    'networking', 'the internet', 'http', 'https', 'dns', 'tcp', 'ip', 'cybersecurity',
    'cryptography', 'encryption', 'passwords', 'a password', 'authentication', 'authorization',
    'security architecture', 'mathematics', 'math', 'statistics', 'probability',
    'calculus', 'linear algebra', 'physics', 'chemistry', 'biology', 'photosynthesis',
    'history', 'geography', 'astronomy', 'the solar system', 'gravity', 'electricity',
})
PUBLIC_SMALL_TALK = frozenset({
    'hello', 'hi', 'hello friday', 'hi friday', 'good morning', 'good evening',
    'thanks', 'thank you', 'goodbye', 'who are you', 'what can you do', 'how are you',
    'tell me a joke', 'tell me a fun fact',
})
PUBLIC_FOLLOWUPS = frozenset({'tell me more', 'give an example', 'give me an example',
    'explain more', 'can you explain more', 'make it simpler'})


def public_conversation_request(text, *, has_public_context=False):
    if type(text) is not str or len(text) > 256:
        return False
    normalized = ' '.join(text.casefold().strip().rstrip('.!?').split())
    if normalized in PUBLIC_SMALL_TALK:
        return True
    if normalized in PUBLIC_FOLLOWUPS:
        return has_public_context
    match = re.fullmatch(r'(?:please )?(?:what is|what are|explain|tell me about|'
                         r'teach me about|describe|think deeply about) (.+)', normalized)
    return match is not None and match[1] in PUBLIC_TOPICS


def message_fingerprint(message):
    return message['role'], hashlib.sha256(message['content'].encode('utf-8')).digest()


def speech_text_has_sensitive_structure(text):
    """Defense in depth after provenance checks; not a privacy classifier."""
    if type(text) is not str:
        return True
    return (SensitivePaths.excluded_content(text.encode('utf-8')) or
            re.search(r'\b(?:password|api[_ -]?key|client[_ -]?secret|access[_ -]?token)'
                      r'\s*[:=]\s*\S+', text, re.I) is not None)
