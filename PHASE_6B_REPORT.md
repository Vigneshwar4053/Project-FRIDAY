# FRIDAY v0.4 Phase 6B — Interactive Permissions and Privacy

Date: 2026-10-08. Implementation, security tests and documentation are complete.
Changes remain unstaged and uncommitted. No commit, push, merge, tag, reset or
rebase was performed. No desktop application launching or Trash operation was added.

## A. Git baseline

| Item | Verified baseline |
| --- | --- |
| Branch | feature/safe-tool-system |
| Starting/current HEAD | 0a4405ec9f18b38b93308f5d632feffe9e6b5172 |
| Commit subject | feat: add secure multi-folder filesystem access |
| Initial working tree | Clean; no unexpected changes or untracked files |
| Phase 6A commit | Present at HEAD, including its 28 new tests and report |
| Tags | v0.1.0, v0.2.0, v0.3.0 |
| Upstream | origin/feature/safe-tool-system; cached ahead 0 / behind 0 |
| Main | 632d4db, v0.3.0 |
| Remote | https://github.com/Vigneshwar4053/Project-FRIDAY.git |
| Previous baseline | 276 tests passed, zero failures/errors/skips |

The expected branch, starting commit and baseline all matched. Upstream status is
based on existing remote-tracking refs; this task did not fetch or query live GitHub.
Git history was not modified. Final modified/untracked files are the implementation,
tests, demo, README and this report listed below; none are staged. Runtime permission
files remain under the already ignored data directory by default. No real user
permission store was created during tests or the demo.

## B. Architecture

### Read/list decision flow

```text
CLI input -> FridayAssistant -> deterministic ToolRouter -> immutable ToolRequest
  -> ToolManager schema validation -> existing RiskPermissionPolicy
  -> FilesystemAccess (filesystem-only direct approval if eligible and unauthorized)
  -> FileSystemPolicy (operation-scoped authorization, exclusions, descriptor checks)
  -> filesystem tool -> ToolResult -> ToolPresenter -> user
```

The existing risk policy remains authoritative before any approval prompt. A
policy denial/approval-required result stops the request. Filesystem approval is
an additional narrow read/list decision, not a generic risk-override API. Qwen and
file contents have no decision or dispatch channel.

Permission administration has a separate deterministic route:
ToolRouter.permission_command -> ToolManager.filesystem_access.command -> validated
store operation/direct CLI prompt -> user. These commands never become normal chat
turns, model prompts or file-tool dispatch. Registry size remains ten existing tools.

### Allow once

An immutable FileApproval records the operation, exact target, exact canonical
folder, folder device/inode and target device/inode. ContextVar tokens activate it
only inside the approved ToolManager execution and reset on every exit path.
Global/static roots are unchanged. No approval token is placed in ToolRequest
arguments, conversation text or a persisted record. Reusing a request ID or target
on a subsequent operation requires new approval. Sibling targets and different
operations do not inherit the grant. A failed operation consumes that attempt.

For a file read the prompt shows the containing folder and exact file. Choice 1
permits only that target/read. For a directory listing it permits only that exact
listing. Choice 2 explicitly grants read/list for the displayed folder and its
descendants, never the displayed folder's parent. Write, execute, privileged,
file_info and disk_usage capabilities are not added by either choice.

### Persistent grants

A dedicated versioned JSON PermissionStore defaults to
`<project>/data/permissions/grants.json`, separately from conversational SQLite.
The directory must be owned by the current UID and mode 0700; store/lock files
must be owned regular singly linked files with mode 0600. The store contains
READ_ONLY folder paths and device/inode IDs only. It has no file bodies or tokens.

There are at most 64 grants and 65,536 bytes of store data. Every use reloads the
store, validates exact schema/types, rejects duplicate keys/records and checks
eligible canonical no-symlink folder identities. There is no cached grant set.
Blanket filesystem/home roots, home ancestors, whole config/local trees, system
roots and sensitive paths cannot become production read roots, including through
Settings misconfiguration. Configured legitimate read roots remain compatible.

Updates use a nonblocking process lock, bounded writes, fsync and atomic replacement.
A durable pending marker blocks readers until the new snapshot is durable.
Publication/revocation failures keep access unavailable rather than activating a
partially committed grant. After store errors the runtime fails closed; after an
interrupted transaction the marker also blocks a restart. A crash after success
can conservatively resurrect the marker, causing denial rather than restoring a
revoked snapshot. Recovery requires offline review; no auto-repair broadens access.

### CLI approval and revocation

Only main() installs CLIFileApproval; reusable composition defaults to no approval
adapter. Both stdin/stdout must be TTYs. The escaped deterministic prompt displays
operation, folder, target and scope, with choices 1/2/3. Exact alternative phrases
are supported only while that direct prompt is active. Invalid input, EOF, Ctrl+C,
noninteractive operation and adapter errors deny. No model interprets the choice.

Path/type/identity validation may probe metadata before prompting. File preflight
uses Linux O_PATH rather than reading content or activating special devices. No
file body or directory entries are read before approval. A denial does not execute
or retry the filesystem tool and never falls back to a model.

`show authorized folders`, `list authorized folders`, `always allow <folder>` and
`revoke access to <folder>` are deterministic. Always-allow text initiates a prompt;
it cannot itself grant access. Revocation removes only an exact existing explicit
persistent record and names its canonical folder. Built-in/configured roots are
preserved. Reloading at use prevents stale in-memory grants after successful
revocation, including changes made by another runtime. Inherited configured or
other persistent ancestor access is not removed by revoking a nested grant.

### Sensitive enforcement

FileSystemPolicy validates root components without following or canonicalizing
through root symlinks, preventing re-rooting between configuration validation and
policy composition. It checks names/path components and explicitly protected
storage paths before access, and canonical paths before containment decisions. These
checks apply even in project/configured roots and approved requests. Listings
omit excluded entries before stat calls while still charging them to the scan
budget; no extra enumeration compensates for hidden entries.

Rules cover .ssh/.gnupg/.aws/.kube, keyrings, .config/gh/gcloud/op, common browser
and password-manager directories/files, .git/security directories, .env variants,
private keys, credentials, token/key/secret/service-account names and common key/
vault suffixes. The dedicated permission directory, conversational database and
sidecars are excluded. Hidden files are not universally denied: .editorconfig
works. ReadFileTool also rejects PEM/OpenSSH and OpenPGP private-key markers and nonempty credential
JSON values under selected known key names, even with innocuous filenames.

No ordinary interactive decision overrides exclusions. Full rules and their
conservative false-positive/false-negative limitations are documented in README
and defined in friday/tools/sensitive.py. Failures expose no private content or
unnecessary sensitive metadata.

### Privacy retention

Filesystem read/list turns, failures and permission commands are not appended to
ordinary chat history and do not call SQLite save_turn. Successful file reads
keep only one snapshot, capped at 16,384 serialized JSON bytes including source
and escaped content. The next read replaces it. An unrelated turn, permission
command, other routed operation, failed request or session end discards it.

A narrow explicit immediate follow-up, such as `explain that code`, consumes that
snapshot once and intentionally sends it to the configured model. The data is a
JSON user-message envelope, with system instructions rejecting embedded commands,
role changes and approvals. Both the follow-up and its generated explanation stay
outside normal/persistent history. Model-job messages/results are cleared on every
exit, and private provider errors are sanitized. The model has no authorization
or execution interface even if it ignores the data-framing instructions.

Ordinary chat persistence is unchanged. MemoryManager/schema/native synchronization
were not rewritten. Restored legacy labelled filesystem turns and recognizable
immediate follow-ups are filtered without deleting old data. This cannot identify
all unlabelled older derived text, especially truncated history windows; see HIGH
risk below. Router refusals and unsuccessful tool decisions, including blocked writes and
approval-required responses, are also excluded from history so denied content
and permission decisions cannot enter later model prompts. No private file
bodies are written to application logs by this feature.
Session clearing drops references; it is not a promise of cryptographic RAM erasure.

## C. Implementation

### Created files

| File | Purpose |
| --- | --- |
| friday/tools/access.py | FolderDecision, immutable approval target, direct CLI adapter, filesystem orchestration/admin |
| friday/tools/grants.py | Strict bounded private grant store, process lock, atomic publication and fail-closed transaction marker |
| friday/tools/sensitive.py | Path/name exclusions and private-key/credential-JSON detection |
| friday/core/file_context.py | One bounded one-use temporary file snapshot and explicit follow-up recognition |
| tests/test_filesystem_permissions.py | 94 new deterministic/adversarial permission/privacy tests |
| tests/phase6b_demo.py | Reproducible production-component demo using temporary state and offline provider |
| PHASE_6B_REPORT.md | This audit and review report |

### Modified files

| File | Change |
| --- | --- |
| friday/config/settings.py | Optional filesystem_permission_store_path; default derived from project root |
| friday/main.py | Compose dedicated store/access controller, validate root eligibility, install actual CLI input adapter, safe config errors |
| friday/tools/manager.py | Narrow authorization context after existing schema/risk checks |
| friday/tools/filesystem.py | Dynamic operation-scoped grants, canonical candidate spelling, eligibility-independent sensitive checks, identity rechecks |
| friday/tools/files.py | Omit sensitive entries within original scan budget; block known private-key/credential content |
| friday/tools/router.py | Dedicated show/authorize/revoke commands, including normalized whitespace and missing-path rejection |
| friday/core/assistant.py | Private filesystem turns, temporary follow-up context, runtime-record scrubbing, legacy-context filtering and shutdown clearing |
| tests/test_tool_routing.py | Replace obsolete file-body persistence expectation with the required non-persistence assertion |
| README.md | Current behavior/configuration, exact exclusion policy, retention limitations, commands, tests/demo and roadmap |

No dependencies added. PermissionPolicy enums/contracts, ToolRequest/ToolResult
schemas, ToolPresenter and conversation database schema remain compatible.
There are no native changes and no launcher, subprocess, shell or Trash capability.

## D. Security results

| Scenario | Result |
| --- | --- |
| Unauthorized eligible directory/file | Explicit direct CLI approval required; denied by default |
| Allow once | One exact operation; no sibling use, ID replay or persistence; expires on failure |
| Persistent grant/restart | Works as read/list only after successful validated storage |
| Revocation/restart/external revocation | Exact record removed; next unauthorized access prompts again or denies headlessly |
| Traversal and invalid path encoding | Blocked before approval; UTF-8/path byte bounds retained |
| Symlink and nested escape | Blocked; approved-target/root replacement and configured-root replacement during construction also rejected |
| Special files/hardlinks/oversized/invalid UTF-8 | Existing protections retained; unsafe preflight targets cannot be approved |
| Sensitive project/configured/persistent/once targets | Blocked independently of grants; no normal override |
| Sensitive listing entries | Hidden before stat; scan/output remain bounded |
| Malicious filenames | Prompt and listing controls escaped; no forged prompt lines or terminal escape execution |
| Model/file/chat approval-like text | Cannot grant or replay approval |
| Unauthorized/denied request | No tool content execution or model fallback |
| Write and execute | No new grant authority; existing risk boundary preserved |
| Malformed/insecure/symlink/hardlink/busy store | Fails closed; no approval prompt or cached fallback |
| Store write/fsync/publication failure | No active grant, including restart after post-publication failure |
| Permission choices/prompts/file bodies | No SQLite conversation messages or ordinary model history |
| Explicit file explanation | Bounded one-use context supplied; answer not retained; runtime records scrubbed |
| Later unrelated chat | Snapshot, derived private answer, rejected write content and permission refusals absent |

Boundary rejection deliberately retains the existing generic FAILED ToolStatus
for filesystem errors, preserving Phase 6A behavior. Existing risk-policy denials
still use DENIED. This avoids exposing detailed reasons or private path metadata.
Prompt eligibility checks are not file-content reads. In-flight operations already
opened by another process are not forcibly terminated by revocation.

## E. Tests and manual demo

| Validation | Actual result |
| --- | --- |
| Starting baseline | 276 passing tests |
| New permission/privacy tests | 94 passing tests |
| Final complete suite | 370 passed; 0 failures, 0 errors, 0 skips |
| Existing file-tool security suite | 27 passed |
| Existing Phase 6A suite | 28 passed |
| Routing suite | 28 passed |
| Memory suite | 22 passed |
| Native/Python synchronization suite | 31 passed, no skips |
| Syntax/compile checks | 52 Python files passed, no bytecode written |
| Production import checks | 38 modules passed |
| Fresh native C compilation | Passed -std=c11 -Wall -Wextra -Wpedantic -Werror -fPIC -pthread -shared |
| Fresh compiled native library contract tests | 14 passed against a new /tmp library |
| Forbidden execution API inspection | No production eval/exec/compile/__import__/os.system/os.popen/subprocess calls or shell=True |
| git diff --check | Passed |

The previous 276-test count is retained. One old test explicitly asserted the
now-prohibited persistence of read-file bodies and failures; it was updated,
not silently removed, to assert non-persistence and clean restoration. All other
regression expectations still pass. Full suite includes CLI, provider, model
runtime, system, arithmetic and permission-foundation coverage.

The C check compiled into /tmp/friday-6b-native.drgoOo/libfriday_sync.so and tested
that fresh artifact. Existing native sources/library in the project were untouched.
Tests use temporary directories, mocks and an offline provider. Real personal
files and the actual conversation database contents were not read or modified.

Reproducible demo:

```bash
PYTHONPATH=. .venv/bin/python -B tests/phase6b_demo.py
```

| Check | Demonstrated result |
| --- | --- |
| A | Unauthorized directory -> direct CLI choice 1 -> successful listing |
| B | Same directory -> permission requested again -> denied |
| C | Direct CLI choice 2 -> saved read-only grant -> successful listing |
| D | New runtime/session -> saved permission works without prompt |
| E | Revoke exact alias -> next access requests permission again |
| F | Deny -> filesystem tool execute not called |
| G | Sensitive .env fixture -> blocked without approval |
| H | Read public fixture -> explicit grounded explanation -> no file body/answer in SQLite |
| I | All authorization/denial requests -> zero model calls |
| J | Real existing project router.py read -> success; source body omitted from output |

All writable demo state was temporary. It uses actual production composition,
CLIFileApproval with mocked direct terminal choices, assistant/router/manager,
policy, filesystem tools/boundary and SQLite. Only model explanation is an offline
stand-in. One provider call occurs solely for H. Actual Ollama/Qwen inference was
not exercised; the tests prove supplied grounding and retention boundaries rather
than model answer quality. Session shutdown clears temporary context.

Commands for review:

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_filesystem_permissions.py' -v
.venv/bin/python -B -m unittest discover -s tests
.venv/bin/python -B -m unittest discover -s tests -p 'test_memory.py'
.venv/bin/python -B -m unittest discover -s tests -p 'test_sync.py'
git diff --check
git status
```

## F. Remaining risks

| Severity | Finding and practical limit |
| --- | --- |
| CRITICAL | None identified in tested new paths; this is not an exhaustive security proof |
| HIGH | Legacy SQLite databases/backups can retain Phase 6A bodies or unlabelled derived text. Labelled/recognized turns are filtered, but unknown legacy content cannot be reliably inferred or securely erased. Review legacy retention before sensitive use |
| MEDIUM | Exclusions are conservative heuristics, not comprehensive DLP. Renamed/encoded secrets and unusual credential stores can evade them; approved content sent for an explicit explanation reaches the configured model |
| MEDIUM | Prompt injection can affect model wording despite untrusted-data framing. The model cannot grant access, execute tools, or retain that private explanation through this workflow |
| MEDIUM | Existing hostile mount/directory relocation/TOCTOU limits remain; this is not an OS sandbox and cannot defeat a process already controlling the same user's account/storage |
| MEDIUM | Existing ordinary-chat/HTTP-response/history/resource bounds and conversation-database permission/retention hardening remain future work; no unrelated runtime rewrite performed |
| LOW | Store contention/errors/interrupted transactions deliberately trade availability for denial. Pending-marker recovery is manual, and existing operations are not forcibly cancelled |
| LOW | Standard home aliases are candidate spellings rather than XDG discovery. Broad-parent files such as ~/notes.txt cannot be interactively approved. Listing remains a bounded subset without pagination; conservative content examples can be blocked |

New file bodies and derived temporary answers are protected from silent persistence
and unrelated future prompts. That does not retroactively sanitize every old chat
row, guarantee the configured model server has no logging, or securely wipe immutable
Python strings or disk backups. No such guarantees are claimed.

## G. Next steps and commit readiness

Phase 6C should add reviewed user-owned configuration/store inspection and recovery,
explicit opt-in legacy filesystem-content cleanup, safe error categories, retention
and database permission hardening, and bounded search/pagination plus broader
HTTP/history/time budgets. Recovery must not auto-authorize stale or invalid grants.
Optional explicit multi-turn private explanations would need their own bounded
consent/expiry design; the present mechanism is intentionally one follow-up.

Phase 6D should test multi-process revoke/read races, actual crash/power-loss
simulation around pending-marker steps, mount/rename/inode-reuse scenarios,
fuzzed encodings/stores, ownership/ACL boundaries and live-Qwen prompt injection.
Test both confidentiality and conservative availability failures. Do not use
personal credentials or documents as fixtures.

Phase 6E desktop opening requires a separate EXECUTE permission and one-use direct
confirmation naming both approved application and authorized canonical target.
Use fixed trusted executable paths, MIME/content and executable-file exclusions,
fixed argument vectors with shell=False, no arbitrary shell/URI/app associations,
and controlled process lifecycle/environment. Keep sensitive-path checks. Prefer
pinned descriptors where viewers support them. Read grants alone must never launch
images, videos, PDFs or folders. Trash opening must be a fixed file-manager action;
delete, restore and empty-Trash remain separate unimplemented operations.

Phase 6B is ready for commit review for its documented trusted local CLI scope.
Review legacy stored content before deploying it with sensitive-folder use; the
HIGH legacy-retention finding remains explicit. No commit or other mutating Git
operation has been performed or authorized by this report. Work stops after final
validation and reporting, awaiting explicit review/approval.
