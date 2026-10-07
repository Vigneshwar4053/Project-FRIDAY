# FRIDAY v0.3 Phase 2 — Native Model Synchronization

FRIDAY is Vigneshwar's personal local-first terminal AI assistant. It uses
Ollama and qwen3:4b for practical help with programming, Linux, AI, authorized
cybersecurity, research, planning, and automation advice.

## Capabilities and limits

- Terminal chat with a consistent identity and SQLite session history.
- Local HTTP model provider, connection/response error handling, and clean exits.
- Requests `think: false` and displays only final answer content. The provider
  also removes embedded thinking blocks when Qwen ignores that option.
- No tool execution, cloud APIs, or extra Python dependencies. Suggested
  commands must be run by the user. Only successful, sanitized conversation
  turns are saved; failed or interrupted generations are not saved.

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
(name, user, model, URL, timeout, thinking, database path, recent-memory limit) lives in `friday/config/settings.py`.
No packages need installing for this milestone.

## Local memory

FRIDAY automatically creates `data/friday.db` in this repository, independent
of the working directory. It contains sessions, successful user/assistant
messages, and categorized key/value memories. Timestamps use UTC. The database
and its journal/WAL sidecars are ignored by Git; `data/.gitkeep` stays tracked.
Conversation text is stored locally in plain text.

Each startup creates a new session and restores up to `recent_memory_limit`
messages (default 20) across earlier sessions, in chronological order. An
orphaned assistant reply at the start of a truncated window is dropped. Model
requests use the same recent-message bound throughout the session, while all
successful turns remain in SQLite. A limit of zero disables restored/model
history but still saves successful turns. A message-count limit does not cap
individual message length or guarantee fitting the model's token context.

Normal exit, Ctrl+C, and Ctrl+D end the current session and close the database.
A force-killed process can leave `ended_at` empty; previously committed turns
remain available on the next startup. A storage failure is reported and the
CLI closes rather than silently continuing without persistence.

`MemoryManager` provides `start_session`, `end_session`, `save_message`, atomic
`save_turn`, `get_recent_messages`, `get_most_recent_session`, `store_memory`
(upsert by category/key), and `get_memory`. Key/value memory is an explicit
Python API; v0.2 does not automatically extract facts or add them to prompts.

To check persistence, tell FRIDAY a short project fact, exit, start it again,
and ask about that fact. Confirm storage separately if the model misrecalls it:

```bash
.venv/bin/python -B - <<'PY'
import sqlite3
from contextlib import closing
from friday.config.settings import settings
with closing(sqlite3.connect(f"file:{settings.database_path}?mode=ro", uri=True)) as db:
    print(db.execute("SELECT id, started_at, ended_at FROM sessions ORDER BY id DESC LIMIT 5").fetchall())
    print(db.execute("SELECT session_id, role, content FROM messages ORDER BY id DESC LIMIT 6").fetchall())
PY
```


## Model runtime

```text
FridayAssistant -> ModelManager -> Synchronization -> ModelProvider -> Ollama
```

`ModelJob` is an in-memory request with a UUID, model name, copied message
snapshot, integer priority, status, result/error, and UTC lifecycle timestamps.
Jobs transition from pending to running, then completed or failed. They are
not saved in SQLite. The manager retains only the last executed job plus jobs
still waiting in its queue; callers may retain job records explicitly.

`ModelJobQueue` is deterministic: **lower numeric values mean higher priority**;
equal priorities run in enqueue order (FIFO). Priority is captured at enqueue
time. `execute_next()` drains in that order; `execute_job(job)` explicitly
executes a supplied pending job immediately and removes it from the queue if
present. The assistant's `generate()` convenience call queues and immediately
executes its own job, leaving unrelated queued jobs waiting.

`ModelRegistry` tracks registered names, a default, a selected (`current_model`)
name, and the last model used for a provider call (`active_model`). The first
registered name becomes default and selected. Changing the default does not
change the selection. Active is runtime metadata, not a claim that Ollama has
loaded a model. Phase 1 binds one provider to one model; requesting a different
model fails explicitly rather than silently using the wrong provider.

The CLI constructs the manager explicitly. The assistant's existing provider
constructor remains compatible by wrapping that provider in a manager.
Provider errors become failed jobs with a finish timestamp; `generate()` raises
`ProviderError` so the CLI keeps its existing error behavior. Unexpected errors
use a generic message. Interrupts mark the job failed before being re-raised.
Only successful final answers proceed to conversation persistence. Ollama HTTP
handling and reasoning sanitization remain in the provider.

## Synchronization (Phase 2)

```text
Python orchestration / FridayAssistant
                  |
             ModelManager
                  |
       Synchronization interface
           /              \
     Native C          Python fallback
         |             threading.Lock
   POSIX ERRORCHECK mutex  |
           \              /
              ModelProvider
                    |
                  Ollama
```

Scheduling, priority, model selection, and the queue remain in Python. C only
protects the model execution resource with a process-local, single-owner binary
gate. It uses a POSIX error-checking mutex: initially unlocked, blocking acquire,
and owner-only release. Unlike a counting semaphore, it cannot accidentally
accumulate permits. It rejects recursive acquisition and release by non-owners.
There is no IPC, shared memory, model logic, or worker creation in C.

Build with the existing Ubuntu C compiler and Make (no Python packages needed):

```bash
make -C native/sync
# Native/fallback synchronization tests:
.venv/bin/python -B -m unittest discover -s tests -p 'test_sync.py' -v
# Complete suite:
.venv/bin/python -B -m unittest discover -s tests -v
```

The build creates `native/sync/libfriday_sync.so` with `-std=c11 -Wall -Wextra
-Wpedantic -fPIC -pthread -shared`. Generated `.so`/`.o` files are ignored by Git.
`friday/sync/native.py` alone handles ctypes and declares every C signature.
Paths are absolute and derived from this project; `sync_library_path` is trusted
local application configuration, never sourced from chat input or the environment.
The opaque pointer stays inside the wrapper and is never stored in SQLite.

At startup the CLI tries native initialization and prints the selected backend.
If the library is missing/incompatible or cannot initialize, it explicitly uses
the Python lock fallback and prints the reason. After native initialization,
acquire/release/destroy failures are reported; they never trigger fallback.
Native-specific tests clearly skip if the library is unavailable. All fallback
and runtime tests remain runnable without building it.

`ModelManager(..., synchronization=gate)` borrows the gate: the caller owns and
closes it. Without injection, the manager creates/owns a Python fallback, closed
by `manager.close()` or its lifecycle context manager. The CLI owns its selected
gate and closes it after the manager and memory/session have shut down. Gate
`with` blocks mean acquire/release, not destruction. Close is idempotent, refuses
holders/waiters, and prevents use after close. Release happens on success,
provider error, unexpected exception, KeyboardInterrupt, and SystemExit.

The provider call alone is protected; SQLite persistence occurs after release.
Production execution is still synchronous with no background threads. Focused
tests share a gate across independent managers and use threads to prove mutual
exclusion. The queue/registry/manager scheduling APIs are **not thread-safe**, and
separate gate instances do not coordinate. Sharing one gate prepares the model
execution boundary for future multi-agent/model-job execution, without adding
those workers in this phase. POSIX waiter order is not guaranteed; Python queue
ordering still controls synchronous scheduling.

## Tests

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

Tests use mocked HTTP responses/providers and temporary SQLite databases.
They never write to `data/friday.db`, require running Ollama, or perform inference.

## Architecture

```text
friday/
  __init__.py
  main.py                 # terminal I/O and composition
  config/settings.py      # centralized configuration and identity
  core/assistant.py       # conversation and successful-turn history
  models/
    __init__.py
    job.py                # in-memory requests and lifecycle states
    queue.py              # priority/FIFO pending jobs
    registry.py           # model names and selection metadata
    manager.py            # synchronous execution via ModelProvider
  sync/
    __init__.py           # native-first selection and explicit fallback
    base.py               # interface, lifecycle, context guard
    native.py             # private ctypes wrapper
    fallback.py           # standard-library lock
  providers/base.py       # abstract ModelProvider and ProviderError
  providers/ollama.py     # standard-library HTTP adapter
  memory/
    __init__.py
    database.py           # SQLite connection, schema, transactions
    manager.py            # session, conversation, key/value APIs
    models.py             # immutable session/message/memory records
  # config/, core/, providers/ each contain __init__.py
native/sync/              # small C API and Makefile; generated .so ignored
tests/                    # unittest coverage
data/.gitkeep             # tracked placeholder; friday.db is local runtime data
logs/.gitkeep             # reserved log directory
```

The core depends on the provider interface rather than Ollama. Future milestones
may add ChromaDB retrieval, a scheduler, typed tools and permissions,
coding/cybersecurity agents, research/Gemini providers, Whisper, Piper, a React UI,
and plugins. None are implemented in this milestone.
