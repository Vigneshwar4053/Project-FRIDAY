"""Local Ollama HTTP adapter, using only the standard library."""
import json
import re
import socket
import urllib.error
import urllib.request

from friday.providers.base import ModelProvider, ProviderError


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
    def __init__(self, base_url: str, model: str, *, timeout: float = 300,
                 think: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think = think

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages,
                   "stream": False, "think": self.think}
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
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
        message = result.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError("Ollama returned an invalid final answer.")
        content = _final_content(content)
        if not content:
            raise ProviderError("Ollama returned no final answer. Check model support for think=false.")
        # Never return message.thinking, raw content, or reasoning-only output.
        return content
