# FRIDAY Phase 0.5 — Checkpoint 3A

Discovery references and deterministic workflow planning are implemented.
Phase 1 remains paused. No live desktop observation/actions, application launches,
input, navigation, screenshots, settings changes, dependency/model provisioning,
Snap changes or commits were performed. Automated GUI behavior is mocked.

## Files changed

- `friday/tools/discovery.py`: immutable recent discovery metadata, bounded
  references, single-use selection tokens, reference resolution and revalidation.
- `friday/desktop/workflows.py`: new typed deterministic planning module;
  no execution API, model calls, filesystem access or network access.
- `friday/desktop/routing.py`: reference and compound grammar before legacy routing.
- `friday/tools/router.py`: typed plan and private reference-response routing.
- `friday/core/assistant.py`: deterministic plan/reference responses, cancellation
  and session-end cleanup; existing L0–L3 and model paths preserved.
- `friday/main.py`: CLI STOP also clears pending discovery state.
- `friday/desktop/runtime.py`: reference cleanup on denial, clear unsupported file
  handoff advice, and suppression of SQLite/Q persistence for reference opens.
- `tests/test_discovery_workflows.py`: 31 new synthetic unit/integration tests.
- This report.

## Recent discovery references

The existing per-runtime TargetDiscovery owns one immutable unique reference,
or at most 20 ambiguous candidates. It records canonical path, file/directory
type, original scope and scope identity, target/parent identities, uniqueness,
file size/mtime fingerprint and a monotonic lifetime marker. No content is read
or stored. Context and selection receipts expire after 120 seconds. Receipts are
single-use, bounded opaque tokens; tool arguments cannot supply a replacement
path. Model replies, chat text and old SQLite activity records do not establish
these references.

Supported deterministic commands:

- `open that`, `open it`, `open this file`, `open the found file`
- `show that in files`
- `open its folder`

Case normalization and the existing FRIDAY invocation prefix are supported.
Ambiguous or truncated discovery results cannot silently supply a unique target;
a follow-up asks for an exact numbered selection. With no recent reference,
FRIDAY returns: "I don't have a specific recent file or folder to open. Find it
first." Malformed reference commands containing appended targets or actions are
rejected. The existing `open that file` / `open that folder` clarification path
remains unchanged to preserve the intent-translator contract.

References clear on a new explicit target, expiration, invalid/missing target,
approval denial, STOP, assistant session end and desktop adapter cleanup.
Unrelated turns do not invent or replace a reference. Directory enumeration is
not repeated to resolve a pronoun. Conversation state is not saved to SQLite;
reference-driven launches also skip existing Q/session metadata persistence.
Explicit discovery/open commands retain their previous recent-work behavior.

## File, folder and permission behavior

For a directory, `open it` uses the existing destination-choice workflow; choosing
Ubuntu Files requests a fresh exact-folder approval. VS Code choices remain
subject to native availability and the existing Snap restriction.

For a file, `open that` targets the existing reviewed VS Code file-opening
mechanism. It never becomes read_file and never substitutes the containing
folder. If only the restricted Snap path is available, handoff remains blocked
without a launch; the response offers `open its folder` and explains that content
reading is a separate request. `show that in files` does not silently reveal a
file by opening its parent: file selection in Files is unsupported and explained.

`open its folder` validates the original discovered target, then verifies its
containing-directory identity and opens that exact folder through the existing
Files permission gateway. The original scope is retained, including when the
containing directory is the search root; a parent outside the scope is refused.

Revalidation checks allowed scope, scope inode, target/parent inode and type,
regular-file link count, sensitive-path exclusions and symlink-free descriptor
traversal. File size/mtime are also checked; target validation runs again after
approval. Prior search approval grants no opening, content reading or persistent
filesystem permission. File fingerprints are metadata-based, not cryptographic
content snapshots; privileged/same-user tampering and changes after validation
are not eliminated. Existing descriptor pinning and permission controls remain.

## Compound plans

Recognized patterns include:

- `Open Firefox and search for Python tutorials`
- `Open Firefox and go to YouTube`
- `Open Firefox and open YouTube`
- `Open Firefox and go to https://example.com/help`
- `Find data.js in Downloads and open it`
- `Open Downloads and find data.js`
- `Open VS Code and open my portfolio project`

`then` is also recognized. Plans contain at most eight immutable WorkflowSteps
with typed action, reviewed application ID, bounded value, scope alias and
capability classification. A future discovered-target binding is represented
symbolically; no guessed filesystem path is emitted. Argument validation is
operation-specific. Shell syntax, unsafe URLs, unknown operations and ambiguous
patterns cannot become executable commands.

Browser plans represent launch, window verification, address focus, exact query
or URL entry, submission and navigation verification. Search-query case is
preserved. A small literal website catalog contains YouTube, Wikipedia and
GitHub. Unknown/ambiguous names such as Gatewallah ask for the exact HTTPS URL
or an explicit search request; no domain is invented. Exact URL planning performs
no network access and creates no browser/Snap URL authorization.

Capability classifications distinguish existing gateway-supported operations,
planned but unavailable operations and native-dependent handoffs blocked for
Snap. Every compound response is plan-only. Even supported steps do not execute;
there is no partial execution, approval reuse, hidden search or automatic launch.
Clarification and unsupported requests explicitly report that no workflow steps
ran. Queries/plans stay out of reusable model history and memory through the
existing private deterministic response path. Existing single-action launch,
folder navigation, intent translation, synchronization and workload routing remain.

## Validation

Final results:

| Suite | Tests | Result |
|---|---:|---|
| Discovery references/workflows | 31 | Passed |
| Existing discovery | 22 | Passed |
| Existing tool routing | 28 | Passed |
| Existing intent translator | 81 | Passed |
| Computer use | 96 | Passed |
| Full regression | 1,337 | Passed |

The full suite used the approved outside-sandbox invocation required by existing
headless Unix-socket tests; UI/application launches remain mocked.
`git diff --check` passed.

Failures encountered during implementation were corrected, not hidden: the new
fixture initially had 28 setup errors from an incompatible inherited setUp;
subsequent assertions exposed a reference destination-menu loop and two test
fixture/response mismatches. The destination loop was fixed. A later full run
found three existing intent-translator failures caused by an overly broad
malformed-reference guard; the runtime guard was narrowed to preserve legacy
clarifications, with existing tests unchanged. Final suites pass without weakening
existing security tests.

## Remaining limitations and next approval

Grammar is intentionally finite. Compound execution, partial-execution approval,
autonomous replanning and live postcondition verification are not implemented.
Ordinary unscoped `open filename.ext` retains its legacy routing; this milestone
changes the specified discovery references and compound forms. Directory opens
can still require an application choice. Real file/folder opening was not tested.

Firefox still lacks an identifiable accessibility registration from the previous
approved diagnostic; no new Firefox probe was performed here. VS Code's prior
metadata-only observation exposed a root frame without actionable descendants.
Real automation still requires separately approved safe control identification,
exact-target action implementations, app-specific postconditions, responsive
cancellation during blocking work, and a reviewed project-opening mechanism.
Snap app-only restrictions and workspace trust/task/extension protections remain.

Stop here. Obtain separate owner approval before any live desktop workflow test,
real input implementation or browser/project navigation. Phase 1 remains paused.
