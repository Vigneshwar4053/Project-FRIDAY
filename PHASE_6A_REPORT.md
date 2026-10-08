# FRIDAY v0.4 Phase 6A audit and implementation report

Audit date: 2026-10-08. Scope: repository diagnosis, Phase 6A implementation,
security fixtures, tests and desktop-opening design. No commit, push, merge, tag,
reset, rebase or staging operation was performed. No personal folder was enabled.

## A. Git and repository status

- Branch: `feature/safe-tool-system`.
- HEAD: `b43e8b33c53602e553b7db7ae3b6aa5c57a3743a`,
  `feat: integrate safe tool routing`.
- Initial working tree: clean, with no accidental untracked files.
- Upstream: `origin/feature/safe-tool-system`; ahead 0, behind 0.
- A read-only live `git ls-remote --heads --tags origin` confirmed branch tips and
  tags match local refs. No fetch or history modification was necessary.
- `main` and `origin/main`: `632d4db`, containing tagged v0.3.0.
- Tags: v0.1.0, v0.2.0, v0.3.0. No v0.4 tag exists.

| Milestone | Verified commit |
| --- | --- |
| v0.1 core assistant | f9d233c |
| v0.2 SQLite memory merge | 5417485, implementation c3ea202 |
| v0.3 model runtime/native synchronization merge | 632d4db, implementations b20c531/d2106d7 |
| v0.4 Phase 1 safe tool foundation | 79ca5c5 |
| v0.4 Phase 2 safe file tools | 65a11e0 |
| v0.4 Phase 3 Linux/system tools | f048e09 |
| v0.4 Phase 4 controlled computation | c584770 |
| v0.4 Phase 5 tool routing | b43e8b3 |

All expected historical commits exist. Phases 1–5 are committed and pushed on the
feature branch, and are not on main. Phase 6A is the new uncommitted work.
Recent phase commits were inspected with `git show --stat`.

Tracked files contain source, tests, README, ignore rules, native C sources,
Makefile and empty runtime-directory placeholders. No tracked database, generated
library/object/bytecode, or common credential-file candidate was found. Common
private-key, AWS-access-key and API-token signatures were scanned across all 11
reachable commits without a match; this is a heuristic, not proof of no secrets.
The local database contents and private user files were not opened.

`.gitignore` correctly excludes the current virtual environment, Python caches,
`.env` files, secrets directory, local data and sidecars, logs, native `.so`/`.o`
outputs. Existing ignored runtime artifacts remain ignored. It does not cover
all possible credential filenames or databases placed elsewhere; explicit future
patterns for such artifacts would be useful. No unrelated ignore changes made.

Intended review/commit candidates: README.md, friday/config/settings.py,
friday/main.py, friday/tools/files.py, friday/tools/filesystem.py,
friday/tools/presenter.py, friday/tools/router.py, tests/test_multi_folder.py,
and this report. The last two files are intentionally new/untracked. Runtime
artifacts, personal paths, databases and credentials should stay out of commits.

## B. Project health

The architecture is coherent: CLI composes Settings, OllamaProvider,
ModelManager, synchronization and MemoryManager; FridayAssistant first routes
intent through ToolRouter. Matched requests pass through immutable ToolRequest,
ToolManager schema validation and PermissionPolicy before filesystem tools enforce
FileSystemPolicy. Unmatched chat uses ModelManager and Ollama. There is no model
output tool-dispatch protocol.

Verified working components include SQLite transactions/session handling,
provider parsing/error handling, model selection/queue, Python/native mutual
exclusion, tools/permission schemas, filesystem checks, bounded arithmetic and
routing. No broken imports or currently failing tested components were found.
No definite dead code, harmful duplication or descriptor leak was identified.
Provider compatibility construction and native-startup fallback are intentional.
Native initialization can fall back to Python with a reported reason; runtime
native errors and rejected tools do not fall back. Unsupported model names fail
instead of silently switching models.

Unrelated modules were not rewritten. Live Ollama availability and actual Qwen
inference were not tested; provider tests use mocks. Desktop launching does not
exist. These are validation/scope limits, not reported implementation failures.

Existing concerns:

- Displayed file contents are persisted with turns and can enter subsequent
  Ollama context; authorization is not secret filtering or retention consent.
- Ollama uses an unbounded HTTP `response.read()`. Socket timeout is not a strict
  total deadline for a peer that continues slowly returning bytes.
- Without memory, conversation history/context grows without a limit. With
  memory, sent context is count-bounded, but in-process history still grows and
  message sizes are not generally bounded for unmatched chat responses.
- Process discovery scans all visible `/proc` entries without an entry budget.
- ModelManager/queue/registry are deliberately single-threaded; the native mutex
  protects provider execution, not the entire runtime.
- Invalid filesystem configuration fails closed but is not caught as a friendly
  CLI configuration error. Generic tool failures hide path details, but also hide
  the distinction between authorization, missing files and invalid encoding.
- Configured paths are trusted; root canonicalization can authorize a configured
  symlink target. Request-time symlinks remain rejected. Mounts and concurrent
  renames are not an OS-sandbox guarantee.

## C. Phase 6A implementation

Modified files:

| File | Change |
| --- | --- |
| friday/config/settings.py | Opt-in filesystem_read_roots and listing limit |
| friday/main.py | Production multi-root policy, project-only write roots |
| friday/tools/filesystem.py | Home expansion, unique aliases, write authorization, named enumeration limit |
| friday/tools/files.py | Bounded streaming enumeration, escaped names and truncation metadata |
| friday/tools/router.py | Explicit directory paths/aliases and reads with spaces/extensionless single tokens |
| friday/tools/presenter.py | General directory label and enumeration truncation indicator |
| README.md | Phase 6A configuration, limits, security and routing documentation |

Created tests/test_multi_folder.py and PHASE_6A_REPORT.md. No dependencies added.

Production keeps the project as its first/default root and only write root.
Additional roots are explicitly configured through the trusted Settings tuple,
empty by default. Absolute paths and home paths work; no username is hardcoded.
All roots must exist and be directories. The existing file size limit is 1 MiB.

Additional root basenames become case-insensitive aliases. Duplicate aliases and
project-entry collisions require absolute paths. The project basename does not
become an alias: this preserves `friday/tools/router.py` inside a FRIDAY root.
That collision was found by the production demo, fixed and regression-tested.
Roots overlapping the project retain pre-existing project write authority;
additional roots do not enlarge write authority. Default manager permissions
still require approval before writes; chat cannot route write_file.

Directory enumeration defaults to 100 entries, stats at most that many and consumes
at most one more to determine truncation. It never follows symlinks. Only the
bounded subset is sorted; results are not globally paginated or globally sorted.
The result includes path, entries, limit and truncated. Names are JSON-escaped,
including terminal controls, Unicode formatting and undecodable bytes. The
presenter independently caps 100 entries and 12,000 body characters with indicators.
A disappearing entry fails safely without a partial result. Memory scales with
the trusted configured entry limit rather than total directory size.

## D. Test and integration results

| Validation | Result |
| --- | --- |
| Original baseline | 248 passed |
| New Phase 6A tests | 28 passed |
| Final complete suite | 276 passed; 0 failures/errors/skips |
| Existing native/Python synchronization tests | 31 passed, including actual native backend |
| Existing filesystem tests | 27 passed |
| Existing routing tests | 28 passed |
| Existing computation tests | 30 passed |
| Existing tool/permission tests | 29 passed |
| Existing Linux/system tests | 30 passed |
| Syntax/compile without bytecode | 46 Python files passed |
| Production import checks | 34 modules passed |
| Native C strict warning/syntax check | Passed with -Wall -Wextra -Wpedantic -Werror |
| Forbidden execution API inspection | No eval/exec/os.system/os.popen/subprocess calls in production |
| git diff --check | Passed |

The full suite also covers CLI, memory, model runtime, provider and system tools.
Tests use temporary directories and mocks; no real user file was written by tests.

Production-component manual demo used real Settings composition, ToolRouter,
FridayAssistant, ToolRequest, ToolManager, default permissions, FileSystemPolicy,
tools and presenter. Only the model provider was replaced by a mock that raises
if called; memory was disabled to avoid writing the real database.

| Request | Result |
| --- | --- |
| what files are in this project | Successful project listing |
| list files in Downloads | Successful authorized temporary Downloads fixture |
| read friday/tools/router.py | Successful real project-source read |
| list files in /etc | Safely blocked; generic FAILED result, no data |

Qwen calls: zero for all four. Default Downloads authorization is absent and a
request fails safely. No personal filenames were displayed. The router source
body was omitted from demo output. Repository changes are implementation,
documentation and tests only; demo created files only in a temporary directory.

## E. Filesystem security findings

Traversal (`../`, nested parents, absolute parent components), absolute unauthorized
paths, unauthorized aliases, symlink escapes, nested/in-root symlinks and replaced
root symlinks were blocked. Existing hardlink checks still reject shared files.
Oversized files, invalid UTF-8/NUL text, directories as files, FIFOs and missing or
disappearing files fail safely. Malformed paths, including NUL and multiline
unauthorized requests, do not produce model fallback. Control characters and invalid
filesystem-byte filenames are escaped in listings. Listing reveals names/types
within authorized roots, never file contents.

Permission denial stops filesystem execution. Default write requests require
approval; even a write-allowing manager cannot create/overwrite files in additional
read-only roots outside the project. Explicit outside-root read/list requests
remain matched and final. Unmatched normal chat still calls the model.

Boundary rejection uses the existing generic FAILED ToolStatus rather than a new
DENIED classification. The presenter states that no model fallback was used.
There is no secrets denylist: authorized readable `.env`, credential or database
text could still be requested. Tests use public fixture text, not personal secrets.
Mount/rename races, hostile filesystem latency and content-retention risks remain.

## F. Future desktop opening — analysis only

Use a separate desktop-opening tool and explicit EXECUTE/approval permission,
not read_file and not a generic command tool. The router should form a structured
request; ToolManager should validate schema/permission, then a desktop policy should
validate both path and application. Confirmation should name the resolved file,
application and action, bound to a one-use request with a short validity period.

| Feature | Proposed approved handler |
| --- | --- |
| Photos | Explicit configured image viewer; approved image MIME types |
| Videos | Explicit configured video player; approved video MIME types |
| PDFs | Explicit configured PDF viewer; PDF signature/type checks |
| Folders | Explicit configured file manager; authorized existing directory |
| Trash | Fixed reviewed file-manager action for trash:///; no user-supplied URI |

Application allowlists should use trusted absolute executable paths. Combine
extension checks with bounded content-type detection, reject scripts, binaries,
executables, `.desktop` launchers and ambiguous/polyglot types, and avoid delegating
to arbitrary MIME associations. Review active-content/network behavior of viewers
and consider OS sandboxing for untrusted documents.

Launch with a fixed argument vector, shell=False, supported end-of-options handling,
minimal environment, controlled working directory, bounded diagnostics and managed
process lifecycle. Reject options, command fragments and arbitrary URI schemes.
Revalidate immediately before launch; where practical pass a pinned descriptor
with approved viewer support to reduce check/use races. An application reopening
an ordinary pathname weakens descriptor-based guarantees and needs explicit design.
Opening Trash must be a distinct fixed virtual resource, never authorization for
its contents. No launch, delete, restore or empty-Trash operation was implemented.

## G. Severity and next actions

| Severity | Finding/action |
| --- | --- |
| CRITICAL | None identified in tested Phase 6A paths; no claim of exhaustive absence |
| HIGH | Credential-bearing allowed roots plus saved file text/later model context: add content exclusions and retention/context policy before enabling sensitive folders |
| MEDIUM | Bound HTTP response size, history bytes, process enumeration and total operation time; add friendly fail-closed config errors and safe error classifications |
| MEDIUM | Document/enforce concurrency ownership; evaluate mount/rename races before use in a hostile filesystem environment |
| LOW | Listing is a bounded subset, without pagination; escaped names are display strings; broader ignore patterns and less ambiguous legacy open spelling would improve usability |

Immediately: keep personal roots disabled until deliberately reviewed; address
retention and credential exclusions before sensitive-folder use. The two Phase 6A
scope defects (unbounded listings and shared read/write root authorization) are fixed.

Recommended Phase 6B: user-owned root/alias configuration UI or file, configuration
validation, safe error categories, sensitive-path exclusions and explicit history/
model-context consent for tool content. This phase should not auto-enable folders.

Recommended Phase 6C: bounded search/pagination, explicit per-request resource
budgets, retention limits, safe tool audit metadata and broader runtime resource
hardening. Do not introduce recursive traversal without depth/entry/time limits.

Recommended Phase 6E: the reviewed desktop-opening architecture above, with fixed
approved apps, MIME policy, one-use approval and lifecycle/race handling. Trash is
opening only; deletion, restoration and emptying remain separate future work.

Phase 6A is ready for commit review under its documented trusted-local-filesystem
scope and default project-only configuration. Sensitive-folder deployment should
wait for the HIGH finding. Approval is still required for any commit or other
mutating Git action. Work stops after validation and reporting.
