# FRIDAY — local offline personal AI assistant

FRIDAY is Vigneshwar's personal local-first terminal AI assistant. It uses
Ollama and qwen3:4b for practical help with programming, Linux, AI, authorized
cybersecurity, research, planning, and automation advice.

Current source/runtime findings and confirmed limitations are in the [full feature audit](docs/FRIDAY_FULL_FEATURE_AUDIT.md). Git tags stop at v0.4.0; voice and desktop changes remain unreleased. Historical phase sections retain their original test counts.

## Capabilities and limits

- Terminal chat with a consistent identity and SQLite session history.
- Local HTTP model provider, connection/response error handling, and clean exits.
- Requests `think: false` and displays only final answer content. The provider
  also removes embedded thinking blocks when Qwen ignores that option.
- Hybrid read-only tools through terminal chat (deterministic routing first, bounded Qwen proposals for unmatched action-like requests); no cloud APIs or extra Python dependencies. Suggested
  commands must be run by the user. Successful ordinary chat turns are saved;
  filesystem turns and temporary file explanations are not saved.
- Interactive read-only folder permissions, revocation, conservative sensitive-path
  exclusions and one-use temporary context for explicit file explanations.

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
requests use the same recent-message bound throughout the session, while successful ordinary chat turns remain in SQLite. Filesystem turns and
temporary file explanations are excluded. A limit of zero disables restored/model
history but still saves ordinary chat turns. A message-count limit does not cap
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
Successful ordinary final answers proceed to conversation persistence; temporary
file explanations are excluded and their job content is scrubbed. Ollama HTTP
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

The typed tool API is separate from model jobs. The CLI explicitly registers
tools and routes supported user intents deterministically; there is no LLM-driven
invocation. Phase 2 adds bounded file tools described below, without Linux
commands, shell execution, or Python code execution. SQLite memory and native
model synchronization stay intact.

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

Phase 6B adds filesystem-only approval. Later phases may add reviewed write/execute
approval, serialization/auditing, and
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
write approval flow; Phase 6B approvals are limited to read/list access. Tests inject an explicitly allowing policy only with temporary
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
enumeration is bounded by Phase 6A, with Phase 6B sensitive-entry filtering. No
delete, rename, chmod/chown, subprocess execution or autonomous tool use is
provided. Future work includes atomic writes and reviewed write approval.

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
anything to chat by itself, change permissions, or broaden the supplied filesystem roots.

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

The Phase 2 mount/hostile-filesystem limitations still apply. There is no model-driven
tool invocation, interactive approval or persistent audit log. Run focused tests:

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
denial/approval decisions still prevent execution. Phase 5 adds narrow chat routing.

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
Phase 5 routing bounds incoming text and numeric payloads before request creation.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_computation_tools.py' -v
```

## Safe routing and CLI integration (v0.4 Phase 5)

```text
CLI user message -> FridayAssistant -> deterministic ToolRouter
    matched -> ToolRequest -> ToolManager -> schema/permission checks -> Tool
            -> ToolResult -> deterministic ToolPresenter -> retention policy
    unmatched -> existing ModelManager -> ModelProvider/Qwen -> conversation history
```

The production CLI composes a fresh registry, file/system/computation tools,
default permission policy, router and presenter. `settings.project_root` is an
explicit absolute project path derived from the installed repository location,
independent of working directory and user text. It is always an allowed file root.
Additional read-only roots are opt-in through Settings or Phase 6B CLI approval;
see the filesystem sections below.
File-size and Phase 2 descriptor/no-symlink protections still apply. Direct
`FridayAssistant` construction without injected routing stays compatible.

Supported narrow routes (case-insensitive intent phrases, preserved file paths):

| Intent | Examples | Tool |
| --- | --- | --- |
| Memory | `check my RAM`, `show memory usage`, `how much RAM is available`, `check swap` | `memory_info` |
| System | `system info`, `what OS am I running`, `show kernel information`, `what architecture is this machine` | `system_info` |
| CPU | `check CPU`, `show CPU information`, `what processor am I using`, `system load` | `cpu_info` |
| Project listing | `what files are in this project?`, `list project files`, `show files in the project` | `list_directory` |
| Read | `read README.md`, `show friday/models/manager.py`, `open tests/test_tools.py` | `read_file` |
| Disk | `check disk space`, `how much disk space is available?`, `disk usage for this project` | `disk_usage` |
| Process | `is ollama running?`, `check ollama process`, `is code running?` | `process_status` |
| Calculation | `calculate the mean of 10, 20, 30`, `add 10,20,30`, `median of 5,1,9`, `what is 25 percent of 200` | `calculate` |

Numeric routes support the Phase 4 operation names and comma-separated signed
real/scientific numeric literals. Subtract/divide/power/percentage still require
exactly two operands. No expressions are evaluated. Read requests preserve
unquoted paths, including spaces when a dot or slash is present; single-token extensionless `read` requests are also recognized. Pronouns
and ambiguous prose are not guessed. Absolute and traversal filesystem requests
are recognized and checked by the file boundary. Directory routes accept explicit
paths and folder aliases. Disk routes still use only the configured project root.

**Unmatched normal conversation uses Qwen. Matched tool failures never do.**
The presenter formats actual results directly, with a `[Tool: name]` source label.
It does not ask Qwen to rewrite live facts. Failures display the actual status;
permission denials and approval-required results remain final responses for that
turn. Selected write verbs and generic `run/call/execute tool ...` syntax are
blocked with an explicit not-enabled/approval message. `write_file` stays registered
with default approval-required permission but is excluded from the router allowlist.
There is no model-output dispatch protocol or automatic approval.

Input is bounded to 4,096 characters **before router parsing and ToolRequest
creation**; over-limit text is rejected without storing it in conversation memory.
Parsed values are capped at 1,000, with numeric tokens at most 32 characters, and
nonfinite values rejected before requests are copied. Code/shell-shaped numeric
payloads are blocked; ordinary ambiguous calculation prose falls back to chat.
The existing numeric magnitude/exponent limits remain authoritative in the tool.

Ordinary chat and successful non-filesystem tool responses use the existing atomic
`save_turn` path. Phase 6B keeps read/list results, filesystem denials, permission
commands, and temporary file explanations outside persistent chat history. Raw results,
request identifiers, internal policy metadata and routing objects are not persisted as
conversation text. Tool-labelled historical replies are **past snapshots**, not
proof of current system state. Successful non-filesystem tool replies follow the same restored/bounded
conversation handling as chat; routed queries do not acquire the model semaphore.

Presentation escapes terminal controls and limits display to 12,000 body
characters, with directory listings capped at 100 displayed entries. Phase 6A
bounds enumeration before collecting results; Phase 6B adds conservative
sensitive-path exclusions and filesystem-only interactive approval. This is a
local assistant with heuristic exclusions, not a complete secrets detector.
There is no semantic intent model, autonomous loop, general command parser or
general tool approval/auditing system. Broad synonyms and unsupported path syntax may use
normal chat, whose suggestions do not execute. A future phase can expand routes
and approval after review.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_tool_routing.py' -v
.venv/bin/python -m friday.main
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
  core/assistant.py       # conversation, routing and privacy-aware history
  core/file_context.py    # one bounded session-only file snapshot
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
    permissions.py        # risk-level allow/deny/approval policy
    access.py             # filesystem-only direct CLI approval and administration
    grants.py             # restrictive validated persistent read-only store
    sensitive.py          # path/name/content exclusions
    manager.py            # validation, permissions, safe execution flow
    filesystem.py         # explicit roots and descriptor-based path boundary
    files.py              # typed list/read/info/write tools; explicit registration
    system.py             # narrow read-only Linux tools; explicit registration
    computation.py        # bounded predefined numeric operations
    router.py             # bounded deterministic intents and read-only allowlist
    presenter.py          # deterministic bounded tool response formatting
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
may add ChromaDB retrieval, a scheduler, reviewed write/execute tools and approval,
coding/cybersecurity agents, research/Gemini providers, Whisper, Piper, a React UI,
and plugins. None are implemented in this milestone.


## Multi-folder filesystem access (v0.4 Phase 6A)

The project root remains enabled. No Downloads, Documents, Desktop, Pictures,
Videos or other personal folder is automatically authorized. To explicitly opt in,
edit trusted `Settings.filesystem_read_roots` in `friday/config/settings.py`, for
example:

```python
filesystem_read_roots: tuple[Path | str, ...] = ("~/Downloads", "~/Documents")
filesystem_max_directory_entries: int = 100
```

Only enable folders you want FRIDAY to read. Configured roots must exist, be
eligible directories, and contain no symlink components. Invalid configuration
fails closed at composition. Blanket home/system roots are rejected in production. Paths
expand the current user's home without a hardcoded username. The CLI uses this
configuration directly. Phase 6B also provides explicit interactive grants below.

`create_tool_runtime` builds one `FileSystemPolicy` with the project first, all
explicit read roots, and only the project as a write root. Default ToolManager
permissions still require approval for writes; chat cannot dispatch writes.
Even an explicitly write-allowing manager cannot write into additional read-only
roots. Low-level callers can configure separate `write_roots` explicitly; these
must be configured read roots. Omitting `write_roots` enables only the first root
for policy-level writes, subject to ToolManager permission.

Relative paths start in the project. Additional read-root basenames are
case-insensitive aliases; the project basename never shadows its source package:
`Downloads/notes.txt` works only when its root is authorized. Duplicate aliases or
aliases colliding with project entries fail safely; use the absolute path instead.
Absolute paths and `~/` paths retain the existing lexical/canonical containment,
no-parent-traversal, descriptor-relative no-symlink, singly linked regular-file,
strict UTF-8, nonblocking-special-file and 1 MiB read protections.

Examples: `list files in Downloads`, `what files are in ~/Downloads`,
`show files in Documents`, `list /absolute/authorized/folder`,
`read ~/Downloads/notes.txt`, `read friday/tools/router.py`.
Explicit unauthorized list/read requests are final tool responses and
**never fall back to Qwen**. Phase 6B can request direct CLI approval for eligible
folders; system folders such as `/etc` remain ineligible. Noninteractive requests
without a grant fail safely.
This phase does not launch applications; the legacy `open file.txt` spelling is
still a text-read route.

Enumeration collects at most `filesystem_max_directory_entries` entries (default
100), consumes at most one additional entry to detect truncation, and stats only
the collected entries without following symlinks. Results contain `entries`,
`truncated`, `limit` and `path`. Only that bounded subset is sorted; it is not a
globally sorted page, and directory iteration order may vary. Names are JSON-escaped
for terminal controls, line breaks and undecodable filesystem bytes. Disappearing
entries fail closed with no partial result. The presenter shows at most 100 entries
and 12,000 body characters, with explicit omission/truncation indicators.

Phase 6B supersedes the original retention behavior: filesystem results are not
saved to CLI conversation memory, and known sensitive paths/content are excluded
regardless of authorization. Unknown secrets can still evade heuristic exclusions.
Mounts, malicious filesystems and concurrent directory renames remain limitations
of the existing path-boundary design; it is not an OS sandbox.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_multi_folder.py' -v
```


## Interactive permissions and privacy (v0.4 Phase 6B)

The LLM never grants access. A recognized `read_file` or `list_directory` request
for an eligible unauthorized location can ask the direct interactive CLI user:

```text
Permission required:
Operation: list_directory
Folder: "/home/<user>/Downloads"
Access: READ_ONLY
Target: "/home/<user>/Downloads"

Allow once: exact target and operation only.
Always allow: this folder and descendants, read/list only.

[1] Allow once
[2] Always allow this folder
[3] Deny
Permission choice:
```

Paths are quoted/escaped to prevent filenames from forging prompt lines or terminal
commands. A file-read prompt shows its exact file target and its containing folder.
Choice 1 permits only that one target/operation, not sibling files or future
requests. Choice 2 permits text reads and directory listings within exactly the
shown folder and its descendants, with all exclusions still enforced. The parent
of the displayed folder is never granted. Metadata-only path/type/identity probes may precede the prompt; no file body or
directory entries are read before approval. Neither choice grants writes, execution,
file-info/disk tools on new roots, privileged access or desktop launching.

Only direct input while this prompt is active can approve. Accepted choices are
`1`/`allow once`, `2`/`always allow this folder`, or `3`/`deny`. All other input,
EOF and Ctrl+C deny. Both stdin and stdout must be TTYs. Redirected/headless use
denies without prompting; existing authorized roots still work. The composition
API defaults to no approval adapter. Model output, file contents and ordinary
chat messages such as `1`, `yes` or `allow once` never become approvals.

Allow-once authorization lives only in a request-scoped context. It binds the
operation, exact target, folder identity and target identity, then disappears even
on failure. It never changes the global read roots and never enters the store.
The tool schema and risk policy run before prompting, and the filesystem boundary
rechecks containment, exclusions, no-symlink traversal and approved identities
when the tool opens the target. No failure or denial falls back to the model.

### Folder commands

These deterministic commands stay outside model prompts and conversation history:

```text
show authorized folders
list authorized folders
always allow Downloads
revoke access to Downloads
revoke access to ~/Documents
```

`always allow` initiates the same direct prompt; choose 2 to save a persistent grant.
The command's wording itself does not approve anything. `revoke access to` removes
only an existing exact explicit persistent folder grant and reports its canonical
folder. No extra revocation confirmation is needed. Built-in project access and
Settings roots cannot be revoked here; edit Settings for configured roots.
Revoking a nested grant does not remove inherited access from another configured
or persistent ancestor. If that matters, revoke/edit the ancestor too.

Configured/persistent folder basenames are aliases only when unambiguous. Standard
unconfigured names Downloads, Documents, Desktop, Pictures, Videos, Music, Public
and Templates are **candidates** under the current home directory for prompting,
not implicit grants. Use absolute paths for custom folders or ambiguous aliases.
Actual home directories, their ancestors, top-level filesystem directories,
whole `~/.config`/`~/.local` trees and system trees such as /etc, /proc, /sys, /dev,
/usr, /bin, /sbin, /lib, /boot, /run and /root cannot become production read roots.
Individual files directly in an ineligible parent (for example `~/notes.txt`)
also cannot be interactively approved under this folder-based policy. Existing
properly scoped project and configured folder access remains supported.

### Dedicated permission storage

Default: `<project>/data/permissions/grants.json`, separate from conversational
SQLite. Set `Settings.filesystem_permission_store_path` to a trusted absolute Path
for a different private location. Add custom locations inside the repository to
.gitignore; the default data directory is already ignored. Its parent must be owned by the current user
and mode 0700; files are owned regular singly linked files with mode 0600.
The store contains only versioned READ_ONLY folder records and device/inode IDs,
not file bodies or secrets. No permission records are sent to the model.

There are at most 64 records and 64 KiB of store data. Every use reloads/validates
schema, path encoding, root eligibility and current no-symlink folder identity.
Malformed JSON, duplicate keys/records, dangerous roots, changed identities,
insecure modes, symlinks, hardlinks and unavailable storage fail closed. File-info,
disk, write and execute capabilities are not granted by persistent read records.

Updates take a nonblocking process lock and atomically replace the snapshot.
A fsynced pending marker gates access until the updated snapshot is durable;
interrupted writes/revocations leave storage unavailable instead of activating a
partial grant. A crash after successful publication may conservatively resurrect
that marker and deny access, rather than restore a revoked snapshot. Store errors
block further filesystem read/list operations in that runtime. Ordinary chat is
still available. Do not automatically remove a pending marker or repair invalid
data: review the store offline and its grants before restoring it, then restart.
No cached grant can survive a successful revocation. An already-open operation
is not forcibly cancelled by another process's revocation.

### Sensitive-path policy

Exclusions apply at FileSystemPolicy even inside the project, configured roots,
allow-once targets and persistent grants. Listings omit excluded entries before
statting them, and excluded entries still count toward the bounded scan budget.
The precise rules are in `friday/tools/sensitive.py`:

- Credential/security directories: .ssh, .gnupg, .aws, .kube, .pki, .azure, secrets,
  .git, keyrings, .password-store, and .config/gh, .config/gcloud, .config/op.
- Browser/password-manager components: .mozilla, Firefox, Chromium, Google Chrome's
  google-chrome directory, Brave, Edge, Vivaldi, Bitwarden, 1Password and KeePassXC.
- Credential/config names: .env/.env.*, private-key names, id_rsa/id_ed25519/id_dsa/
  id_ecdsa, authorized_keys, credentials/credentials.*, .netrc, .npmrc, .pypirc,
  .git-credentials, kubeconfig, .dockerconfigjson and .docker/config.json.
- Token, API-key, client-secret, secret-key, private-key, service-account and
  Firebase-adminsdk naming conventions; certificate/key/password-vault suffixes
  .pem, .key, .p12, .pfx, .ppk, .kdb, .kdbx, .psafe3, .opvault, .agilekeychain.
- Browser credential filenames such as Login Data, Cookies, logins.json, key4.db,
  key3.db and signons.sqlite, plus permission-store names and its entire directory,
  and the configured conversational database and its standard sidecars.

Matching is case-insensitive for names/components, not a blanket ban on hidden
files: `.editorconfig` remains readable. Text reads additionally reject PEM/OpenSSH private-key
markers, OpenPGP private-key blocks and nonempty JSON strings under access_token, refresh_token,
client_secret, private_key and aws_secret_access_key. These are conservative
heuristics: renamed/encoded secrets, unusual credential stores and unknown token
formats can evade them; harmless examples can be excluded. Invalid UTF-8, NUL text,
oversized files, special files and shared hardlinks remain rejected. There is no
interactive override for exclusions, and errors contain no private content or
unnecessary sensitive metadata.

### Temporary file context and memory

Router refusals and unsuccessful tool decisions are not retained, including
blocked writes and approval-required messages. Read/list results, filesystem
denials and permission commands are not saved to
SQLite and are not appended to ordinary model conversation history. Successful
text reads display `[Session-only file context; not saved]` and keep **one** bounded
snapshot: at most 16,384 bytes of serialized JSON, including source and content.
The snapshot may be shorter than the displayed file. It is replaced by the next
file read and discarded by an unrelated turn, any other routed operation, a
permission command, a failed request or session shutdown.

An explicit immediate follow-up can use that snapshot once: `explain that code`,
`explain this code`, `explain that file`, `explain this file`, `explain the file`,
`summarize that file`, `summarize this file`, `review that code`, `analyze that code`,
or `what does that code do`. **This intentionally sends the bounded file snapshot
to the configured model for that follow-up.** Deterministic reads/listings and all permission prompts/choices make no model call.
Phase 6C may use one intent-model call before an unmatched semantic read/list request;
it receives no file body and never interprets permission choices.

The snapshot is framed as untrusted JSON data in a user message with explicit
system instructions to ignore embedded instructions/approvals. The explanation
is labelled `[Temporary file context; not saved]`. Both that turn and its generated
answer stay out of persistent and ordinary chat history, and private model-job
messages/results/errors are scrubbed even on failure. The snapshot is consumed
on the attempt, so a later explanation needs another explicit read. Model behavior
cannot be guaranteed against prompt injection; it has no authorization or execution
channel and its private answer is not retained for later unrelated prompts.

Ordinary chat memory and successful non-filesystem tools continue to use the existing atomic
save_turn behavior. Legacy labelled filesystem turns and their recognized immediate follow-ups are
filtered from restored model context without deleting old SQLite data. Unlabelled
older derived text or history windows missing the original file turn cannot always
be identified; review legacy data before sensitive use. Old Phase 6A databases/backups may
still contain previously saved file bodies; this phase does not silently purge
user data or promise secure RAM/disk erasure.

### Phase 6B regression tests and demo

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_filesystem_permissions.py' -v
.venv/bin/python -B -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python -B tests/phase6b_demo.py
.venv/bin/python -B -m friday.main
```

The reproducible demo mocks only direct terminal choices and model explanation,
uses temporary writable state, and omits the body of its real project-source read.
No personal documents or real user files are modified. Live Qwen inference is a
separate integration check; explanation tests prove the supplied context/privacy
boundaries with a deterministic provider.

Phase 6B privacy/store recovery limitations remain applicable. Hybrid intent routing
is documented below; bounded session navigation is described below; search and desktop opening remain separate phases.

## Phase 6C: voice-ready hybrid natural-language routing

Deterministic routing remains first: recognized commands, invalid requests and
refusals never reach Qwen as fallback. A small semantic location resolver adds
simple known-folder browsing without model inference. Unfamiliar action-like
phrasing uses one structured Qwen response through the existing ModelManager,
Ollama provider and native POSIX mutex. Ordinary chat retains its memory-aware
conversation flow. All tools use the same ToolManager and permission system.

```text
User → deterministic router → simple folder concept → trusted location resolver
                           └→ unmatched → Qwen proposal → strict validation
                                                          + location resolution
                                         ↓
                         ToolRequest → ToolManager → PermissionPolicy
                                         ↓
                         Phase 6B filesystem access → registered tool
```

### Semantic locations and voice input

| Spoken concept | XDG mapping | Default only when mapping is absent |
|---|---|---|
| photo / photos / picture / pictures | XDG_PICTURES_DIR | ~/Pictures |
| videos | XDG_VIDEOS_DIR | ~/Videos |
| downloads | XDG_DOWNLOAD_DIR | ~/Downloads |
| documents | XDG_DOCUMENTS_DIR | ~/Documents |
| music | XDG_MUSIC_DIR | ~/Music |
| desktop | XDG_DESKTOP_DIR | ~/Desktop |

`open photos`, `show my pictures`, `pictures`, `open videos`, `show downloads`,
`list documents`, `open music`, and `open Desktop` use a small verb/alias grammar,
not a collection of memorized sentences. `FRIDAY, open my photos.` is accepted
as transcribed text. These requests cost **zero Qwen calls**. “Open” means list
contents in this CLI; it never claims to launch an application.

`can you show me my photos?`, `take me to my downloads`, and
`FRIDAY, can you take me to the place where I keep my pictures?` now use the
trusted fast path too. Unfamiliar requests such as `what's in my pictures folder?`,
`show me where my videos are`, and `can you inspect my pictures folder?` retain
the hybrid intent model.
Trusted Python resolves the folder concept after strict proposal validation.
A bare `pictures` also works after a clarification because it is a complete
unambiguous new browsing request. No pending clarification/path guessing state is introduced. A separate bounded
session navigation manager now remembers successful listings, as described below.

The resolver reads only `$XDG_CONFIG_HOME/user-dirs.dirs`, or
`~/.config/user-dirs.dirs` when that environment variable is absent. It parses
bounded data: at most 16,384 bytes and 64 lines, double-quoted `XDG_*_DIR` entries,
absolute paths or a literal leading `$HOME/`. Non-English folder names and spaces
are supported. Comments and blank lines are allowed. No shell is run and arbitrary
variable/command expansion is rejected. Config files and every parent are opened
without following symlinks; special/hardlinked/oversized files, invalid UTF-8,
controls, duplicate keys, traversal and malformed syntax fail closed. Backslash
escape syntax and `${HOME}` expansion are deliberately unsupported. A malformed
configuration does not silently select the English default. A mapping of `$HOME`
(disabled folder), `/`, or a relative path is unavailable; no home/root listing is
authorized. Missing directories are reported, never created or replaced.

XDG mappings are location hints, **not permissions**. The resolver neither grants
access nor opens folder contents. All resulting paths still pass through the
existing sensitive-path policy, canonical containment, descriptor traversal,
identity checks, permission prompt and file/list bounds. Configuration is reloaded
on each resolution; no authorization is cached in the resolver. Semantic names
use XDG directories; pre-existing deterministic configured-root aliases such as
`list files in Downloads` retain their Phase 6A rules. Their ambiguity/conflict
checks remain intact. Use an explicit path to distinguish those meanings. For
revoking a localized XDG grant, use the canonical folder shown by `show authorized
folders`; permission-management aliases retain their existing rules.

Explicit paths stay exact: `/Videos` is different from `~/Videos`. A bare path is
a deterministic directory-list request, preserving its spelling. It is never
rewritten to a semantic home folder or localized XDG directory. Existing explicit
file-reading commands still use their original routes. `play a video`,
`launch the photo viewer`, and `open the Photos application` are unsupported
application requests. `go back` and `return to the previous directory` revisit a
successfully visited directory when one exists. `go back from /Downloads` and
`enter that folder` without a named visible child remain unsupported or require
clarification; they never invent a location. Instructional questions such as `how do I open Pictures in
Ubuntu?` remain ordinary chat, including when prefixed with `FRIDAY,`.

### Strict proposals, allowlist and permissions

Existing path proposals remain supported:

```json
{"kind":"tool","tool_name":"list_directory","arguments":{"path":"~/Downloads"}}
```

The smallest semantic extension is exclusive to `list_directory`:

```json
{"kind":"tool","tool_name":"list_directory","arguments":{"location":"pictures"}}
```

`location` must be one of the bounded aliases above and grounded in exactly one
concept in the current user request. It cannot coexist with `path`, apply to a
read/write tool, replace an explicit path or reinterpret a launch/navigation
request. Compatible model paths such as `~/Pictures` for a spoken `photos` request
are normalized using the same resolver, not the model's home-directory guesses.
Only the normalized existing `path` argument reaches ToolManager. Model output
cannot set the internal semantic-evidence flag.

Other exact forms remain `{"kind":"chat","response":"..."}`,
`{"kind":"clarification","question":"..."}` and
`{"kind":"unsupported","reason":"..."}`. Text is display-only. Unknown/duplicate
fields, arrays, nested/multiple calls, non-JSON text/code wrappers, wrong types,
unknown tools/arguments, authorization flags/tokens, controls, shell syntax and
nonfinite JSON are rejected. Limits remain 4,096 input characters, 8,192 response
bytes, depth 3, 16 keys, 4,096 bytes per path and 1,000 display-text characters.
Invalid proposals fail safely without retry or execution.

The eight registered read-only model choices remain `list_directory`, `read_file`,
`file_info`, `system_info`, `memory_info`, `cpu_info`, `disk_usage`, `process_status`.
Computation remains deterministic. Writes, shell execution, privileged actions,
search and autonomous workflows are excluded. Allow once, always allow and deny
still require direct CLI input. Always-allow grants remain folder/descendants
**read/list only**, revocable; metadata tools retain static-root restrictions.
Denial never invokes Qwen to find another way in. Sensitive files and contents
remain blocked regardless of approval. No write/execute scope was added.

Safe failure categories distinguish an unavailable path, non-directory target,
permission denial and a blocked/invalid filesystem request. The presenter uses
fixed messages from a typed category, never raw exception strings, private paths
or permission-store details. The existing FAILED status/generic internal error
remain compatible. Unsupported navigation and invalid proposals have separate
controlled responses; malformed XDG configuration fails before tool dispatch.

### Privacy and performance

Semantic browsing, proposals, failures, permission prompts/choices and tool outputs
are not saved to SQLite or ordinary chat context. Planning sees only the current
request, compact schemas/aliases and an optional bounded immediate file path;
no file bodies, listings, XDG mapping contents or permission-store records.
Intent job messages/results/errors are scrubbed on success, failure and interruption.
Ordinary chat remains persistent. One bounded private file snapshot still supports
an explicit immediate explanation, intentionally outside intent planning and
without persisting the body or derived answer. Old SQLite rows/backups can retain
pre-Phase-6B file bodies/unlabelled derived text; nothing is silently deleted.

Fast requests perform a small bounded XDG read and zero model calls. Unfamiliar
wording uses one model call, with no planning/retry loop. A structured CHAT result
includes its answer in that same call and remains session-only, avoiding duplicate
inference and private-path retention at the cost of prior-chat context for that
candidate. Existing Ollama intent bounds remain 512 requested output tokens,
65,536 HTTP envelope bytes, JSON format, think=false and the configured timeout.
The original normal-chat provider behavior and single-threaded ModelManager/native
mutex are preserved for future Phase 6D adaptive workload management.

### Offline checks and owner live test plan

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_semantic_locations.py' -v
.venv/bin/python -B -m unittest discover -s tests -p 'test_intent_translator.py' -v
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
.venv/bin/python -B -m unittest discover -s tests -p 'test_sync.py' -v
PYTHONPATH=. .venv/bin/python -B tests/phase6c_demo.py
.venv/bin/python -B -m friday.main
```

The semantic refinement passed 538 tests and navigation passed 582. With trusted
file references the offline suite has **649 passing tests**: 370 committed Phase 6B
tests, 81 hybrid tests, 87 semantic tests, 44 navigation tests and 67 file-reference
regressions. The extended demo uses temporary
fixtures, a fake model, real CLI authorization/ToolManager and the actual native
mutex. It verifies backend behavior, not new live Qwen accuracy. The owner reported
successful pre-refinement live Downloads/Desktop/Pictures checks; refined semantic
accuracy and latency still need owner verification with qwen3:4b.

| Live input | Expected behavior |
|---|---|
| open photos | Fast list of XDG Pictures; permission prompt if needed |
| pictures | Same fast browsing request; no pending state required |
| open videos | Fast list of XDG Videos, not playback |
| list downloads | Fast list of XDG Downloads |
| open Desktop | Fast list of XDG Desktop; case insensitive |
| show my documents | Fast list of XDG Documents |
| what is inside my music folder? | One Qwen proposal, trusted Music resolution, permissions |
| how do I open Pictures in Ubuntu? | Ordinary instructional chat, no tool |
| play a video | Unsupported playback; no tool/model call |
| go back | Revisit the previous successful listing with fresh authorization, or report no previous location |
| /Videos | Exact absolute path; safe failure outside configured/eligible roots; never ~/Videos |
| ~/Videos | Exact home path; permission-controlled listing; no XDG rewriting |

Select Deny for personal folders unless you explicitly want to display their
filenames. Use public fixtures for file reads. Test unknown/malformed proposals and
a denied folder: no retries, private content, arbitrary execution or SQLite entries
should appear. Missing/default-disabled folders report safe errors rather than
choosing another location.

Known limits: six semantic concepts/nine English spoken aliases, not a full
multilingual voice interface; localized filesystem names come from XDG. No speech
capture, GUI launcher, directory history, recursive search, new clarification state
or filesystem indexing is implemented. Strict config syntax and lexical grounding
may require explicit paths. File-policy secret detection remains heuristic, and
model answers can be wrong or injection-influenced but cannot approve/execute.

Phase 6D is **Adaptive Workload Management**: build on the shared ModelManager,
existing native synchronization, zero-inference fast paths and explicit budgets;
measure CPU inference, queue/timeout behavior and safe cancellation. Navigation/
search require their own later bounded, permission-scoped design. Phase 6E desktop
opening requires approved apps/MIME types, executable restrictions, exact path
checks, direct confirmation and safe process arguments without a shell. Read grants
never authorize launching applications or any Trash modification.

### Session-only directory navigation

After `list downloads`, a visible directory named `portfolio` can be opened with
`open portfolio`, `enter portfolio`, or `go into portfolio`. Voice-style input such
as `FRIDAY, please enter the portfolio folder.` works too. Simple navigation costs
zero Qwen calls. Standard directory concepts (`Pictures`, `Downloads`, etc.) keep
Semantic Location Resolver precedence. Explicit `/Videos` and `~/Videos` retain
their original meanings and do not become relative to the current location.

`go back` revisits the last successfully visited directory, rather than calculating
a parent. `go home` lists FRIDAY's configured project root, then clears navigation
history after success. It does not authorize the entire Ubuntu home directory.
The manager retains at most 16 prior locations and 100 visible child entries. It
records a location only after a successful, authorized listing. Failed or denied
requests leave both location and history unchanged. A new successful listing
replaces the child snapshot; no filesystem search is performed.

Trusted tool results provide directory names and device/inode identities. These
identities are checked again before approval and on descriptor-relative execution.
They are stale-target checks, never permission grants. Parent **Allow once** does
not authorize a child, and returning with `go back` asks again when necessary.
Persistent read/list grants retain their existing scope and can be revoked.
Sensitive entries and symlinks cannot be navigated through the cache. Unknown,
unlisted or ambiguous entries require clarification or an explicit path;
case-colliding names can be selected with exact double-quoted spelling. Controls
and invalid Unicode names are excluded from navigation. Explicit `read path`
commands remain available; `open` of a listed regular file reads supported text
through the same permission system. `enter` of a regular file explains the type mismatch.

Navigation context stays in Python memory, is never sent to Qwen or SQLite, and
clears at session shutdown. A validated model basename can select a cached child,
but only trusted backend code constructs its guarded path. Listing and navigation
responses remain outside conversation memory. There is no forward history,
recursive search, navigation persistence, speech capture, or application launching.
Truncated listings only make their returned entries available for navigation.
Stale snapshots require relisting; device/inode checks do not promise immunity to
inode reuse or every concurrent filesystem mutation.

Owner test sequence (use only folders you want to authorize):

1. Start FRIDAY as documented above with qwen3:4b available.
2. `list downloads` → existing authorization and a bounded listing.
3. `open portfolio` → works only if `portfolio` was returned as a directory;
   Allow once for Downloads asks for a separate child decision.
4. `go back` → authorized revisit of Downloads; Allow once may prompt again.
5. `go home` → project listing, no blanket home grant.
6. Deny child approval → no listing and no location change.
7. `open pictures` → semantic/XDG Pictures mapping takes precedence.

Offline checks, with no personal file access or live Ollama dependency:

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_navigation.py'
.venv/bin/python -B -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python -B tests/phase6c_demo.py
```

### Context-aware file reading and explanations

After listing a folder containing `data.js`, `index.html`, and `images`:

| Request | Behavior |
|---|---|
| `open images`, `enter images`, `show images folder` | List the verified child directory |
| `open data.js`, `read data.js`, `show data.js` | Read the verified file through ToolManager |
| `what's in data.js?`, `what have in data.js` | Display the actual authorized text; no Qwen call |
| `show me index.html`, `read the index file` | Read the exact name, or unambiguous listed file stem |
| `explain data.js`, `explain what's inside data.js` | Authorized read, then one bounded session-only model explanation |
| `summarize index.html` | Authorized read, then one bounded session-only summary |
| `open portfolio.zip` | Explain that archive browsing is unsupported; no archive read |
| `open .zip file` | One visible ZIP: same refusal; multiple matches: ask which one |

File existence and type come only from the last successful authorized listing.
Exact names, casefold matching and explicit `the … file` stem references are bounded
by that snapshot. Ambiguous/unknown references ask for a listed name or explicit
path, without searching, guessing, or asking Qwen to invent contents. Directories
use list_directory; files use read_file. Reading never changes the current directory
or back history. A later successful listing replaces the snapshot.

A listing's Allow once does **not** grant file reads. Each read checks current
ToolManager policy, folder permissions, sensitive exclusions, no-follow traversal,
regular single-link type, file-size limit and strict UTF-8/non-NUL content rules.
The cached parent and file device/inode identities are checked before prompting
and again against descriptors during execution. A replaced file, replaced parent,
or symlink cannot silently become a different read target. A valid extension is
not proof of text; binary content under `data.js` is refused. Unsupported content
has a safe explanatory error. Controls in supported text are escaped for display.
The UTF-8/non-NUL check is a bounded text policy, not a complete MIME detector.

ZIP filenames in contextual requests are deliberately refused even if their bytes
might decode as text; no extraction, archive inspection, execution or application
launching is added. Extension selection requires exactly one matching listed file.
Symlinks and special entries remain unsupported. Explicit paths retain the existing
filesystem semantics and security checks.

An explicit explanation/summary makes one model call only after a successful read.
It reuses the existing one-item, 16,384-byte temporary snapshot and labels the content
as untrusted data, unable to authorize instructions or tool calls. Snapshot truncation
is indicated to the model. Denied/failed/binary reads make zero explanation calls.
Model failures are not retried; the verified read text is returned with an explanation
failure notice. Model prompt/job records are scrubbed, and neither body nor explanation
is saved to SQLite or normal conversation history. Navigation context is never sent
to the model. Ordinary chat memory continues working. Model summaries can still be
inaccurate and may cover only the bounded snapshot; no new live Qwen accuracy is claimed.

Voice-style folder examples now handled without Qwen:

```text
FRIDAY, take me to my pictures
FRIDAY, can you take me to the place where I keep my pictures?
take me to where I keep my pictures
can you show me my photos?
open my picture folder
show me my videos
take me to downloads
```

These are bounded browsing grammars for known XDG concepts, not a general action
parser. `how do I open Pictures in Ubuntu?`, `show me how to read data.js`, and
`tell me about photography` remain chat. `launch a photo editor` stays unsupported.

Owner live testing, using a folder you explicitly choose to authorize:

```text
list downloads
open portfolio
open images
go back
open data.js
what's in data.js?
what have in data.js
read the index file
explain data.js
summarize index.html
open portfolio.zip
open .zip file
go back
go home
FRIDAY, can you take me to the place where I keep my pictures?
```

Folder/file examples require those entries in the returned listing. Expect fresh
read approval after Allow once on the parent; Deny produces no body/explanation.
Direct reads/listings cost zero Qwen calls. Explanations use the existing local
qwen3:4b through ModelManager/native synchronization. No files are executed.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_file_references.py'
.venv/bin/python -B -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python -B tests/phase6c_demo.py
```


## Phase 6D — adaptive workloads (opt-in rollout)

Enable the adaptive path and, optionally, redacted diagnostics:

```bash
.venv/bin/python -B -m friday.main --adaptive
.venv/bin/python -B -m friday.main --adaptive --diagnostics
```

`--diagnostics` also enables adaptive mode. Settings can instead set
`adaptive_workloads=True`; the default stays False to preserve the committed
Phase 6C API/CLI greeting behavior and all 649 baseline tests unchanged. This
compatibility mode uses the existing Phase 6C behavior and does not apply the new
inference budgets. No permissions or filesystem security rules change in either mode.

| Level | Selection | Execution |
|---|---|---|
| L0 minimal | Exact hello/hi/good morning, hello friday/hi friday, thanks/thank you/goodbye | Local conventional reply; zero model/tool/permission calls; no memory save |
| L1 light | Existing deterministic routing, trusted listing references, navigation, safe refusals/clarification | Existing ToolManager and Phase 6B permissions; zero model calls |
| L2 standard | Ordinary chat, explicit verified-file explanation, unmatched hybrid intent | Existing ModelManager/provider with standard profile |
| L3 deep | Explicit “think deeply …”, “perform a detailed technical analysis …”, or “compare … thoroughly” | One conversational call with deep profile; no autonomous tools |

“hello, list downloads” and “thanks, show my files” are not L0. Classification is
local, bounded and deterministic; no model call is made to choose a workload.
Workload choice never authorizes a tool. Successfully matched actions and safe
refusals retain priority over inference. Hybrid proposals still require strict
validation and ToolManager authorization. Explicit deep analysis bypasses semantic
tool planning; mixed deep/action requests ask for a supported command first.

`list this folder`/`list this directory` relist the last successfully authorized
location, with identity validation and fresh permission as needed. With no current
listing they clarify; they never invent a path. File reads do not change navigation.

### Per-request inference configuration

Profiles are frozen, validated values in `friday/config/settings.py`, using
`friday/models/profile.py`. Example trusted local configuration:

```python
from friday.models.profile import InferenceProfile
# Fields on Settings:
adaptive_workloads = True
workload_diagnostics = False
standard_inference_profile = InferenceProfile(
    think=False, num_predict=768, num_ctx=8192, temperature=0.3,
    timeout_seconds=300, max_context_bytes=24576, max_history_messages=6)
deep_inference_profile = InferenceProfile(
    think=True, num_predict=2048, num_ctx=8192, temperature=0.4,
    timeout_seconds=450, max_context_bytes=32768, max_history_messages=16)
```

Only documented Ollama request options `num_predict`, `num_ctx`, and `temperature`
are forwarded; timeout is the existing HTTP client's timeout. The existing model
name remains unchanged. Profiles explicitly set `think=false` for L2
and `think=true` for L3; only final answers are displayed. Intent mode keeps JSON, think=false,
zero temperature and at most 512 output tokens, even with a larger profile.
Options are scoped to the request inside the existing synchronization boundary and
restored afterward. No model download, global Ollama change or second runtime is added.
See the [official Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md)
and [parameter reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx).
The installed Ollama service reported 0.40.0. Public live L2 and L3 requests
completed successfully through the existing ModelManager and native mutex; the
owner also confirmed successful live L3 analysis. See the verification summary below.
Unsupported provider/options fail safely rather than dropping the profile or retrying.

Validation rejects unlimited/negative/bool token budgets, nonfinite temperature/
timeout, odd history lengths, unknown fields and unreasonable maxima. Output is
bounded by the requested tokens, a 256-KiB ordinary HTTP response cap (64 KiB for
intent transport), and a 64-KiB final-answer cap for profiled jobs. This bounds work;
it does not promise higher answer quality, lower peak CPU usage or lower Ollama RAM.
HTTP timeout is not a hard end-to-end scheduler deadline or an OS CPU quota.

### Bounded context and file privacy

Adaptive prompts keep only recent complete user/assistant pairs. Old pairs are
dropped oldest first to meet the profile; individual turns are never rewritten or
summarized. The system instructions, current request and explicit one-use verified
file snapshot are mandatory. Their contents are never shortened again to make a
request fit; overflow fails before inference. System memory annotations are rebuilt
for the actual selected history. SQLite rows are neither deleted nor rewritten.

Serialized message bytes are capped by the smaller of max_context_bytes and
`num_ctx - num_predict - 512`: a conservative one-byte-per-possible-token proxy
with an output/template reserve, not an installed-model tokenizer. Default effective
input limits are **6,912 bytes standard** and **5,632 bytes deep**. The same 8,192
context setting means deep's larger output budget leaves less input room. This
conservative check can reject text that would actually fit. A large 16-KiB temporary
snapshot can therefore exceed the default budget; FRIDAY reports the limit instead
of silently cutting verified data or rereading another file. Tokenizer/template
behavior still needs live verification. Prompt selection is bounded; the preexisting
ordinary in-session history/SQLite retention policy itself is unchanged.

`explain this code`, `explain the code I just read`, and narrowly recognized
`think deeply about this code` can consume the existing verified session-only
snapshot once. Deep analysis grants no new read and never rereads a file. Unrelated
turns, including greetings, expire temporary file context; navigation remains.
File contents are untrusted data, not instructions. They and derived explanations
remain outside SQLite and normal history; temporary model-job records are scrubbed.
Permission decisions/prompts and private paths never enter workload diagnostics.

### Observability and benchmarking

Diagnostics are opt-in stdout JSON after a response (or model failure): selected
level/profile, classification/routing/model/total nanoseconds, provider invocation
attempt count, Python process CPU nanoseconds and Linux process peak RSS in KiB.
Only the most recent metrics are retained in memory; no diagnostic file is written.
There are no prompts, paths, tool outputs, authorization outcomes or timestamps.
Metrics may still reveal interaction patterns, so enable them deliberately.

**Python CPU/peak RSS exclude the separate Ollama process.** Peak RSS is cumulative
for this Python process, not per-request RAM. No model-related CPU/RAM estimate,
peak-CPU reduction or live speedup is claimed. Model latency measures provider.chat,
not native-lock waiting or a pure server evaluation duration; total latency includes
permission/input waits. Failed provider calls count as attempts; classification or
budget failures before provider.chat count zero.

```bash
PYTHONPATH=. .venv/bin/python -B tests/phase6d_benchmark.py --samples 3
# Explicit opt-in public-fixture live run; model/service must already be installed:
PYTHONPATH=. .venv/bin/python -B tests/phase6d_benchmark.py --live --samples 1
.venv/bin/python -B -m unittest discover -s tests -p 'test_workload.py'
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
```

Offline benchmarks use temporary public fixtures, real tools/permission checks,
the existing native mutex and a fake provider with no artificial inference delay.
They compare the retained Phase 6C compatibility path under shared instrumentation,
not an untouched commit binary. Setup is outside measured calls; each case starts
fresh. Live runs permit at most two samples per case and have uncontrolled warm/
cold effects; neither mode auto-downloads or retries. Current offline invocation
counts are **1/0/0/1/1 compatibility** versus **0/0/0/1/1 adaptive** for greeting,
folder, known file, standard chat and deep analysis. Actual timings and limitations
are documented in PHASE_6D_REPORT.md. PHASE_6D_BENCHMARK.json contains historical
fake-provider results from before the final profiles; it remains untracked and is
excluded from the recommended commit. The final suite has **770 passing tests**,
including **121 new Phase 6D tests**, with all 649 baseline tests unchanged.
Fake-provider timings do not establish live inference savings.

### Owner live test sequence

Start with `--adaptive --diagnostics`, then:

| Input | Expected workload/behavior |
|---|---|
| hello friday | L0, local greeting, zero model calls |
| thank you | L0, local gratitude, zero model calls |
| list downloads | L1, existing authorization and listing |
| open portfolio | L1 if a listed directory; fresh approval after Allow once |
| open data.js | L1 if a listed regular file; separate read approval; no model |
| explain this code | L2, one model call with the verified bounded snapshot, or a safe input-budget failure |
| explain Python decorators | L2, standard bounded profile |
| think deeply about the security architecture | L3, one deep-profile conversation; no extra tool authority |
| go back | L1, previous successful location with current permission checks |
| go home | L1, project root; no blanket Ubuntu home access |

Example folder/file names must exist in the returned listing. Denial never triggers
model fallback. Read the `[Workload]` JSON line to observe the level and actual
invocation count without exposing private context. No Phase 6E feature is introduced.


### Phase 6D final-answer reliability fix

The provider ignores `message.thinking`, removes embedded thinking blocks, and
rejects recognizable unmarked deliberation prefixes. It rejects output-token
limit stops (`done_reason=length`), incomplete responses and unsupported completion
reasons before display or storage. Errors contain no generated text and do not
trigger retries. L2 uses `think=false`; L3 uses bounded thinking with its larger output
budget. A deep request may exhaust that budget and return a clear error.
No automatic budget increase or model replacement occurs.

Completion metadata absent from older adapters remains compatible; arbitrary
untagged prose cannot be reliably distinguished from an answer. Prefix detection
can reject a legitimate answer using deliberation wording. The installed model
passed the public live checks; other model variants and prompts still need testing. Existing historical SQLite
rows are not rewritten by this fix.


### L2 CPU reliability retesting

The standard Settings profile now reserves 768 output tokens, keeps thinking off,
and requests a concise direct answer (normally at most 150 words, one small example).
Only three recent complete turns are selected. This is guidance, not a guaranteed
word limit. Deep mode uses 2048 tokens with thinking enabled and brief-deliberation guidance. The context size is
unchanged at 8192; no claim of lower peak CPU or RAM usage is made.

Normal `done_reason=stop` succeeds even when token counts meet the budget. Explicit
`length` remains a truncation error, including when `done=true`; punctuation is not
proof of completion. Empty/absent/null reasons are accepted for older adapters,
subject to final-answer validation; this compatibility mode cannot prove truncation.
No custom stop sequences are added, and model-configured stops remain intact.

Run `.venv/bin/python -B -m friday.main --adaptive --diagnostics`, then ask
`do you know who am i`, `explain Python decorators`, and
`think deeply about the security architecture`. The first two remain L2, the last
L3. Only final answers or safe errors should appear. For a public synthetic live
comparison without conversation memory or file content:

```bash
PYTHONPATH=. .venv/bin/python -B tests/phase6d_l2_benchmark.py --live --baseline --samples 1
```

Four bounded requests compare the previous and current L2 defaults. The benchmark
prints only scenario identifiers, latency, call count, completion class, thinking
presence, validated token/duration counters and tokens/second when available.
It never prints prompts, answers, paths or exception text, and makes no retries.
At most two samples are allowed. Cold/warm model loading and execution order affect
comparisons; this is not a controlled measurement of whole-Ollama CPU/RAM use.


### L3 final-answer reliability

L3 retains thinking, with a hard total-output cap of 2048 tokens and brief internal
reasoning guidance followed by a final structured analysis (normally at most 350
words). It remains distinct from L2's 768 tokens, shorter-answer guidance and
thinking off. L3's timeout is 450 seconds and history limit 16 messages; context
setting remains 8192, with a conservative effective input cap of 5632 bytes.
Mandatory verified-file context is never silently truncated to fit.

Live testing reproduced thinking-only exhaustion at 1024 tokens. A 2048-token
thinking alternative with concise guidance completed, while a direct-answer 1024
alternative also truncated. Guidance is not a hard reasoning-token limit and no
output cap guarantees completion. There is no automatic retry, fallback, raw-trace
reuse or unlimited generation. A length stop still returns a safe error before
persistence. No unsupported thinking_budget option or stop override is used.
Model output cannot authorize tools; file/session privacy and permissions remain.

Start `.venv/bin/python -B -m friday.main --adaptive --diagnostics`, then request
`think deeply about the security architecture`. Expect L3, one model call and only
a final analysis or clear error. For a short public aggregate retest:

```bash
PYTHONPATH=. .venv/bin/python -B tests/phase6d_l3_benchmark.py --live --current-only --samples 1
# Compare previous and current L3 profiles (two requests):
PYTHONPATH=. .venv/bin/python -B tests/phase6d_l3_benchmark.py --live --samples 1
# Also measure the direct-answer alternative (three requests):
PYTHONPATH=. .venv/bin/python -B tests/phase6d_l3_benchmark.py --live --alternatives --samples 1
```

One attempt per mode/sample; at most two samples. The harness records only token
counts, completion class, latency, generation rate and thinking/final-presence
booleans. It never records prompts, answers, reasoning text, paths or file bodies.
Total output counts do not expose a verified reasoning/final token split. See the
report for actual results and cold/warm-order limitations; no lower CPU/RAM usage
or response-time guarantee is claimed.


### Final live verification and CPU limitations

Public L2 requests completed normally: the revised identity scenario took 23.96
seconds (278 output tokens), and Python decorators took 24.91 seconds (301 tokens).
The final L3 profile completed twice: 90.98 seconds (993 total output tokens) and
86.14 seconds (935 tokens). Each used one model call and returned only final content.
The owner independently confirmed working L3 analysis. These measurements use
public synthetic prompts; no reasoning text or private file content was recorded.

CPU-only qwen3:4b remains slow: responses can take tens of seconds or longer. The
owner observed a complete L2 Python explanation taking 74.5 seconds. Prompt length,
history, loading, requested detail and stochastic generation affect latency. The
small live sample is not a guaranteed speedup, success rate or answer-quality result.
Python CPU/RSS counters exclude Ollama. L3 can still exhaust its 2048-token cap;
there is no automatic retry or separate hard thinking-token reservation. Large
verified snapshots can exceed the conservative input cap and fail safely.

Adaptive usage remains explicit: `.venv/bin/python -B -m friday.main --adaptive`,
with optional `--diagnostics` for redacted workload metrics. Plain compatibility
mode does not apply adaptive inference profiles. No permissions are changed.

### Phase 6E: automatic conversational speech and confirmed voice input

Voice wraps the existing FridayAssistant and secure tool runtime. The microphone
is OFF at startup. No speech plays merely because FRIDAY starts. Automatic speech
for eligible conversational responses defaults ON when the offline TTS executable
is available. Startup prints `Speech Output: ON` and `Microphone: OFF`; if TTS is
missing, it prints an actionable warning and continues with speech OFF. Text mode
works without Whisper, models, eSpeak NG or valid voice configuration.

The old `/tmp/friday-voice-trial.81iQhN/` runtime dependencies disappeared.
Following explicit owner approval, Whisper.cpp v1.9.5 and checksum-verified tiny.en
were restored to `~/.local/share/friday/voice/`, with owner-local saved configuration.
Synthetic native-format decoding passed; live hardware validation remains pending.
See [durable setup and manual validation](docs/PHASE_6E_SETUP.md).
Store Whisper in `$XDG_DATA_HOME/friday/voice/` (default
`~/.local/share/friday/voice/`), with `bin/whisper-cli` and
`models/ggml-tiny.en.bin`. No dependency is installed/downloaded automatically
or added to Git. Base.en remains a separate optional comparison proposal.

Save owner-controlled JSON in `$XDG_CONFIG_HOME/friday/voice.json` (default
`~/.config/friday/voice.json`) **after valid dependencies are provisioned**:

```json
{
  "version": 1,
  "binary": "/absolute/XDG-data-directory/friday/voice/bin/whisper-cli",
  "model": "/absolute/XDG-data-directory/friday/voice/models/ggml-tiny.en.bin",
  "model_sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"
}
```

Use the actual absolute paths, not the example placeholders. `~` is expanded;
environment/shell expressions are not. Relative XDG directory values are ignored.
Configuration must be an owner-owned regular file, not a symlink, and cannot be
writable by other users; prefer mode 0600. Invalid/oversized/duplicate/unknown
fields and unapproved model pins fail safely. Explicit `--voice-binary`,
`--voice-model` and `--voice-model-sha256` values override saved fields. Complete
CLI overrides can recover from an invalid saved file; partial overrides require
the remaining saved fields. CLI arguments never rewrite the saved file.

```bash
# No microphone, playback, executable launch, or assistant/memory session:
.venv/bin/python -B -m friday.main --check-voice-config
# Optional explicit configuration location:
.venv/bin/python -B -m friday.main --voice-config /absolute/path/voice.json --check-voice-config
# Normal startup discovers saved configuration; audio remains OFF:
.venv/bin/python -B -m friday.main --adaptive
```

Inspection reports the configuration path, chosen dependency directory and
missing-file/checksum status. `verified_files` confirms files/model integrity,
not executable/model compatibility or hardware success. The setup guide provides
an offline synthetic-WAV compatibility check. Missing dependencies fail before
activation with an actionable message; invalid configuration leaves text mode
available. No paths enter shell commands.

At the interactive prompt, type `/voice`, then press Enter separately to activate.
Stay quiet until the flushed `CAPTURE READY — SPEAK NOW` cue. Native ALC256 capture
uses `hw:CARD=Generic_1,DEV=0`, 48 kHz stereo S16LE. Owned RUNNING status and an
advancing hardware pointer are required, including after 0.8 seconds of settling.
The **eight-second speaking window starts after the cue**, rather than sharing
eight seconds with readiness. Capture now finishes naturally at arecord's
twelve-second frame limit, including bounded quiet pre-roll and finalization
tail. The cue must complete within three seconds of launch. After the speech
window, finalization has a four-second wait bound; only natural exit 0 with a
complete finalized twelve-second native WAV is accepted. SIGINT/SIGKILL are
reserved for cancellation/failure cleanup; interrupted recordings are rejected.
RIFF/chunk lengths, PCM format/alignment and full frame count are checked before
decoding. Cleanup uncertainty ends the session and never falsely reports OFF.
Original pre-roll is preserved. There is no gain change, normalization, trimming, VAD,
denoising or microphone fallback. Tiny.en decoding keeps English, four CPU
threads, beam/best-of 5, temperature zero and no fallback; STT has a 60-second
timeout. Conversion belongs to the trusted CLI.

Inspect the escaped transcript. Type `y` only if it is accurate. Enter or `n`
discards it; type `/voice` again to retry. Ctrl+C cancels and returns to text.
Only a confirmed transcript reaches `FridayAssistant.respond(..., persist=False)`.
Permissions still require separate typed approval; speech cannot approve them.
Transcripts are never dispatched as CLI commands or shell expressions.

Explicit offline output is available through:

```text
You: /speak Hello, I am FRIDAY.
```

Only supplied text is spoken through `/usr/bin/espeak-ng` (English, 175 wpm).
Text travels through stdin, not shell/argv, files or SSML. The backend limits
input to 8192 UTF-8 bytes, rejects controls, uses a 60-second timeout and bounded
process-group cancellation, and handles missing executables/audio errors without
printing input or backend diagnostics. Ctrl+C cancels speech and returns to text;
SIGTERM unwinds cleanup before CLI exit. No microphone or assistant/tool/model
call occurs for `/speak`, and its text does not enter SQLite or chat history.
Automatic speech uses the same offline backend as /speak, with a session-owned
SpeechController. For eligible keyboard and confirmed /voice replies, FRIDAY
prints the complete answer, flushes terminal output, then speaks it once. Text
remains visible if speech fails. Playback is synchronous and interruptible,
with no queue, background worker, overlapping audio or extra Ollama request.

```text
You: hello
FRIDAY: Hello, Vigneshwar!
# Greeting is printed and spoken.
You: /q
Automatic speech disabled.
You: hello
# Greeting remains visible but silent.
You: /q
Automatic speech enabled.
You: hello
# Greeting is spoken again.
You: /speak Hello, I am FRIDAY.
# Manual speech plays once, regardless of the /q state.
```

/q toggles automatic output only. It never activates the microphone, invokes
Ollama/tools, changes permissions or writes settings/messages. Toggle confirmations
are printed without speech. State resets for each new CLI session. Exit, quit,
/bye and Ctrl+C retain their established behavior. No startup/unlock service exists.
`/q hello` prints `Usage: /q` without toggling or invoking the model. Malformed
`/voice` and `/bye`, empty `/speak`, and unknown slash commands receive CLI feedback
instead of becoming model requests. `/speak TEXT` continues to accept supplied text.
Type `hello` at the `You: ` prompt, rather than typing the prompt prefix yourself.

Speech eligibility comes from immutable ResponseMetadata assigned by the existing
assistant's trusted code paths. Deterministic L0 greetings can speak. A model
answer can speak only for a positively recognized public conversation request
and actual context carrying current-session public provenance. Whole-request
public-topic grammar includes questions such as `what is Python?`, `what is a
Python decorator?`, `explain machine learning`, and reviewed general computing,
science and mathematics topics. Public small talk and limited follow-ups are also
supported. This is deliberately conservative: arbitrary requests, pasted text,
personal/security findings, unclassified restored history and unknown sources
remain text-only. The catalog is in `friday/core/response.py`; it is not an LLM
classification and not a keyword blacklist. A question about passwords can qualify
as public education while harmless-looking private text cannot.

Tool results, directory listings, private file snapshots and their generated
explanations, permission messages, diagnostics, errors and unknown/untrusted
retrieved context have no automatic speech authorization. Common credential/key
structures are checked as a secondary safeguard after provenance checks. An LLM's
JSON label, model claim or printed string cannot grant speech permission. Public
history fingerprints are bounded, session-only and invalidated by content changes;
no speech permission is restored from SQLite. Answer generation, routing, tool
permissions and text-memory behavior remain unchanged. Thus a public model question
may remain silent if its actual prompt contains unclassified prior-session history.
/q does not override privacy classification. `/speak` is an explicit owner request,
so choose public text when other people may hear it.

The 8192-byte input bound and 60-second playback timeout can refuse or interrupt
long answers; terminal text is always retained. Expanding public speech coverage
requires reviewed provenance/request handling rather than silently trusting more
content. Piper remains a future SpeechBackend adapter with separate installation
and model approval; no Piper dependency has been installed.

Voice transcripts and responses remain session-only and do not enter SQLite or
reusable chat history. Private model-job messages/results are cleared per turn;
there is no global mutable persistence switch. Audio is in a private temporary
directory and deleted before typed transcript confirmation, including ordinary
errors, Ctrl+C and orderly SIGTERM. Existing bounded file context/navigation and
typed permission protections remain intact; explicitly approved persistent folder
grants retain their established behavior. No transcript/private text is logged or
included in diagnostics. Terminal scrollback can retain displayed text; SIGKILL
or a system crash can interrupt cleanup, and OS audio infrastructure can buffer
audio independently. Unlinking is not forensic erasure.

No live recording/playback test was performed by Codex for this increment. The earlier
owner-reported 8.33% WER across three recordings of one phrase is historical,
not a guarantee or evidence that this timing fix improves recognition accuracy.
The standalone capture scripts remain unavailable. Owner validation and an
independent model comparison remain necessary.

Offline regression tests (fake backends, no microphone or playback):

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_voice*.py'
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
.venv/bin/python -B -m unittest discover -s tests -p test_sync.py
```

### Preserved FRIDAY roadmap

| Version | Milestone | Status |
| --- | --- | --- |
| v0.4.0 | Phase 6D — Adaptive Workload | Complete |
| v0.5.0 | Phase 6E — Voice Interaction Foundation | IN PROGRESS; approved dependency restoration and owner validation pending |
| v0.6.0 | Phase 6F — Wake Word & Natural Conversation | Planned |
| v0.7.0 | Phase 7 — Ubuntu Desktop Control | Planned |
| v0.8.0 | Phase 8 — Vision & Screen Understanding | Planned |
| v0.9.0 | Phase 9 — Advanced Memory + Local RAG | Planned |
| v1.0.0 | Phase 10 — Stable FRIDAY Assistant | Planned |
| v1.1.0 | Phase 11 — Telugu Language & Voice Integration | Planned |

Later desktop integration may offer an owner-controlled greeting after unlock,
with microphone OFF until explicitly enabled and no autonomous command execution.
Phase 7 will add secure installed-app discovery (VS Code, Firefox, Files), trusted
recent-project and approved workspace/study shortcuts, and typed confirmation
for sensitive actions. Future internet tooling needs explicit network approval,
Wikipedia/trusted-source attribution, safe handling of retrieved content and no
private-data exfiltration. Phase 9 conversation imports need explicit approval
and local privacy/retrieval controls. Telugu STT/TTS and Telugu-English conversation
remain in Phase 11. None of these future features is enabled by the voice increment.

### Unreleased Phase 7A desktop enhancement

An interactive terminal launch prints a local-time greeting and speaks it once
through the existing offline eSpeak NG controller when speech is enabled. It then
shows **YOUR RECENT WORK**: the last three distinct accepted FRIDAY-managed
launch requests, stored in the existing SQLite database. Disabled or missing TTS
keeps startup in text mode; help, diagnostics and noninteractive startup do not
play a greeting. No microphone is activated.

Type `Open VS Code.`, `Open Firefox.`, `Open Downloads.`, `Open Documents.`,
`Open my FRIDAY project.` or `Open github.com in Firefox.`. Bare approved folder
opening now means a desktop launch; use `list downloads` or `list documents` to
browse through filesystem tools. Type `Show Q.`, `Show my recent work.`,
`What was I working on?`, `Resume my last work.`, `Resume yesterday's project.`
or `Resume previous projects.`. A number selects a stable saved ID only while
that menu is active, and every resume needs fresh typed exact-operation approval.
An intervening command closes the numeric menu. `/q` remains the speech toggle.

Reviewed native installations must be administrator-owned ELF executables at
fixed paths, with no writable parents or symlink components. A separate,
owner-authorized Snap adapter permits **only Firefox and VS Code app-only launches**.
It verifies fixed package/publisher IDs, active registration, immutable revision
mounts, trusted snapd/dispatch helpers and fixed runtime-provider registrations
before and after approval. The owner accepts these packages sourcing owner-writable
startup shell files; Code's classic confinement and package-supplied no-sandbox
flag are additional trust risks. FRIDAY adds no arbitrary flags or shell commands.
Flatpak, other Snap apps, arbitrary PATH executables and user scripts remain unsupported.
Snap project/file/URL arguments remain blocked: app-only approval is not an exact
path-handoff exception. No installation or ownership setting is changed.

Q remembers accepted launch requests, **not everything done inside external
applications**. Authorized process starts enter Q with an internal window-unverified status, including processes still running after the bounded launch wait. The compact menu shows location and application; `show Q diagnostics` exposes status and summary.
Failed/denied launches and voice-derived turns do not enter Q. No editor contents, history, keystrokes,
clipboard or windows are monitored. Only the reviewed `https://github.com/` link
is currently supported; private URLs, credentials, queries and fragments are
refused. Saved metadata grants no permission, and all targets are revalidated.

See [Phase 7A setup and security boundaries](docs/PHASE_7A_DESKTOP.md) and the
[enhancement report and acceptance commands](docs/PHASE_7A_ENHANCEMENT.md).
The [Q persistence fix report](docs/PHASE_7A_Q_PERSISTENCE.md) documents the
process-start outcome policy, SQLite migration and regression acceptance steps.
Six owner-approved real launch attempts ran through the actual CLI gateway. Visible GUI/folder outcomes still require owner confirmation; no release version changed. See the full audit for evidence and limitations.


`open files`, `open downloads`, `open documents`, and
`open my friday project folder` use **Ubuntu Files / Nautilus**, following the
owner's latest command requirement. This restores the native defaults from before
the managed-browser experiment. Exact Nautilus window ownership cannot be proved
through the reviewed API, so FRIDAY cannot safely close a previous window or
guarantee one native window. Every approved native request now attempts the
requested location, including repeats and Q resumes. No cooldown or previous
window receipt blocks it. Each attempt requires one exact-target approval and
consumes an actual-launch slot; the existing four-launch session limit remains.
`retry` is compatible but no longer required.
No unrelated window or Nautilus process is closed.

The real audit exposed a limitation in descriptor-pinned Nautilus targets: the
file manager retains a `/proc/<friday-pid>/fd/<pin>` URI. It cannot remain usable
after that FRIDAY process exits. Passing a normal canonical pathname instead
needs a separate owner security decision because Nautilus does not expose an
atomic directory-descriptor handoff. FRIDAY does not claim durable folder opening
or compositor visibility from process acceptance.

Named discovery uses existing filesystem boundaries: `find portfolio`,
`where is portfolio`, `show portfolio location`, `open portfolio in downloads`,
`open portfolio in vs code`, and `open portfolio from downloads in vs code`.
Unqualified searches use configured and persistently authorized roots only.
Explicit Downloads/Documents scopes require metadata-only `search_directory`
approval unless existing access covers them. Search is bounded to depth 3,
1,000 examined entries, 20 results and a cooperative two-second traversal budget;
permission waiting is excluded. Hidden entries, sensitive paths and symlinks are
skipped. No file contents are read, no grants are saved by search, and no hidden
monitoring is introduced. Multiple matches need a numbered exact-path choice.
An unspecified destination needs a VS Code/Ubuntu Files choice before launch;
regular files offer only VS Code. Searches and choices cost no application slot.
Native reviewed VS Code accepts validated descriptor-pinned targets with one
`open_project_in_application` approval. Snap Code project/file targets remain
unsupported by the app-only exception and fail clearly.

Existing explicit text-reading commands and references after a terminal directory
listing retain their prior behavior. Use a destination-qualified command for
desktop opening in that context. Ordinary known folder opening remains native.

Use `open friday browser`, `open downloads in friday browser`,
`open documents in friday browser`, and
`open my friday project folder in friday browser` for the separate managed GTK
window. `open my friday project` still uses VS Code.
First browser use requires separate typed `launch_browser` and `navigate_browser`
approvals. Further navigation, including `go back`, `go forward` and numbered Q
resume, requires fresh exact navigation approval but reuses the managed window.
History is bounded to 16 locations and changes only after renderer confirmation.
A hidden/unmapped window still answers health checks. An inconclusive IPC check
keeps the live renderer and prevents another launch; it never reuses old approval.
Use `show browser status` for bounded diagnostic codes without folder contents,
paths, IPC credentials or raw error text. Closing the window is detected on the next operation; reopening needs both
approvals and counts toward the unchanged four-process desktop limit. Navigation
inside an existing window consumes no launch slot.

Navigation displays the current approved location with contents hidden. Use
`list browser contents` for a bounded listing through the existing filesystem
permission gateway. Navigation grants no read access, and Home's existing read
restriction remains. The minimal GUI has no file opening/modification or arbitrary
folder entry controls; use terminal navigation commands. GTK uses installed system
Python/PyGObject, a private configuration/cache directory and local GIO backend.
There is no public IPC endpoint, shell, network request or filesystem watcher.

Q persists the last three distinct verified managed actions in SQLite. Managed
navigation records application-confirmed location with compositor visibility
unverified; legacy Nautilus entries keep their original backend and are labeled
Ubuntu Files / Nautilus. New location activities use `nautilus_location` or
`friday_browser_location`. Showing Q validates and semantically deduplicates legacy records without rewriting them. Accepted repeats normalize canonical application + target keys with stable IDs; superseded alias metadata is retained in a SQLite legacy archive. New explicit Browser workflows remain distinct. While its menu
is active, `resume Q 2 in friday browser` offers the saved approved location in
FRIDAY Browser with fresh approval; it records a distinct Browser activity after
confirmation, subject to the normal three-slot limit. Plain numbered resume uses
the displayed original application. Denials/failures
do not refresh Q. No completed external work is inferred. No packages or release
versions changed. App-only Firefox/VS Code Snap requests now attempt reviewed launches; visible GUI acceptance is pending. See the
[managed-browser report and exact acceptance steps](docs/PHASE_7A_MANAGED_BROWSER.md)
and [security design](docs/FRIDAY_BROWSER_DESIGN.md).

See the [browser lifecycle and window ownership repair report](docs/PHASE_7A_BROWSER_REUSE.md) for current behavior, limitations and manual GUI acceptance.
