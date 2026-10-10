"""Local Ollama HTTP adapter, using only the standard library."""
from contextlib import contextmanager
import json
import re
import socket
import urllib.error
import urllib.request

from friday.providers.base import ModelProvider, ProviderError
from friday.models.profile import InferenceProfile


# Conservative fail-closed detection of common unmarked deliberation prefixes.
# This is a fallback, not a general classifier of arbitrary natural language.
_REASONING_PREFIX = re.compile(
    r"^(?:(?:okay|ok|alright)[,.!:]?\s*)?(?:"
    r"the user (?:is asking|asks|wants|asked)|let me think\b|"
    r"(?:i need|i should|i must) to (?:answer|respond|figure|determine)|"
    r"we need to (?:answer|respond|figure|determine))", re.IGNORECASE)

_THINK_TAG = re.compile(r"<\s*(/?)\s*think\s*>", re.IGNORECASE)


def _final_content(content: str) -> str:
    """Remove marked reasoning; discard ambiguous prefixes and unclosed blocks.

    Structured message.content is the primary answer source. This fallback
    handles models that embed thinking tags in that field instead. An orphan
    closing tag means everything preceding it may be reasoning. An unclosed
    opening tag means everything following it must remain hidden.
    """
    answer: list[str] = []
    depth = 0
    position = 0
    for tag in _THINK_TAG.finditer(content):
        if depth == 0:
            answer.append(content[position:tag.start()])
        if tag.group(1):
            if depth:
                depth -= 1
            else:
                answer.clear()
        else:
            depth += 1
        position = tag.end()
    if depth == 0:
        answer.append(content[position:])
    return "".join(answer).strip()


class OllamaProvider(ModelProvider):
    supports_inference_profiles = True
    def __init__(self, base_url: str, model: str, *, timeout: float = 300,
                 think: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think = think
        self._intent_mode = False
        self._profile = None
        self.last_generation_metrics = None

    @contextmanager
    def inference_profile(self, profile):
        if not isinstance(profile, InferenceProfile):
            raise ProviderError('Invalid inference profile.')
        previous = self._profile
        self._profile = profile
        try:
            yield
        finally:
            self._profile = previous

    @contextmanager
    def intent_mode(self):
        previous = self._intent_mode
        self._intent_mode = True
        try:
            yield
        finally:
            self._intent_mode = previous

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.last_generation_metrics = None
        payload = {"model": self.model, "messages": messages,
                   "stream": False, "think": self.think}
        if self._profile is not None:
            payload["options"] = self._profile.options
            payload["think"] = self._profile.think
        if self._intent_mode:
            options = ({**self._profile.options, 'temperature': 0}
                       if self._profile is not None else {'num_predict': 512})
            payload.update(format='json', think=False, options=options)
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=(self._profile.timeout_seconds if self._profile is not None else self.timeout)) as response:
                limit = 65536 if self._intent_mode else 262144 if self._profile is not None else None
                body = response.read(limit + 1) if limit is not None else response.read()
                if self._intent_mode and len(body) > 65536:
                    raise ProviderError("Intent response exceeded its transport limit.")
                if limit is not None and len(body) > limit:
                    raise ProviderError("Model response exceeded its transport budget.")
                result = json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404:
                message = f"Ollama model {self.model!r} or chat endpoint was not found. Check the model with ollama list."
            else:
                message = f"Ollama returned HTTP {exc.code}. Check the service and model configuration."
            raise ProviderError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderError("Ollama timed out. CPU generation can be slow; try again.") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.base_url}. Check that ollama serve is running."
            ) from exc
        except OSError as exc:
            raise ProviderError("Ollama connection failed while reading the response.") from exc
        except (ValueError, UnicodeError) as exc:
            raise ProviderError("Ollama returned an invalid JSON response.") from exc

        if not isinstance(result, dict):
            raise ProviderError("Ollama returned an invalid chat response.")
        if "error" in result:
            raise ProviderError("Ollama reported a generation error. Check its service logs.")
        # A token-limit stop is not a verified complete answer, even when some
        # apparently final text precedes it. Never retry or save partial output.
        reason = result.get("done_reason")
        message = result.get("message")
        def counter(name):
            value = result.get(name)
            return value if type(value) is int and 0 <= value <= 2**63 - 1 else None
        tokens, duration = counter('eval_count'), counter('eval_duration')
        # Scalar-only opt-in benchmark data; no response text, paths or prompts.
        self.last_generation_metrics = {
            'completion': ('truncated' if reason == 'length' else
                           'normal' if reason == 'stop' else 'unspecified'),
            'prompt_tokens': counter('prompt_eval_count'), 'output_tokens': tokens,
            'generation_ns': duration, 'load_ns': counter('load_duration'),
            'prompt_eval_ns': counter('prompt_eval_duration'),
            'tokens_per_second': tokens * 1e9 / duration if tokens is not None and duration else None,
            'thinking_present': isinstance(message, dict) and bool(message.get('thinking')),
            'final_answer_present': (isinstance(message, dict) and isinstance(message.get('content'), str)
                                     and bool(_final_content(message['content']))
                                     and not bool(_REASONING_PREFIX.match(_final_content(message['content'])))),
        }
        if reason == "length":
            raise ProviderError("Ollama reached the output-token limit without a complete final answer. "
                                "Use a shorter request or review the inference profile budget.")
        if ("done" in result and result["done"] is not True) or (
                reason not in (None, "", "stop")):
            raise ProviderError("Ollama did not produce a completed final answer.")
        message = result.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError("Ollama returned an invalid final answer.")
        # Intent wrappers and extra text must be rejected, not repaired into calls.
        content = content.strip() if self._intent_mode else _final_content(content)
        if not self._intent_mode and _REASONING_PREFIX.match(content):
            raise ProviderError("Ollama returned reasoning instead of a valid final answer. "
                                "Check model compatibility with the configured thinking control.")
        if not content:
            raise ProviderError("Ollama returned no final answer. Check model support for think=false.")
        # Never expose message.thinking. Ordinary chat hides marked reasoning;
        # intent content goes only to the strict validator before display/execution.
        return content
