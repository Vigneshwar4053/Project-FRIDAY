# FRIDAY v0.4 Phase 6B — Interactive Permissions and Privacy

FRIDAY is Vigneshwar's personal local-first terminal AI assistant. It uses
Ollama and qwen3:4b for practical help with programming, Linux, AI, authorized
cybersecurity, research, planning, and automation advice.

## Capabilities and limits

- Terminal chat with a consistent identity and SQLite session history.
- Local HTTP model provider, connection/response error handling, and clean exits.
- Requests `think: false` and displays only final answer content. The provider
  also removes embedded thinking blocks when Qwen ignores that option.
- Deterministic read-only tools through terminal chat; no cloud APIs or extra Python dependencies. Suggested
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
to the configured model for that follow-up.** No live model call is made to read,
list, ask for permission or interpret a permission choice.

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

### Tests, demo and Phase 6C roadmap

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

Phase 6C should add reviewed user-owned configuration/recovery tools, explicit
opt-in cleanup of legacy retained filesystem turns, safe error categories and
bounded search/pagination, plus broader response/history/time budgets. Phase 6D
should stress cross-process revocation, crashes, filesystem races, malformed stores
and prompt injection. Phase 6E requires a separate approved-app/MIME/EXECUTE
permission design; read grants never authorize application launching or Trash
operations. No desktop launcher is implemented here.
