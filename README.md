# FRIDAY Core v0.1

FRIDAY is Vigneshwar's personal local-first terminal AI assistant. It uses
Ollama and qwen3:4b for practical help with programming, Linux, AI, authorized
cybersecurity, research, planning, and automation advice.

## Capabilities and limits

- Terminal chat with in-memory session history and a consistent identity.
- Local HTTP model provider, connection/response error handling, and clean exits.
- Thinking disabled through Ollama's `think: false` API option; only final
  `message.content` is displayed, never the separate thinking field.
- No tool execution, persistent memory, cloud APIs, or extra Python dependencies.
  Suggested commands must be run by the user. History disappears on exit and
  grows during a session; long sessions can exceed the model's context window.

## Requirements and usage

Ubuntu, Python 3.14 (verified with 3.14.4), an existing `.venv`, and Ollama
with `qwen3:4b` installed. Use an Ollama version supporting the `think` option.
Run from the repository root:

```bash
cd ~/Projects/FRIDAY
source .venv/bin/activate
# If Ollama is not already running, in another terminal:
ollama serve
# Check installed models:
ollama list
# Start FRIDAY (activation is optional for this exact command):
.venv/bin/python -m friday.main
```

Enter `exit`, `quit`, `/bye`, Ctrl+C, or Ctrl+D to close. CPU generation can take
more than a minute; the default request timeout is 300 seconds. Configuration
(name, user, model, URL, timeout, thinking) lives in `friday/config/settings.py`.
No packages need installing for this milestone.

## Tests

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

Tests use mocked HTTP responses and providers; they do not require running
Ollama or perform model inference.

## Architecture

```text
friday/
  __init__.py
  main.py                 # terminal I/O and composition
  config/settings.py      # centralized configuration and identity
  core/assistant.py       # conversation and successful-turn history
  providers/base.py       # abstract ModelProvider and ProviderError
  providers/ollama.py     # standard-library HTTP adapter
  # config/, core/, providers/ each contain __init__.py
tests/                    # unittest coverage
data/.gitkeep             # reserved runtime data directory
logs/.gitkeep             # reserved log directory
```

The core depends on the provider interface rather than Ollama. Future milestones
may add SQLite memory, ChromaDB retrieval, a scheduler, typed tools and permissions,
coding/cybersecurity agents, research/Gemini providers, Whisper, Piper, a React UI,
and plugins. None are implemented in v0.1.
