# Phase 0.5 — Checkpoint 3D: application handoff review

## Outcome

Four distinct handoff tools and a native-editor verification gate are implemented.
Production application target handoffs remain disabled. A safe Snap exception
could not be established without a reviewed target transport and exact displayed
target verifier. No general security bypass or new Snap arguments were added.
Correct owner authentication cannot enable these unavailable capabilities.

No real owner passphrase, project `.env`, user file, live application window,
browser navigation, input, screenshot or desktop setting was accessed/changed.
No package was installed and no commit/push performed. Phase 1 remains paused.
Package metadata reports `argon2-cffi` 25.1.0 installed; the existing synthetic
Argon2 tests now pass. Real owner credential configuration was deliberately not
checked. Existing full-suite owner tests use disposable synthetic configuration
files; the new handoff suite mocks configuration loading and never reads `.env`.

## Files changed

| File | Change |
| --- | --- |
| `friday/desktop/handoffs.py` | Distinct operations, immutable requests/target bindings, typed verification proof, unavailable production verifier, fixed failure messages |
| `friday/desktop/runtime.py` | Gate reviewed native handoffs, enforce authentication/approval, revalidate targets/executables, verify exact postconditions, one-use leases, deadline/STOP handling |
| `friday/desktop/routing.py` | Include four named handoff tools in the desktop tool boundary |
| `friday/core/assistant.py`, `friday/main.py` | Connect existing STOP paths to pending handoffs |
| `friday/tools/models.py` | Typed handoff failure category |
| `friday/tools/manager.py` | New handoff tools return failure unless their postcondition is verified; preserve failure-without-data invariant |
| `friday/tools/presenter.py` | Present fixed accurate handoff failure messages |
| `tests/test_application_handoffs.py` | 32 isolated tests for authorization, targets, execution and verification |
| `tests/test_tool_routing.py` | Registry isolation test expects 29 tools, retaining isolation checks |
| This report, `FRIDAY_PHASE05_COMPUTER_USE.md` | Current readiness, boundaries, validation and next approval scope |

All pre-existing uncommitted work was preserved. This list is this checkpoint's
scope, not a claim that the entire dirty working tree originated here.

## Distinct capabilities and exact targets

| Operation | Accepted arguments | Production status |
| --- | --- | --- |
| `open_project_in_vscode` | One registered `project_id` OR one single-use discovery `token` | Disabled: exact displayed project verifier unavailable |
| `open_file_in_vscode` | One single-use discovery `token`; no raw path | Disabled: exact displayed file verifier unavailable |
| `navigate_firefox_to_exact_url` | Exact validated HTTPS `url` | Disabled: attribution/navigation verification unresolved |
| `search_firefox_for_query` | Bounded exact `query` | Disabled: attribution/provider/navigation verification unresolved |

Raw executable names, filesystem paths, flags and arbitrary argument vectors are
not accepted by these tools. Project IDs resolve only from the trusted registry.
Discovery receipts retain the original canonical scope, identity and provenance;
missing, ambiguous, expired, already-consumed or wrong-type references fail.
Opening a file never becomes a `read_file` request or content permission.
URLs must be explicit HTTPS targets; unknown names and guessed domains are not
accepted. Browser compound requests still execute zero steps, including launch.

Eligible editor operations use the existing reviewed native ELF adapter. The
target binding captures operation, canonical path, inode/device, file fingerprint
and executable fingerprint. Files and project directories are distinct operation
types and mismatches are rejected before credential entry or action approval.
Directories retain exact inode identity; their child list/size/mtime may change
without changing which directory they are. Files retain size/mtime as well as
identity. Neither metadata check hashes or reads target content.

Production legacy native VS Code project/file routes also require the verifier;
older tool names cannot evade this new production gate. Production legacy native
Firefox URL launches are disabled until navigation verification is available.
Existing app-only launches and folder navigation remain available under their
existing permissions. Synthetic registries/verifiers are constructor-injected
test seams, not settings, CLI toggles, model options or owner-code exceptions.

## Authorization and execution

1. Existing ToolManager schema and risk policy checks run first.
2. Capability and target adapter must be available and reviewed. The default
   verifier supports no operation. Firefox operations are unconditionally disabled
   in this checkpoint, even with a mock editor verifier.
3. Resolve the exact registered/discovered target and pin the reviewed native
   executable/target. Build immutable application/action/target authorization.
4. Existing OwnerAuthenticator requires fresh hidden terminal authentication.
   No credential token/cache, chat/voice credential entry or model involvement.
   Missing authentication denies even a mock-eligible operation.
5. Require a separate exact operation/target Allow once decision. Persistent
   grants, spoken approval, cancellation and denial cannot authorize launch.
6. Revalidate canonical path, scope, target identity, file fingerprint and pinned
   executable before launch. Use existing fixed argv, sanitized environment and
   pinned descriptors; no shell, PATH fallback or unrestricted arguments.
7. Consume the request lease once. Native launch retains its one-second process
   wait and session maximum of four launches. A five-second action deadline and
   cancellation event cover launch/postcondition verification. No autonomous loop.
8. Require a typed proof matching the exact immutable target, an attributed VS
   Code window/process incarnation, and showing state. Recheck target/executable
   after verification. Missing, malformed, hidden, wrong-window, wrong-target,
   timeout, cancellation or changed-target results stop with no completion claim.

New tools report ToolStatus.SUCCESS only for a verified postcondition. A process
launch, normal exit or running application is insufficient. Failure output comes
from fixed messages, not backend exception text. Handoff requests do not persist
Q/session metadata or filesystem grants. A launched process may remain open after
verification failure; FRIDAY does not silently retry or kill owner applications.

Verification deadlines are checked before/after calls and passed to the trusted
verifier. The production verifier performs no I/O and is unavailable. A future
real verifier must enforce its deadline within bounded worker/IPC execution;
the mock contract does not certify an arbitrary blocking implementation. File
size/mtime/inode checks also cannot prove unchanged content against a same-account
attacker who deliberately restores metadata. This remains an OS-account trust
boundary, not a filesystem snapshot or content-integrity guarantee.

## Snap boundary and verification blocker

`ReviewedSnap.arguments` remains app-only `run code` / `run firefox`, with no new
file/project/URL payload. Existing reviewed application launch/profile behavior
is unchanged. No confinement, publisher, installation identity, workspace trust,
extension or automatic-task policy was weakened.

The native editor passes a pinned target descriptor using `/proc/self/fd/...`.
It is not established that Snap confinement and Electron subprocess boundaries
preserve/access that target. Substituting a canonical raw pathname would remove
the pinned-target guarantee and introduce a pathname race. This checkpoint does
not introduce that substitution, alternate launcher or `xdg-open`.

The current metadata-only AT-SPI backend observes roles/states, not the actual
workspace directory or editor document identity. Window titles alone and a
successful process launch cannot establish exact file/project postconditions.
No reviewed VS Code target verifier is available. Accordingly there is no
production handoff exception to enable. The mock proof tests the contract only.

Firefox's prior missing attributed registration remains unresolved. No live
diagnostic or identity relaxation was attempted. A matching executable/process
does not establish an attributable window or browser navigation state. Browser
automation and production mouse/keyboard actions remain disabled.

## Tests

| Suite | Result |
| --- | --- |
| New application handoffs | 32 passed |
| Existing owner authentication, including synthetic real Argon2 | 31 passed, no skip |
| Computer-use foundation/AT-SPI mock coverage | 96 passed |
| Reviewed Snap | 13 passed |
| Tool routing | 28 passed |
| Checkpoint 3B | 16 passed |
| Discovery references/workflows | 31 passed |
| Desktop | 77 passed |
| Full regression | 1,416 passed; zero failures/errors/skips |
| `git diff --check` | Passed |

The full suite ran with permission outside the socket-restricted sandbox for
existing headless Unix-socket tests. No live GUI test was performed. Auth tests
used synthetic secrets only; the new suite mocks its credential loader/provider.

During development, new tests initially had 16 errors from a helper name colliding
with the fixture's project Path, plus two result-status assumption failures.
Correcting the helper exposed ten errors when failure data violated the existing
ToolResult invariant; failure reporting now uses the typed category/fixed error,
preserving that invariant. Two production-mode tests initially reached the mock
Snap fallback instead of their intended native branch; separate mock native
registries now isolate that branch. All final tests pass. Security checks and
existing permission tests were not weakened.

## Exact next owner-approved live scope

There is no safe automatic file/project launch ready for a live test yet. First
approve a narrowly scoped VS Code target-verification design: actual workspace/
document URI or equivalent identity metadata, exact app/window/process binding,
bounded IPC, no content reads, and target-inode correspondence. The existing
METADATA_ONLY backend cannot provide that evidence without an independently
reviewed extension to its allowed metadata contract.

After that design/implementation review, the proposed live test is: owner manually
opens one disposable synthetic project directory and one synthetic file; authorize
read-only exact-window target-identity verification only, no title guessing,
editor/terminal contents, credentials, screenshots or input. This tests the
verifier before any automated handoff. A Snap descriptor-transport exception
would then require separate review and approval before a synthetic handoff test.

Firefox needs a separately approved bounded metadata-only registration experiment
on one owner-supplied nonsensitive window first. Do not restart the browser or
change settings implicitly. Only after attribution/navigation verification and
adapter review should an exact URL/provider/query workflow be approved for live
execution. Stop here for owner review; Phase 1 remains paused.
