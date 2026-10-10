# Phase 0.5 — Checkpoints 3B and 3C

Implemented: deterministic file-open routing, discovery selection lifecycle,
code-only Firefox readiness review, handoff design and an owner-authentication
foundation. Phase 1 remains paused. No live desktop probe/action, navigation,
capture, setting change, installation, model download, real credential setup,
commit or push was performed. Existing dirty work was preserved.

## Files changed in this checkpoint

| Files | Change |
| --- | --- |
| `friday/tools/discovery.py` | Exact recent filename matching/revalidation; qualified references; consumed-selection feedback |
| `friday/desktop/routing.py` | Resolve filenames before clearing context; `open it/that in vs code`; current Q menu priority |
| `friday/tools/router.py` | Separate open/read; block unsupported explicit paths; reject explicit chat credentials without persistence |
| `friday/security/__init__.py`, `owner.py`, `setup_owner.py` | Lazy private configuration, typed policies/requests, Argon2id provider, hidden input, cooldown and owner-run setup |
| `friday/desktop/runtime.py`, `computer_use.py`, `friday/main.py` | Shared production authentication before sensitive-action permission; unsupported actions rejected first |
| `friday/tools/models.py`, `manager.py`, `presenter.py` | Typed authentication failure and fixed safe feedback |
| `requirements-owner-auth.txt` | Optional proposed pins; no installed dependencies |
| `tests/test_checkpoint3b.py`, `test_owner_auth.py` | New synthetic regression/security tests |
| `tests/test_desktop.py`, `test_recent_work.py` | CLI auth mocks/assertions; original permission approval/denial assertions retained |
| `tests/test_tool_routing.py`, `test_discovery.py` | Replace obsolete open-as-read/stale-number fallthrough expectations with no-read/no-action assertions |
| This report, `FRIDAY_PHASE05_COMPUTER_USE.md` | Findings, validation, setup instructions and approval gates |

## File opening and selections

Root cause: discovery deliberately skipped bare `open` filenames with extensions,
then the legacy router treated `open` as a content-read verb. Those rules are
corrected. `read data.js` retains its existing read-file semantics and filesystem
checks. Opening is never a read permission.

`open data.js` first checks the active conversation's discovery for an exact,
case-insensitive basename. A unique match retains canonical path, original scope,
parent/scope/target identity, fingerprint and 120-second lifetime. Exact metadata
revalidation precedes a single-use receipt, then repeats at the action gateway.
Missing/changed/symlinked/out-of-scope targets fail closed. Ambiguous or incomplete
results require selection; even one candidate from a truncated search stays
non-unique. With no matching reference, existing bounded discovery searches only
approved roots (depth 3, 1,000 entries, 20 matches, 2 seconds). Downloads/Documents
outside those roots retain their separate metadata-search permission. No path
is invented. New differently named explicit targets replace old references.

References supported: `open that`, `open it`, `open this file`, `open the found
file`, `show that in files`, `open its folder`, and the first four qualified with
`in vs code`/`in visual studio code`. Matching `open data.js in vs code` preserves
the recent discovery scope. Reference launches do not persist discovery grants
or conversation-derived Q/SQLite records.

Directories use existing VS Code/Ubuntu Files selection. Files use only the
existing reviewed native VS Code path when available. Snap file/project handoff
is still blocked before authentication, action approval or launch. Responses
offer `open its folder`; no parent-folder substitution happens automatically.
Reading contents remains a separate operation and permission.

Destination menus are consumed after one numbered answer, including a blocked
answer. Previously the next number could fall through to normal/model routing,
which mocks reproduce. This is a plausible explanation for the historical
`Working...` delay, not proof of that specific event. Completed/expired choices
now produce bounded feedback and no action. A newly displayed Q menu has priority.
STOP/denial/cancellation clear targets and receipts; a content-free consumed-menu
marker can remain to reject stale numbers. No old permission is reused.

## Existing adapters and proposed handoff design

Native launch uses reviewed root-owned ELF executables, pinned descriptors,
fixed argv arrays, sanitized environments and no shell. Existing native VS Code
uses a fresh private profile, disabled extensions, automatic tasks off, workspace
trust required and pinned target descriptors. Native Firefox retains only its
existing reviewed URL catalog. No URL was added to that catalog. Reviewed Snap
launch uses a pinned `/usr/bin/snap`, exactly `run code` or `run firefox`, and
existing publisher/package/confinement checks. Snap accepts no target payload.

These proposed operations are independently reviewable, not new executable tools:

| Typed operation | Exact permission scope | Status |
| --- | --- | --- |
| `LaunchApplication` | Reviewed application/adapter and launch effect | Existing app-only permission gateway |
| `OpenEditorFile` | Application, receipt, canonical file, scope/inode/fingerprint, adapter | Existing native path only; Snap blocked; owner auth then exact-action approval |
| `OpenEditorProject` | Application, registered/discovered directory, identity, private trust profile, adapter | Existing native path only; Snap blocked; owner auth then exact-action approval |
| `NavigateBrowser` | Firefox, attributed window, reviewed exact HTTPS URL/origin and verification predicate | General navigation planned only |
| `SearchBrowser` | Firefox, attributed window, exact query, separately reviewed provider/origin and verification predicate | Planned only |

Future adapters must preserve target identity, reject symlink escapes/option
payloads, and retain workspace trust/task/extension protections. Snap cannot be
assumed to see FRIDAY's `/proc/.../fd` targets across confinement boundaries.
Passing a canonical pathname alone does not preserve the pinned-file guarantee.
A new Snap handoff needs separate review of fixed arguments, target visibility,
profile/trust behavior, confinement and genuine result verification. No shell,
`xdg-open`, arbitrary argument fallback or credential-based policy override.

Browser compound requests remain typed plans only and execute zero steps,
including the first launch. Searches have six planned steps. YouTube is a
recognized exact site; Gatewallah/unknown sites require an exact URL or a
separately approved search. No domains are guessed.

## Firefox diagnostic findings — code and mocks only

No new live observation was performed. Historical findings remain: reviewed
Firefox process present, no attributable AT-SPI registration, VS Code root-frame
observation available. The underlying Firefox registration cause is unresolved.

Before inspecting UI, the worker requires a unique bus name, bus-owner PID equal
to the application's reported PID, and reviewed `/proc/PID/exe` device/inode/
size/mtime. Process start time pins incarnation. Snap fingerprints cover both
`firefox` and `firefox-bin`. Only then are FRAME/WINDOW roles, SHOWING/non-DEFUNCT
state and protected-dialog filtering used. Metadata observation still excludes
names, descriptions, values and protected content. Worker source/hash and identity
checks were not modified or relaxed.

Existing mocks verify both Snap layouts, PID/bus/fingerprint mismatches, delayed
or missing registration, unknown/hidden/dialog roots, exact window identity,
pruning and traversal bounds. Possible causes are absent/lazy registration,
pre-enable application lifecycle, Snap accessibility exposure, process boundaries,
fingerprint availability or conservative root filters. None is established by
code review; VS Code/Electron exposure does not prove Firefox exposure.

Minimum next experiment requires separate approval: the owner manually supplies
one nonsensitive Firefox window, then one bounded content-free diagnostic checks
registration presence, advertised PID, bus-owner PID, reviewed fingerprint and
root role/showing state. No names/titles/descriptions/content or broad UI traversal.
If registration is absent, a comparison after a separately owner-approved manual
Firefox restart could test lifecycle effects. No automatic restart/settings/Snap
change is authorized here.

## Owner authentication and dependencies

The core has no existing Python dependency manifest and uses stdlib. The Argon2
Python package is absent from the venv and system Python. Optional proposed pins
in `requirements-owner-auth.txt`: `argon2-cffi==25.1.0`,
`argon2-cffi-bindings==25.1.0`, `cffi==2.0.0`, `pycparser==2.23`. None was installed;
Python 3.14 wheel compatibility and real library behavior remain unverified.
Separate owner approval is required for installation/network access. There is
no substitute KDF or automatic installation.

The provider delegates to `argon2-cffi.PasswordHasher`: Argon2id v19, 64 MiB,
three iterations, one lane, 16-byte cryptographically random salt, 32-byte output.
Stored parameters are validated against this bounded format. Constant-time
password comparison is delegated to the hashing library; actual library execution
has not been validated yet. RAM cost is 64 MiB per hash plus interpreter/library
overhead. A shared authenticator serializes hidden entry; no model is involved.

Setup uses hidden `getpass` entry and confirmation; TTY/warning checks forbid
echoed fallback. It writes only the new owner-auth hash and enabled flag,
preserving unrelated existing settings. `.env` must be owner-owned, regular,
single-link, mode 0600, bounded to 16 KiB, with no symlinked ancestors. Existing
updates require explicit `--update-existing`, recheck identity and use atomic
replacement. Unsafe existing permissions are rejected, not silently changed.
Setup checks Git exclusion and absence from the index. Metadata checks confirmed
the project `.env` is ignored and untracked. Its real contents were not read or
modified; no real passphrase was requested or created.

Flow: tool/schema/risk validation → reviewed capability/adapter checks → frozen
exact application/operation/target owner request → hidden authentication → fresh
allow-once exact-action permission → target/binary revalidation → existing adapter
execution → honest verification level. Typed application policies cover existing
native VS Code file/project operations, existing reviewed Firefox URL operations,
and future supported desktop input. Authentication issues no token, cached success
or session grant. Each sensitive request authenticates again. Denial/cancellation
performs no action. App-only launch and normal folder navigation retain existing
permission behavior without an owner-code prompt. Production AT-SPI actions remain
unsupported and are rejected before authentication/approval.

Missing/disabled/malformed/insecure credentials or absent Argon2 deny sensitive
actions before secret entry. Three failed guesses impose a 30-second process-local
cooldown without sleeping. Failure feedback is fixed and content-free. Secrets
are never tool arguments, model context, logs, messages or SQLite records.
Explicit chat credential submissions are rejected without persistence. Only the
hidden terminal prompt accepts credentials; voice cannot supply authentication.

Limitations: immutable Python strings cannot be reliably wiped (references are
cleared, no copies are intentionally retained). Cooldown resets on process restart
and cannot prevent offline guessing of a stolen hash. This is an additional app
gate, not isolation against compromise of the same OS account/runtime. Arbitrary
unsolicited secrets in ordinary chat cannot reliably be recognized; use only the
hidden prompt. No real credential or working real hashing dependency exists yet.

## Owner setup — after separate dependency approval

1. Approve/provision the optional pinned packages in the venv and rerun the real
   Argon2 test. It must pass rather than skip before claiming cryptographic readiness.
2. Confirm `.env` is ignored/untracked and already private (0600). If existing
   permissions are unsafe, obtain separate approval to correct them; setup refuses
   to silently chmod or expose the file.
3. In a private interactive terminal in the project, run
   `.venv/bin/python -B -m friday.security.setup_owner` for a new file, or
   `.venv/bin/python -B -m friday.security.setup_owner --update-existing` to
   explicitly authorize updating an existing private file.
4. Enter a new 12–1,024-character passphrase twice at hidden prompts. Never put it
   in argv, environment, chat, voice or shell history.
5. Start FRIDAY normally. Supported sensitive requests require both hidden auth
   and separate exact-action approval. Correct authentication does not enable
   Snap handoffs, real input, general browser navigation or verified GUI outcomes.

## Validation and failure history

Synthetic files/credentials, mock desktop state and mocked launches only. No
process launch was counted as successful real GUI verification.

| Suite | Final result |
| --- | --- |
| Checkpoint 3B | 16 passed |
| Owner authentication | 31 run: 30 passed, 1 skipped (real Argon2 absent) |
| Computer use/Firefox attribution | 96 passed |
| Discovery references/workflows | 31 passed |
| Discovery | 22 passed |
| Tool routing / intent translator | 28 / 81 passed |
| Desktop / recent work | 77 / 45 passed |
| Full regression | 1,384 run: 1,383 passed, 1 skipped; no final failures/errors |
| `git diff --check` | Passed |

Initial sandbox regression: 4 headless Unix-socket errors and 4 cleanup failures,
plus 4 obsolete fixture/expectation failures. Outside the sandbox only the 4
fixture/expectation failures remained. CLI fixtures now mock and assert auth while
retaining permission tests; two open-as-read expectations were replaced. A later
full run found one stale-selection expectation, now explicitly testing bounded
feedback and no tool/process. New-test authoring exposed incorrect accessor/action
assumptions and an import cycle; these were corrected. No security validation was
weakened to pass. Final socket tests ran outside the sandbox with permission;
no live GUI action was performed. Real Argon2 remains explicitly skipped.

## Required next checkpoints

Separate approval is needed for dependency provisioning/real hashing validation
and owner-run setup; Firefox metadata-only registration/lifecycle diagnostics;
a reviewed native/Snap target-handoff adapter with identity/trust/confinement and
postcondition guarantees; and synthetic window-scoped input implementation/live
testing before bounded browser workflows. Webpage reading needs its own content
permission and untrusted-data boundary. Existing launches still report window/
target verification unavailable. Stop for owner review; Phase 1 remains paused.
