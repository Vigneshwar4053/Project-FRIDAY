# FRIDAY v0.4 Phase 4 — Controlled Python Computation

FRIDAY is Vigneshwar's personal local-first terminal AI assistant. It uses
Ollama and qwen3:4b for practical help with programming, Linux, AI, authorized
cybersecurity, research, planning, and automation advice.

## Capabilities and limits

- Terminal chat with a consistent identity and SQLite session history.
- Local HTTP model provider, connection/response error handling, and clean exits.
- Requests `think: false` and displays only final answer content. The provider
  also removes embedded thinking blocks when Qwen ignores that option.
- No tool execution through terminal chat, cloud APIs, or extra Python dependencies. Suggested
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

## Safe tool foundation (v0.4 Phase 1)

```text
Explicit application caller
    -> ToolRequest -> ToolManager -> ToolRegistry
    -> argument validation -> PermissionPolicy -> Tool -> ToolResult
```

This is a standalone Python API, separate from terminal chat and model jobs.
Tools are registered explicitly by application code; there is no LLM-driven
invocation. Phase 2 adds bounded file tools described below, without Linux
commands, shell execution, or Python code execution. The CLI, SQLite memory, and native model synchronization stay intact.

A trusted `Tool` implementation declares an immutable `ToolSpec`: unique
lowercase identifier, description, explicit risk, and argument schema. Schema
fields use `ArgumentSpec` with a required flag and string/integer/number/boolean/
object/array types. Validation rejects unknown fields, missing required values,
wrong types, and boolean values used as numbers; it performs no coercion. Arrays
and objects accept finite JSON-compatible values, without nested field schemas
or nested domain validation. File tools separately enforce a path boundary.

`ToolRequest` carries a UUID (or supplied request id), creation timestamp, and
copied arguments. Requests, schemas, registered metadata, and result data are
immutable: objects become read-only mappings and arrays become tuples. Unsupported
values, nonfinite numbers, cycles/excessive nesting (over 64 levels), and nonstring
object keys are rejected. `ToolRegistry` rejects duplicate names, keeps isolated
per-instance state, returns immutable registration records on lookup, and lists
immutable metadata in registration order.

Default `RiskPermissionPolicy` decisions:

| Risk | Decision |
| --- | --- |
| `READ_ONLY` | `ALLOW` |
| `WRITE` | `REQUIRE_USER_APPROVAL` |
| `EXECUTE` | `REQUIRE_USER_APPROVAL` |
| `PRIVILEGED` | `DENY` |

Policies are injectable and can inspect registered metadata and request arguments.
Trusted application configuration can override defaults. Invalid decisions and
policy exceptions fail closed. **Approval-required requests never execute**:
there is no approval UI, token, or automatic retry in Phase 1.

`ToolManager.execute(request)` looks up, validates, evaluates policy, and only
then invokes the tool. Tools return structured data; the manager builds a
`ToolResult` with status, data/error, tool/request identity, request timestamp,
manager processing start, and finish time. Status distinguishes success, failure,
unknown tool, invalid arguments, denial, and approval required. Tool exceptions
produce generic failures without raw exception messages or tracebacks.
KeyboardInterrupt/SystemExit propagate. Invalid API construction is a programmer
error; correctly constructed requests receive structured results.

This policy boundary is **not a sandbox for untrusted Python plugins**. Tool and
policy implementations are trusted local code; application dispatch must use
`ToolManager`. There is no dynamic loading, automatic tool discovery, audit
persistence, subprocess invocation, `eval`, or `exec` in this package.

Later v0.4 phases may add explicit user approval, serialization/auditing, and
controlled model integration. None is implemented yet.

Run the focused tests (purely fake/in-memory tools):

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_tools.py' -v
```

## Safe file tools (v0.4 Phase 2)

```text
Explicit caller -> ToolRequest -> ToolManager -> ToolRegistry
  -> schema validation -> PermissionPolicy -> File tool
  -> FileSystemPolicy (allowed roots + descriptor checks) -> ToolResult
```

Composition requires trusted, explicit existing directory roots; no default
filesystem access is granted. Relative paths use the first root; absolute paths
must stay inside one configured root. `max_file_size` defaults to 1 MiB and
bounds both UTF-8 reads and writes. Example composition (no invocation):

```python
from friday.tools import ToolManager, ToolRegistry
from friday.tools.files import register_file_tools
from friday.tools.filesystem import FileSystemPolicy

boundary = FileSystemPolicy(["/your/explicit/allowed/directory"], max_file_size=1024 * 1024)
registry = ToolRegistry()
register_file_tools(registry, boundary)
manager = ToolManager(registry)  # invoke only via manager.execute(ToolRequest(...))
```

| Tool | Arguments | Structured output | Default permission |
| --- | --- | --- | --- |
| `list_directory` | `path` | path, sorted entry names/types | ALLOW |
| `read_file` | `path` | path, UTF-8 content, byte size, encoding | ALLOW |
| `file_info` | `path` | path, type, byte size, UTC modification time | ALLOW |
| `write_file` | `path`, `content`, optional boolean `overwrite` | path, bytes written, overwrite intent | REQUIRE_USER_APPROVAL |

The default write policy never opens or writes a file. There is no interactive
approval flow. Tests inject an explicitly allowing policy only with temporary
files. Existing files are protected by exclusive creation unless `overwrite`
is explicitly true. Missing parent directories are not automatically created.

Paths reject NULs, empty values and all `..` components, even traversal that
would normalize back inside a root. Both lexical and resolved paths must be
inside a root, using component boundaries rather than string prefixes.
Linux descriptor-relative opens walk directory components with `O_NOFOLLOW`;
final opens also refuse symlinks. **All symlinks are rejected for access**, even
in-root links; directory listings may report their names/types without following
them. Read/write targets must be regular files with a single hard link. Reads
are bounded during I/O as well as by initial size, decode strict UTF-8, and reject
NUL-containing binary content. FIFO/device targets cannot become read/write tools.
Metadata omits owners, permissions, inode identifiers and link targets. Operational
errors remain generic structured failures through the existing manager.

Limits: Ubuntu/Linux filesystem APIs are required. This is not an OS sandbox
against hostile mount changes, directory relocation by another process, or
untrusted Python implementations. Files may change during reads; overwrites are
not atomic or crash-safe, and an I/O failure may leave a partial file. Directory
listing size is currently unbounded. No delete, rename, permission changes,
subprocess execution, automatic registration in chat, or autonomous tool use is
provided. Future work includes bounded listings, atomic writes and reviewed approval.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_file_tools.py' -v
```

## Safe Linux/system tools (v0.4 Phase 3)

```text
Explicit caller -> ToolRequest -> ToolManager -> schema validation
  -> PermissionPolicy -> narrow system Tool -> ToolResult
                     disk_usage -> FileSystemPolicy -> opened descriptor
```

All five tools are `READ_ONLY` and default to `ALLOW`. Register explicitly with
`register_system_tools(registry, filesystem_policy)` from `friday.tools.system`,
then invoke only through `ToolManager.execute`. Registration does not connect
anything to chat, change permissions, or broaden the supplied filesystem roots.

| Tool | Arguments | Data source and output |
| --- | --- | --- |
| `system_info` | none | `os.uname` and `sys`: OS, kernel, architecture, hostname, Python version/implementation |
| `memory_info` | none | fixed `/proc/meminfo`: total/available/used and swap counters, in bytes |
| `cpu_info` | none | `os.cpu_count`, `os.uname`, `os.getloadavg`, fixed `/proc/cpuinfo`: logical count, architecture, bounded model label, three load averages |
| `disk_usage` | `path` | `os.fstatvfs` on a boundary-checked descriptor: total, used and user-available free bytes |
| `process_status` | `name` | fixed `/proc/<numeric-pid>/comm`: exact-name running flag/count, incomplete flag and visible-process scope |

Narrow Python APIs avoid command parsing and arbitrary execution. No subprocess,
shell, process signals, service changes, package management, environment reads,
command-line reads or generic command tool is provided. System tools return
selected fields, never raw pseudo-file contents, usernames, process IDs or
credentials. Hostname and CPU model are deliberately exposed by their specific
capabilities; read-only status is not a guarantee that information is non-sensitive.

`disk_usage` uses the same explicit roots, traversal rejection and no-symlink
rules as file tools. `fstatvfs` queries the opened file/directory rather than
reopening a validated pathname, avoiding a second path-security mechanism.
Paths outside roots fail before querying capacity. Capacity describes the entire
filesystem containing the allowed path, not the size of the allowed subtree.
Reserved blocks mean `used + free` need not equal `total`.

Memory reads are capped at 64 KiB, with strict ASCII parsing of selected kB
counters and consistency checks. Total is required; missing available memory
means available/used are null, rather than using an unreliable estimate. Missing
swap counters produce null swap fields. Malformed selected counters, missing or
inaccessible meminfo fail through the manager's generic structured error.
CPU parsing examines at most the first 64 KiB and returns a model label of at
most 256 characters. Missing model/load/count information is null; load averages
are OS averages, not a CPU utilization percentage.

Process names must be 1–15 ASCII letters/digits/underscore/dot/hyphen, starting
with a letter or digit. This is exact `comm` matching, not a substring, executable
path or command-line search. Invalid name syntax fails before `/proc` scanning;
wrong declared argument types fail at manager validation. Reads use pinned
directory descriptors and no-follow flags, at most 64 bytes per comm. Processes
that vanish or become inaccessible are skipped and set `incomplete=true`.
The count covers visible processes in the current PID namespace; permissions,
`hidepid`, concurrent exits/renames and kernel name truncation limit certainty.
A false running flag is not proof of global absence. Matching zombie entries may
still be counted. This is a snapshot, not monitoring or process control.

The Phase 2 mount/hostile-filesystem limitations still apply. There is no LLM
integration, interactive approval or persistent audit log. Run focused tests:

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_system_tools.py' -v
```

## Controlled computation (v0.4 Phase 4)

```text
ToolRequest -> ToolManager -> schema validation -> PermissionPolicy
  -> CalculateTool -> predefined bounded numerical operation -> ToolResult
```

Explicitly register with `register_computation_tools(registry)` from
`friday.tools.computation`, then submit `ToolRequest("calculate", arguments)`
through `ToolManager`. The tool is `READ_ONLY` (default `ALLOW`), but injected
denial/approval decisions still prevent execution. There is no chat integration.

Arguments are exactly `operation` (string) and `values` (numeric array).
Results contain `operation`, `result`, and `input_count`.

| Operations | Meaning/arity |
| --- | --- |
| `add`, `sum` | Sum all values; only `sum` permits empty input (zero) |
| `subtract`, `divide` | Exactly two values, in supplied order |
| `multiply` | Product of one or more values |
| `power` | Exactly two values: base, exponent; bounded real floating-point power |
| `mean`, `median`, `min`, `max` | One or more values |
| `count`, `sort` | Count or ascending numeric sort; empty input allowed |
| `percentage` | Exactly two values: part, whole; `(part / whole) * 100` |

Named limits in `computation.py`: at most **1,000 values**, absolute numeric
input/result magnitude at most **10^12**, absolute exponent at most **100**.
Only exact built-in integers/floats are accepted, never booleans, strings,
objects or nested values. NaN/infinity are rejected by the existing immutable
`ToolRequest` constructor before dispatch. Missing/extra/wrongly typed fields
return `INVALID_ARGUMENTS`; invalid operations, operand domains, arity, limits,
zero denominators and unsafe results return generic `FAILED` results through
the manager. Invalid request construction raises `ValueError`, as in Phase 1.

Power uses fixed-size floating-point math rather than unbounded integer
exponentiation. Multiplication checks every intermediate result, so even a
later zero or small factor cannot bypass the magnitude limit. Sort output is
bounded by the input-count limit. All scalar results must remain finite and
bounded. Python numerical precision applies; exact decimal financial arithmetic,
complex numbers, expression parsing and arbitrary precision are not provided.

Users choose names from a fixed operation whitelist, not source code, modules,
functions or scripts. The computation module has no filesystem, process,
network, environment or dynamic-import access. It does not evaluate, compile
or execute supplied strings. Code-shaped strings are ordinary invalid operands.
This is a narrow capability, not an untrusted-code sandbox or Python REPL.
Existing request snapshot creation occurs before tool-level count limits; a
future routing/transport layer must also bound incoming payloads before copying.
Phase 5 will address controlled routing/CLI integration; it is not implemented.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_computation_tools.py' -v
```

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
  tools/
    __init__.py           # standalone public tool API
    base.py               # trusted Tool interface
    models.py             # schemas, immutable requests/results, risk/status enums
    registry.py           # isolated registry and metadata snapshots
    permissions.py        # allow/deny/approval policy
    manager.py            # validation, permissions, safe execution flow
    filesystem.py         # explicit roots and descriptor-based path boundary
    files.py              # typed list/read/info/write tools; explicit registration
    system.py             # narrow read-only Linux tools; explicit registration
    computation.py        # bounded predefined numeric operations
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
may add ChromaDB retrieval, a scheduler, reviewed system tools and interactive approval,
coding/cybersecurity agents, research/Gemini providers, Whisper, Piper, a React UI,
and plugins. None are implemented in this milestone.
