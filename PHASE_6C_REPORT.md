# FRIDAY v0.4 Phase 6C — refined hybrid routing

## Objective and preflight

Refine the existing uncommitted Phase 6C implementation with semantic user-folder
resolution and voice-ready text, preserving the owner's Python ModelManager/native
C POSIX mutex architecture and the single ToolManager/permission execution pipeline.
Includes a small bounded session navigation manager; no speech capture, desktop launcher or replacement architecture.

- Repository: `/home/vigneshwar/Projects/FRIDAY`.
- Branch: `feature/safe-tool-system`.
- Committed HEAD remains `dba445fbbcb352fcf8469a4feafbec811082a358`:
  `feat: add interactive filesystem permissions and privacy controls`.
- Committed Phase 6B baseline: **370 passing tests**.
- Refinement preflight: expected intentional Phase 6C working changes, no unexpected
  files; **451 tests passed** before edits (370 + 81).
- Read the prior Phase 6C report and inspected existing routing/model/privacy changes.
  No AGENTS.md was found in the repository or checked parent instruction locations.
- Recorded upstream remains ahead 0 / behind 0; no network fetch performed.
- Existing tags: `v0.1.0`, `v0.2.0`, `v0.3.0`.
- Current combined working tree: **11 tracked files modified, 9 untracked files**, unstaged; see latest refinement record below.
- No commit, push, merge, tag, reset, rebase, stash, cherry-pick or user-work discard.

The owner reported live pre-refinement successes for Downloads/Desktop/Pictures and
ambiguities for photos/videos/bare pictures, plus erroneous navigation proposals.
These observations motivated the refinement. This implementation's new behavior
was verified offline; no claim of new live Qwen accuracy or CPU latency is made.

## Existing architecture inventory

| Component | Repository implementation |
|---|---|
| CLI/composition | `friday/main.py`: Ollama, shared ModelManager, MemoryManager, registry/runtime and direct TTY approval |
| Assistant | `friday/core/assistant.py`: deterministic priority, semantic fallback, private tool presentation, normal chat memory |
| Router | `friday/tools/router.py`: bounded immutable RouteDecision, existing commands, permission administration; added semantic fast path/refusals |
| Registry/schema | `registry.py`, `models.py`: immutable registered ToolSpec metadata, typed arguments, ToolRequest/ToolResult |
| Execution | `manager.py`: schema -> risk permission -> filesystem authorization -> registered implementation |
| Permissions | `permissions.py`, `access.py`, `grants.py`: default risk policy, exact-operation once scope, read/list folder persistence and revocation |
| Filesystem | `filesystem.py`, `sensitive.py`, `files.py`: roots, descriptor-relative no-follow traversal, identity/type checks, exclusions and bounds |
| System/computation | `system.py`, `computation.py`: existing narrow read-only system APIs and controlled computation |
| Model/native | `friday/models/`, `friday/providers/ollama.py`, `friday/sync/`, `native/sync/`: existing single provider/model and native POSIX mutex |
| Memory/privacy | `friday/memory/`, assistant filtering and `core/file_context.py`: SQLite ordinary chat, one-use private file snapshot |
| New resolver | `friday/tools/locations.py`: concept aliases, bounded XDG data parsing, semantic normalization; no permissions/execution |

Filesystem containment/descriptor algorithms, sensitive rules, persistent grant
logic, normal memory subsystem, native source/bindings and ModelManager remain
unchanged. Access gained only a typed denial exception for presentation; no scope
or approval-choice change. The deterministic router was extended, not replaced.

## Refined architecture

```text
User / voice-transcribed text -> Assistant -> deterministic ToolRouter
  recognized existing command -> original request/refusal
  simple known browsing concept -> SemanticLocationResolver -> lexical path
  bare explicit path -> exact original path
  navigation/application request -> controlled refusal
  unmatched -> lightweight gate
      ordinary/instructional chat -> existing memory-aware ModelManager
      action-like -> IntentTranslator -> same ModelManager/native mutex/provider
                  -> strict JSON/top-level validation
                  -> grounded semantic location normalization, when applicable
                  -> registered argument validation -> ToolRequest
All requests -> same ToolManager -> same PermissionPolicy
             -> Phase 6B filesystem authorization -> existing tool -> presenter
```

The resolver is shared by router and translator, independent of CLI presentation,
Ollama, permission decisions and tool execution. It never opens directory contents,
authorizes a root, searches or executes a tool. No duplicate model or execution
system. Semantic normalization cannot override an explicit path.

## Files delivered

Relative to committed HEAD:

| File | Status | Purpose |
|---|---|---|
| README.md | Modified | Refined architecture, aliases/XDG rules, privacy, tests, live plan and Phase 6D roadmap |
| friday/core/assistant.py | Modified | Existing semantic integration/private tool flow; share router's resolver |
| friday/core/file_context.py | Modified | Earlier Phase 6C bounded path-only immediate reference accessor, preserved |
| friday/providers/ollama.py | Modified | Earlier bounded structured intent mode on existing provider, preserved |
| friday/tools/router.py | Modified | Small alias/verb fast path, optional FRIDAY prefix, bare explicit paths, navigation/application refusals |
| friday/tools/access.py | Modified | Typed filesystem authorization denial, existing decisions/scopes preserved |
| friday/tools/models.py | Modified | Optional typed ToolErrorCategory on failure results, backward-compatible defaults |
| friday/tools/manager.py | Modified | Fixed error categories from exceptions; existing generic error/status and execution boundary preserved |
| friday/tools/presenter.py | Modified | Fixed public explanations from typed categories; no exception/path echo |
| friday/tools/intent_translator.py | New | Original hybrid planner/strict validator, refined location normalization and input gate |
| friday/tools/locations.py | New | Reusable semantic location resolver and safe XDG parser |
| tests/test_intent_translator.py | New | 81 original Phase 6C tests; model-specific cases now use unfamiliar wording rather than new fast commands |
| tests/test_semantic_locations.py | New | 87 additional deterministic/XDG/security/refinement tests |
| tests/phase6c_demo.py | New | Extended A–O temporary-fixture native/CLI/ToolManager demo |
| PHASE_6C_REPORT.md | New | Updated final report |

The refinement itself created two files (`locations.py`, its test module) and
refined eleven existing tracked/uncommitted Phase 6C files. The earlier provider
and file-context changes were preserved. All 370 committed tests are unchanged.
No settings changes, dependencies or SQLite migration. No private files modified.

## Semantic locations and XDG parsing

| Accepted semantic aliases | XDG key | Default if config file/entry is absent |
|---|---|---|
| photos, pictures | XDG_PICTURES_DIR | ~/Pictures |
| videos | XDG_VIDEOS_DIR | ~/Videos |
| downloads | XDG_DOWNLOAD_DIR | ~/Downloads |
| documents | XDG_DOCUMENTS_DIR | ~/Documents |
| music | XDG_MUSIC_DIR | ~/Music |
| desktop | XDG_DESKTOP_DIR | ~/Desktop |

Case-insensitive simple verb/alias grammar supports bare aliases, open/show/browse/
display/list, optional my/the, me and folder/directory. An optional `FRIDAY,` prefix
and natural sentence punctuation support transcribed voice input without requiring
spoken Linux syntax. `FRIDAY, open my photos.` deterministically resolves Pictures.
No giant sentence catalogue or additional inference for simple requests.

Personal `can you show me my photos?` and `take me to my downloads` now use the
expanded trusted grammar. Unfamiliar phrasing stays model-assisted: `can you inspect
my pictures folder?`, `what's in my pictures folder?`, `what did I put in my downloads
folder?`, `show me where my videos are`, and `what is inside my music folder?`.
The model identifies intent; trusted Python resolves the known concept.

XDG source is `$XDG_CONFIG_HOME/user-dirs.dirs`, otherwise
`~/.config/user-dirs.dirs`. Resolution reads at most **16,384 bytes + one overflow
byte**, at most **64 lines**, from a regular single-link file. All config parent
components/file are opened without following symlinks; nonblocking flags prevent
FIFO/device reads before type validation. No config file or folder is created.
Configuration is reloaded each resolution, without caching grants.

Accepted syntax: blank/comment lines and double-quoted `XDG_*_DIR="value"`
assignments, optional trailing comments, absolute UTF-8 paths or literal leading
`$HOME/`. Localized names/spaces are supported. Duplicate assignments, malformed
syntax, unknown variable/command expansion, controls, invalid UTF-8, traversal,
special/hardlinked/oversized config files and config symlinks fail closed. Backslash
escape syntax and `${HOME}` are intentionally unsupported. Missing file/entry alone
uses the conventional default. Malformed/unreadable config never silently falls
back. `$HOME` (disabled folder), root and relative mappings are unavailable; no broad
home/root authorization. A mapped nonexistent directory returns a safe path error.

XDG values are untrusted **location hints**, not new allowed roots. They can point
outside home, but containment/sensitive checks and the existing direct approval
remain authoritative. `/etc`, sensitive paths and symlinks remain blocked regardless
of mapping. No arbitrary config code is evaluated and no shell command obtains XDG
values. Only this narrowly specified config file is read for mapping, never its
contents in model prompts/history/errors.

Compatibility: existing deterministic configured-root aliases (`list files in
Downloads`) retain their original ambiguity/root rules. New semantic commands use
XDG mappings, which can differ from those configured-root aliases. Explicit paths
remain exact: `/Videos` never becomes `~/Videos`; `~/Videos` never becomes a
localized XDG directory. Bare explicit path input is a deterministic list request.
Existing explicit file read commands retain their original routing. For revocation of localized XDG grants, use the canonical
folder listed by `show authorized folders`; permission-command alias rules remain
unchanged.

## Structured schema, validation and allowlist

Original exact proposals:

```json
{"kind":"tool","tool_name":"list_directory","arguments":{"path":"~/Downloads"}}
{"kind":"chat","response":"A directory contains files."}
{"kind":"clarification","question":"Which file do you mean?"}
{"kind":"unsupported","reason":"This action is unavailable."}
```

Small semantic extension, **only** for list_directory:

```json
{"kind":"tool","tool_name":"list_directory","arguments":{"location":"pictures"}}
```

`location` must be a known lowercase alias, exclusive of `path`, grounded in
exactly one concept in the current user request, and unavailable for read/write
operations. Explicit path evidence prevents semantic replacement. Both the location
form and compatible original path forms (`Pictures`, `~/Pictures`, `photos`) pass
through trusted resolution. No repair of invented absolute model paths. Multiple
semantic targets fail rather than guessing one. Instructional/recognized launching
or unsupported navigation requests cannot be reinterpreted as an unrelated list operation. An internal
semantic-evidence flag is Python-owned and forbidden in model JSON.

JSON parsing and exact top-level/schema/registered READ_ONLY checks precede request
creation; normalized arguments undergo the same registry schema validation as
ordinary paths, then ToolManager validates again. Existing rejection rules remain:
unknown/duplicate fields, wrong kinds/types, arrays, nested/multiple calls, extra
text/markdown/code, unregistered/unsafe tools, unknown arguments, permission flags/
approval tokens, nonfinite JSON, control/invalid strings and shell syntax.
Intent-mode reasoning wrappers are rejected, not stripped into executable proposals.

Existing bounds: 4,096 input characters; 8,192 response bytes; depth 3; 16 aggregate
keys; 4,096 bytes per argument/reference; 1,000 display-text characters. All text
classifications are display-only. No evaluation, deserialization, automatic repair,
retries or execution of raw model text.

Explicit model tool allowlist remains **eight registered read-only tools**:
list_directory, read_file, file_info, system_info, memory_info, cpu_info, disk_usage,
process_status. Computation is deterministic. write_file remains unavailable to the
model; shell, privilege, delete/move/rename, installation, search and desktop tools
are absent. Registered names do not automatically become model-selectable.

## Permissions, failures and privacy

Every accepted semantic/deterministic request uses ToolManager, risk policy and
existing Phase 6B filesystem authorization. Allow once remains exact target and
operation, consumed even on failure. Always allow remains canonical folder and
descendants **read/list only**, persistent/revocable, never writes/execute; file_info
and disk_usage retain static-root access rules. Direct TTY input alone chooses
approval. Noninteractive/invalid/EOF/interrupted choices deny. No model-generated
permissions, store writes, parent broadening, alternate tools or fallback after denial.

Sensitive paths/content, size/list bounds, no-follow descriptor traversal,
regular/single-link file checks and identity/race protections are unchanged.
Malformed permission storage still denies; XDG does not recover or bypass it.

Safe error classification adds an optional typed category to ToolResult, leaving
FAILED/status behavior and `Tool execution failed.` compatibility intact. The
presenter maps categories to fixed text: permission denied, path unavailable,
not a directory, or request blocked/invalid. No exception strings, private paths,
store details or sensitive existence metadata appear. Sensitive requests are
blocked before private target inspection. Invalid proposals/configuration and
unsupported navigation/launching get controlled separate messages. No retry.

All semantic browsing, tool outputs/proposals, denials, permission prompts/decisions,
private follow-ups and candidate chat remain out of SQLite and ordinary chat context.
Intent prompts contain the current request, compact tool/alias descriptions, and
only when explicitly needed one bounded immediate file path. They never contain file
bodies, directory output, XDG mapping contents, full chat history or permission-store
records. ModelJob messages/results/errors are scrubbed on completion/failure/interrupt.
Ordinary chat memory remains functional. The private one-use file snapshot still
supports explicit immediate explanation, outside planning and persistent memory.

No new pending clarification state: bare `pictures` independently answers the owner's
observed clarification scenario as a complete new request. Unrelated replies cannot
trigger guessed paths. Existing one-file context expiry/
shutdown/cancellation via incompatible turns is preserved; larger clarification and
general navigation/search is deferred; bounded session navigation is documented below.

Old SQLite rows/backups can retain pre-Phase-6B file bodies or unlabelled derived
answers; no automatic deletion/rewrite and no guarantee of secure RAM/disk erasure
or retention control inside the external local model process.

## Performance and native integration

Fast known-folder requests make **zero model calls** and one bounded config read.
Existing deterministic commands remain zero-inference. Unfamiliar phrasing uses
one bounded structured response on the existing ModelManager/native mutex/provider.
Structured CHAT includes its answer in the same call, avoiding duplicate inference;
that candidate lacks previous-chat context and is session-only for privacy.

Existing intent mode: JSON format, think=false, 512 requested output tokens,
65,536-byte HTTP envelope limit and unchanged configured timeout. No retries,
background workers, extra model/client instances, preload or multi-tool loops.
Normal conversation/provider behavior remains unchanged. Native C/source/bindings
and ModelManager are unchanged; the extended demo uses the actual native mutex.
This preserves the architecture for Phase 6D Adaptive Workload Management.

## Tests and final validation

| Check | Actual result |
|---|---|
| Committed Phase 6B baseline | 370 passed |
| Initial uncommitted Phase 6C baseline | 451 passed |
| Earlier Phase 6C translator tests | 81 passed; model cases use unfamiliar wording |
| New refinement tests | **87 passed** |
| Additions after semantic refinement | **168 tests** |
| Semantic refinement full suite | **538 passed** |
| Session navigation regression tests | **44 passed** |
| Navigation refinement suite | **582 passed**, zero failures/errors/skips |
| Latest file-reference suite | **649 passed**, zero failures/errors/skips |
| Failures / errors / skips | **0 / 0 / 0** |
| Permission/privacy security | 94 passed |
| File tools | 27 passed |
| Multi-root filesystem security | 28 passed |
| Deterministic routing | 28 passed, committed tests unchanged |
| Tool validation/permissions | 29 passed |
| Native/Python synchronization | 31 passed, no skips |
| Native build | `make -C native/sync` succeeded; existing binary up to date, no C edits |
| Syntax | 57 Python source/test files parsed |
| Production imports | 40 modules imported |
| Forbidden execution inspection | No production eval/exec/os.system/os.popen/subprocess call or shell=True found by AST scan |
| Whitespace | git diff --check passed |
| Extended offline demo | A–O passed |

Full suite also covers existing memory, Ollama, CLI, model-runtime, system and
computation behavior. Automated tests do not require live Ollama/network, and all
configuration/data fixtures are temporary. Tests cover every requested A–Z group:
semantic aliases, exact paths, unknown/ambiguous targets, launch/play/navigation
refusals, normal chat, direct permission scope/denial/revocation, sensitive/symlink
protection, malformed/forged model JSON, private retention, localized/malformed XDG,
missing directories, typed errors and no retries. Original 370 tests are unchanged.

## Controlled demo and owner live plan

Run `PYTHONPATH=. .venv/bin/python -B tests/phase6c_demo.py`.

| Case | Verified offline behavior |
|---|---|
| A: List files in Downloads | original deterministic listing, zero model calls |
| B: Open Downloads | trusted semantic fast path, direct CLI approval, zero model calls |
| C: What's inside Downloads? | validated location proposal, trusted mapping, authorized listing |
| D: RAM request | existing memory_info through ToolManager |
| E: How do I open Downloads? | normal chat, no tool |
| F: Open that file | clarification, no tool |
| G: rm -rf request | unsupported, no model/tool |
| H: Sensitive SSH path | blocked before approval, no model |
| I: Open Downloads + Deny | no directory tool execution or model retry |
| J: Hello FRIDAY | ordinary memory-aware response |
| K: FRIDAY, open my photos. | localized XDG Pictures fast path, zero model calls |
| L: Unfamiliar pictures wording | location proposal -> trusted localized mapping -> normal permission pipeline |
| M: go back from /Downloads | unsupported navigation, no model/tool |
| N: /Videos | preserved absolute path, blocked; no home replacement |
| O: ~/Videos | exact explicit home path, permission-controlled listing |

Six total fake-model calls for A–O; only ordinary E/J chat retained in SQLite.
Real composition, native mutex, CLI input adapter, permissions and ToolManager
were used, with all state under temporary directories. No real personal files read.
Owner live observations are separate; new Qwen behavior/latency has not been verified
by this implementation run.

With existing qwen3:4b/Ollama service, run `.venv/bin/python -B -m friday.main`.

| Owner input | Expected refined behavior |
|---|---|
| open photos | Fast XDG Pictures listing, prompt if unauthorized |
| pictures | Same independent fast request |
| open videos | Fast XDG Videos listing, not playback |
| open downloads | Fast XDG Downloads listing |
| open Desktop | Fast XDG Desktop listing, case insensitive |
| show my documents | Fast XDG Documents listing |
| what is inside my music folder? | One Qwen proposal, trusted Music mapping and permissions |
| how do I open Pictures in Ubuntu? | Normal instructional chat, no tool |
| play a video | Unsupported playback, no tool/model |
| go back | Revisit a prior successful listing with fresh permission checks, or report no previous directory |
| /Videos | Exact absolute path, safe failure outside allowed/eligible roots |
| ~/Videos | Exact home path, approved listing; no XDG remapping |

Use Deny unless intentionally willing to show personal filenames. Use public
fixtures for reads; do not authorize private documents just to validate semantics.
Test a refusal/denial and verify no retry or alternate operation. A missing/disabled
folder must report an error, not choose a replacement. README includes runnable
focused/full/native/demo commands and the same live plan.

## Remaining risks, limitations and next phase

| Severity | Finding |
|---|---|
| CRITICAL | No new execution/authorization bypass found in reviewed code/tests; this is not a formal proof. |
| HIGH (existing) | Legacy SQLite/backups may retain old file content/unlabelled derived text. Any cleanup requires explicit owner approval. |
| MEDIUM | Unfamiliar phrase accuracy/latency remains unverified live; lexical grounding constrains target evidence, not full semantic correctness. |
| MEDIUM | Sensitive exclusions are heuristic; hostile filesystem/config changes and local model/OS memory retention remain trust assumptions. No comprehensive DLP/OS sandbox added. |
| MEDIUM (existing) | Normal-chat response/history resource budgets remain broader hardening work; only intent/config operations are newly bounded. |
| LOW | Strict XDG syntax rejects shell escapes/expansions and malformed files globally. Missing config uses conventional English folder defaults; nonexistent/disabled folders do not resolve successfully. |
| LOW | Six folder concepts/nine English aliases; localized XDG filesystem names supported, not a complete multilingual speech interface. |
| LOW | Pre-existing configured-root aliases and new XDG semantic concepts can name different folders. Explicit paths disambiguate; no roots are silently granted. |
| LOW | No general pending clarification state; ambiguous multi-concept requests fail or clarify, never guess. Token limits may cause safe invalid-proposal failures without retry. |

Phase 6D is **Adaptive Workload Management**, per the owner: retain shared native
synchronization and fast paths while measuring CPU inference, bounded queue/
response/context budgets, timeouts and cancellation. No new model process manager.
Broader navigation/search needs a separately reviewed future permission-scoped design.
The bounded session navigation requested by the owner is implemented below.
Phase 6E desktop opening requires approved applications/MIME types, executable
restrictions, exact authorized paths, direct confirmation and safe process arguments
without a shell. Read/list grants never authorize GUI launches or Trash changes.

**Refined Phase 6C is ready for owner review.** Offline tests/security/demo pass;
owner live semantic tests remain to be performed. All Phase 6C changes are preserved
and uncommitted. Stop for review and explicit Git authorization.

## Session-aware navigation refinement — final delivery

### Baseline and scope

Repository `/home/vigneshwar/Projects/FRIDAY`, branch `feature/safe-tool-system`,
HEAD `dba445fbbcb352fcf8469a4feafbec811082a358`. The expected uncommitted Phase 6C
work was preserved. Before navigation edits, **538 tests passed**; the committed
Phase 6B baseline remains 370. No repository-specific AGENTS.md was found. No Git
mutation, network operation or real personal file access was performed.

### Architecture and changed files

`friday/core/navigation.py` is a new per-assistant NavigationManager. It plans
read-only ToolRequests from bounded successful listing snapshots. Assistant core
integrates these plans with its existing private ToolManager execution path and
clears state on shutdown. All semantic, deterministic and hybrid successful
listings update the same manager; normal chat/model output never creates children.
The translator receives no navigation snapshot and does not construct child paths.
Validated relative model basenames must match the trusted cache before execution.

Changes for this refinement:

- Created `friday/core/navigation.py` and `tests/test_navigation.py`.
- Modified `friday/core/assistant.py` for session lifecycle, planning and recording.
- Modified `friday/tools/files.py` to add descriptor-derived directory identity
  metadata and no-follow child directory identities to bounded results.
- Modified `friday/tools/models.py` with typed request-local DirectoryGuard and
  DirectoryIdentity. Guard metadata is not part of the model JSON contract.
- Modified `friday/tools/filesystem.py` and `friday/tools/access.py` to check cached
  identities before prompting and again against open descriptors during execution.
- Modified untracked `friday/tools/locations.py` to allow `enter` for standard
  semantic folders, preserving their precedence.
- Updated `tests/test_semantic_locations.py` only to replace its superseded
  expectation that all `go back` requests are unsupported.
- Extended `tests/phase6c_demo.py`, README.md and this report.

Navigation-refinement combined working tree: **11 tracked modified files and 8 untracked
files** (19 files total at that point), including the previously uncommitted implementation.
No native synchronization source or memory subsystem was modified by navigation.

### Semantics, authorization and privacy

`open` / `enter` / `go into` resolve a visible child from the current successful
listing. Optional FRIDAY invocation, polite prefix, articles and folder suffixes
support voice-style input. Unknown names do not become trusted paths. Casefold
collisions clarify; exact quoted spelling can disambiguate. File and symlink
entries are refused as navigation targets. Controls/invalid Unicode are excluded.
Standard semantic folder concepts take precedence, while explicit absolute and
home-relative paths keep their meaning. Existing explicit read commands remain.

`go back` visits a previously successful location from a maximum 16-entry history;
it does not infer a parent. `go home` means the configured FRIDAY project root.
This default was stated while the optional preference question was pending; it
preserves Phase 6B's prohibition on blanket Ubuntu home access. Successful home
listing clears history. Failure/denial never advances or clears navigation state.
Current child names are bounded to 100 returned entries, not a complete directory
index. Only successful matching request/tool results can update the snapshot.

Every plan still uses ToolManager schema validation, PermissionPolicy,
FilesystemAccess, FileSystemPolicy and the registered listing tool. Cached
identities merely reject stale targets; they do not authorize access. A parent
Allow once requires a separate child decision and fresh approval on return.
Persistent read/list descendants remain permitted as before; writes/execution are
not added. Revocation remains authoritative even with an existing snapshot.
Sensitive-path, traversal, symlink and descriptor-relative protections remain.
Cached parent and target identities are rechecked on descriptor traversal, including
replacement races during approval. No denied request is retried through Qwen.

State is session-only, never sent to the model or written to SQLite, and cleared
at shutdown. Tool bodies, private listing results, grants and permission choices
retain Phase 6B/6C privacy filtering. Older database rows/backups remain untouched.

### Results and demonstration

44 new navigation tests; **582 total passing tests** = 370 committed baseline +
81 initial hybrid + 87 semantic refinement + 44 navigation. Zero failures, errors
or skips in the final full run. The original 538 tests continue to pass after one
semantic test expectation was updated for the newly authorized navigation feature.
Tests cover child/back/home, fresh approval, denial, persistent scope, revocation,
sensitive/symlink targets, case ambiguity, files, missing/replaced directories,
replacement during approval, bounds, shutdown, SQLite privacy, semantic priority,
exact paths, and trusted normalization of relative hybrid proposals.

The temporary-fixture production-component demo now also performs
Downloads → portfolio → back → project home. It passes with fresh direct CLI
approvals, zero model calls for navigation, actual native mutex synchronization,
and a fake model provider. Existing hybrid/security demo cases also pass. This is
not a claim of live Qwen accuracy; owner live testing is still required.

### Remaining limitations and next phase

- CRITICAL/HIGH: No new finding established by this review and test scope.
- MEDIUM: Device/inode identity checks mitigate replacement but cannot guarantee
  protection against inode reuse or all concurrent renames. Existing same-user
  OS/memory trust and heuristic sensitive exclusions still apply.
- LOW: Only returned visible children can be selected; truncated/unusual-name
  listings may require an explicit path or relisting. History is bounded and
  session-only, with no forward navigation, recursive search or indexing.
- LOW: “Go home” is the project root. Arbitrary path-relative conversational
  navigation, deictic folder references and comprehensive speech/multilingual
  interpretation remain outside this small manager.

Phase 6D adaptive workload management should preserve these fast paths and the
shared native mutex while measuring inference budgets and cancellation. Broader
navigation/search and Phase 6E desktop opening require separate scoped designs.
Ready for owner review after final checks; all changes remain uncommitted.

### Navigation verification record (prior refinement)

| Check | Actual result |
|---|---|
| Full suite after all code changes | 582 passed in 1.660s; zero failures/errors/skips |
| Navigation-specific suite | 44 passed |
| Filesystem permission/security suite | 94 passed |
| File tools | 27 passed |
| Multi-folder filesystem security | 28 passed |
| Deterministic tool routing | 28 passed |
| Semantic/XDG security | 87 passed |
| Hybrid intent validation/integration | 81 passed |
| Native build | `make -B -C native/sync` rebuilt successfully with configured C11 warning flags |
| Native synchronization | 31 passed after rebuild |
| Syntax/import and forbidden execution API inspection | Passed; syntax checked 59 Python files, imported FRIDAY modules excluding executable __main__ |
| Production-component temporary-fixture demo | Passed, including navigation; fake provider, actual native mutex and CLI approvals |
| `git diff --check` | Passed |
| Final HEAD/branch | dba445f / feature/safe-tool-system, unchanged |
| Final Git status | 11 tracked modified + 8 untracked; all Phase 6C work remains uncommitted |

No eval/exec, os.system/os.popen, shell=True or subprocess launching was added.
The syntax checker compiles ASTs for validation only; it is not production execution.
No live model or personal-directory accuracy claims were made.

## Context-aware file references and voice refinement — latest delivery

### Preflight and architecture

Branch `feature/safe-tool-system`, HEAD `dba445f` unchanged. The intentionally
uncommitted Phase 6C implementation was inspected and preserved. Preflight full
suite: **582 passed in 1.650s**, zero failures/errors/skips. Read current report,
router, navigation cache, XDG resolver, translator, manager/registry/schema,
filesystem permission flow, file tools, presenter and temporary context handling.
No repository AGENTS.md was found. No reset/stash/commit/push/merge/rebase performed.

The existing NavigationManager now retains trusted regular-file identities as
well as directory identities. Existing bounded listing results supply the type,
name and no-follow stat metadata; no model/chat assertion can create trusted entries.
The same per-session cache holds at most 100 returned children and 16 prior visited
locations. File bodies are not added to that cache. No second router/execution or
permission system was introduced.

```text
Current request → deterministic routing + trusted listing-reference resolution
                → exact read_file or list_directory ToolRequest
                → ToolManager → PermissionPolicy → Phase 6B filesystem approval
                → descriptor-relative identity recheck → existing registered tool
                → deterministic bounded presentation
Optional explicit explanation → existing bounded temporary file snapshot
                              → same ModelManager/native mutex → private answer
```

The existing DirectoryGuard was extended with an exact read/list operation field.
Despite the legacy name, it now also binds a regular-file identity. The field is
trusted backend metadata, excluded from model JSON, grants no permissions, and
cannot attach to write/execute requests. Metadata-only preflight uses no-follow
O_PATH for files; authorized execution rechecks cached parent and file descriptors
before reading. Existing size, nlink, sensitive-content and UTF-8 safeguards remain.

### Files changed in this refinement

Created `tests/test_file_references.py` (67 offline regressions). Modified:

- `friday/core/navigation.py`: file/dir distinction, exact names and bounded stem/
  extension references, private clarification, ZIP refusal, guarded read proposals.
- `friday/core/assistant.py`: route precedence and optional explanation via the
  existing temporary context; failed reads never invoke the model.
- `friday/tools/files.py`: regular-file identities in listings, typed unsupported
  content errors with unchanged strict UTF-8/non-NUL requirements.
- `friday/tools/models.py`: read/list operation binding and unsupported-content
  category; strict model proposals still cannot set trusted guard fields.
- `friday/tools/filesystem.py`: no-follow metadata preflight and actual descriptor
  identity verification for guarded reads.
- `friday/tools/manager.py`, `friday/tools/presenter.py`: safe unsupported-text
  message; generic internal error string retained for backward compatibility.
- `friday/tools/locations.py`: singular picture/photo aliases and bounded polite,
  personal-location/take-me-to grammar; XDG parsing/authorization unchanged.
- `friday/tools/router.py`: instructional questions remain unmatched chat rather
  than accidentally treating “show me how to read data.js” as a file operation.
- `tests/test_intent_translator.py`, `tests/test_navigation.py`,
  `tests/test_semantic_locations.py`: model-only fixtures use unfamiliar `inspect`
  wording now that previous voice phrases are fast; obsolete directory-only file
  test now verifies `enter` type mismatch. No committed test was changed.
- `tests/phase6c_demo.py`, README.md and this report.

Combined Phase 6C state: 11 tracked modified + 9 untracked = 20 files. The new
file-reference test is the only file newly created in this refinement. Native C,
SQLite memory modules, CLI permission adapter and provider remain unchanged here.

### Behavior and privacy

Listed files support `open/read/show data.js`, `what's in data.js?`, `what have in
data.js`, `show me index.html`, and an unambiguous `read the index file` stem.
Listed folders still support open/enter/show-folder. Case collisions or multiple
stem/extension candidates clarify, never search or guess. Unknown contextual file
references are private clarifications rather than normal model chat. Explicit paths
and standard semantic location precedence remain. Reads do not update directory
location or back history. File paths and snapshots are not sent to intent planning.

A parent Allow once does not authorize a read; read_file needs its own existing
Phase 6B decision. Persistent read/list grants behave as before. Denial/failure
returns no file contents and does not trigger a model workaround. Cached file or
parent replacement and symlink targets fail closed, including replacement during
approval and reads under built-in project access.

Regular UTF-8 text is accepted after the existing no-NUL, size, single-link,
path/content privacy checks. Extension alone never proves text. Binary/invalid
UTF-8 receives a safe unsupported-content message; terminal controls in otherwise
supported text remain escaped by the existing presenter. This is not comprehensive
MIME classification. ZIP contextual references are refused before bytes, grants
or model calls. `.zip file` identifies only unique visible regular-file candidates;
multiple matches clarify. No archive extraction/inspection, file execution or GUI
application launch was added.

Explicit explain/summarize requests perform one verified authorized read followed
by one model explanation using the existing one-item 16,384-byte temporary JSON
snapshot and untrusted-data system instructions. The explanation is not interpreted
as a proposal and cannot authorize tools. Denied, missing, replaced, binary or
sensitive reads make zero explanation calls. Failed/interrupted explanations are
not retried; verified authorized text is returned with a controlled failure notice.
Snapshot and model-job content are scrubbed; body and derived explanation are never
saved to SQLite or normal history. Ordinary chat memory remains. Old rows/backups
are not rewritten or deleted.

Personal-location fast paths now include “FRIDAY, can you take me to the place
where I keep my pictures?”, “take me to where I keep my pictures”, “can you show
me my photos?”, singular “open my picture folder”, and “take me to downloads”.
They cost zero Qwen calls and use trusted XDG mapping plus ordinary approval.
Unfamiliar phrasing still uses the same translator and strict validator. General
photography/instructional questions remain chat; application requests remain refused.

### Test and demonstration results

**67 added tests**, **649 total** = 370 committed Phase 6B + 81 hybrid + 87 semantic
+ 44 navigation + 67 file references. Final verified counts/checks are recorded below. Existing 582 tests remain passing, with uncommitted model fixtures
updated to keep testing translation after requested phrases became deterministic.

New tests cover known-file reads, stem/case ambiguity, read denial and parent
Allow once isolation, repeated reads, missing/changed files, changed parent,
symlink/sensitive/oversized/binary content, archive selectors, SQLite and job-record
privacy, explanation failure/interruption and forged tool-like content, single
execution, navigation history, project-root replacement checks, voice fast paths,
instructional questions and application refusal.

Temporary-fixture demo now shows portfolio → authorized JS/HTML reads, ZIP refusal,
back/home, and a verified private explanation using actual production ToolManager,
CLI approval and native mutex with a fake provider. No real personal document was
read. No live Qwen accuracy is asserted. Owner test commands and expected behavior
are in the new README file-reference section.

### Security review and remaining limitations

- CRITICAL/HIGH: No new unresolved finding identified within this offline review.
  A regression test caught `app.js` being mistaken for an application word and
  bypassing the cached identity check; token matching was corrected, and the
  project-root replacement test now passes.
- MEDIUM: Device/inode checks cannot eliminate inode reuse or in-place concurrent
  edits. Text reads are bounded and verified but not atomic filesystem snapshots.
  Existing heuristic sensitive-content rules and same-user OS/RAM trust remain.
- MEDIUM: Explicit model explanations may be inaccurate or cover only the truncated
  16-KiB snapshot. Untrusted-data prompts limit instruction influence but do not
  prove semantic prompt-injection immunity; output cannot invoke more tools.
- LOW: Contextual reference grammars and nine English location aliases are bounded,
  not unrestricted multilingual speech understanding. Unknown/unreturned names
  need relisting or explicit paths; no search/indexing or pending conversational
  clarification engine is added.
- LOW: No MIME-complete detector, archive browser or desktop launching. Valid UTF-8
  without NUL is the existing supported-text rule; an extension is not a guarantee.

Ready for review after final verification. Phase 6D was not started. All Phase 6C
work remains uncommitted with original HEAD and branch preserved.

### Latest final validation record

| Check | Exact result |
|---|---|
| Full suite | **649 passed in 2.227s; failures 0, errors 0, skips 0** |
| New file-reference suite | **67 passed** |
| Navigation suite | 44 passed |
| Semantic/XDG suite | 87 passed |
| Hybrid intent suite | 81 passed |
| Filesystem permission/privacy suite | 94 passed |
| File tools | 27 passed |
| Tool routing | 28 passed |
| Multi-folder filesystem security | 28 passed |
| Native synchronization | 31 passed |
| Existing native build command | `make -C native/sync`: success, already up to date; no native source change |
| Production-component temporary demo | Passed including new verified reads, ZIP refusal and explanation case P; fake model, actual native mutex and CLI approval |
| Syntax checks | 60 Python source/test files parsed and compiled in memory |
| Import checks | 41 production modules imported, excluding executable __main__ |
| Forbidden execution inspection | AST scan clean: no production eval/exec/os.system/os.popen/subprocess call or shell=True |
| Whitespace | `git diff --check` passed |
| Git | feature/safe-tool-system, HEAD dba445f, unchanged; 11 tracked modified + 9 untracked |
| Persistence | Temporary-fixture SQLite checks confirm no file bodies, listing snapshots, permission decisions or file explanations persisted |

The final combined suite adds 279 tests over committed Phase 6B, of which 67 belong
to this refinement. Existing user work remains available for review. No commit,
push, merge, reset, rebase, stash, tag or Phase 6D implementation occurred.
