# Phase 0.5 Checkpoint 3E — browser dispatch and verification gate

Production browser navigation is **disabled**. This checkpoint implements the
validated execution path and tests it with synthetic backends. It does not
establish that the acceptance command navigates real Firefox. No existing
reviewed production interface can currently prove its exact final destination.
Owner authentication cannot supply that missing capability.

## Files changed in this checkpoint

- `friday/desktop/browser_execution.py`: reviewed target policy, typed context,
  window/receipt/proof contracts, deterministic plan compilation, one-use
  authorization and bounded browser execution controller; unavailable production
  backend is the default.
- `friday/desktop/runtime.py`: compose the controller, route the two existing
  browser handoff tools through it, retain exact ToolManager leases, keep browser
  metadata out of persistent recent work. Existing STOP event cancels it.
- `friday/core/assistant.py`: dispatch only a complete reviewed Firefox plan when
  the backend explicitly supports its target. No model call, generic step
  interpreter, app-only partial execution or alternate launcher.
- `friday/desktop/workflows.py`: preserve destination/query punctuation instead
  of trimming periods into a different target.
- `friday/desktop/handoffs.py`: fixed content-free errors for unsupported browser
  targets, unverifiable windows and unverifiable navigation.
- `tests/test_browser_execution.py`: synthetic targets, credentials, executable
  fingerprints, windows, navigation evidence, clocks and cancellation.
- This report and the phase overview link.

Existing uncommitted project changes were preserved. No commits or pushes.
No dependency changes, package installation or downloads.

## Backend review and Firefox attribution

| Candidate | Assessment | Production decision |
| --- | --- | --- |
| Verified AT-SPI controls | Current worker is metadata-only and production input is disabled. Roles/states cannot establish a destination URL. Firefox registration is unresolved. | Disabled |
| Fixed Firefox destination launch adapter | Validated URL plus fixed argv could resist argument injection, but Snap target handoff is not an existing reviewed exception. A launcher may forward to an already-running Firefox and exit; exit/process existence proves neither the window nor navigation. | No adapter activated |
| Existing browser integration | FRIDAY's managed GTK browser is a folder browser, not Firefox. Import availability checks found no Selenium or Playwright; `/usr/bin/geckodriver` was absent. `/usr/bin/firefox` existence alone does not establish a reviewed native executable. | No available navigation verifier |

The selected production backend is `UnavailableFirefoxBackend`. The controller
has an explicit injection interface for trusted mock code and a future separately
reviewed backend; there is no environment flag, model proposal or owner-code
switch that activates it. No subprocess, worker, window enumeration, browser
connection or network request starts through this backend, including on import.

The prior live report found a reviewed Firefox executable/process but no
attributed AT-SPI application registration; VS Code exposed a root frame. These
are historical findings, not new live observations. Source review retains:
AT-SPI bus-owner PID matching, application process attribution, reviewed native
or Snap executable fingerprints, process-start identity, permitted window roles,
SHOWING/non-defunct filters and protected-region pruning. Possible causes remain
Firefox registration/lifecycle, Snap accessibility-bus exposure, registered versus
browser-process identity, delayed registration, or conservative role/state
filtering. Code inspection cannot distinguish these without another approved
live diagnostic. No identity check, worker hash, visibility filter, Snap connection
or accessibility setting was changed.

Even resolving registration will not make metadata-only observation prove
navigation. A separately reviewed URL-only evidence channel is also necessary.
No page/editor/terminal content, accessible names, descriptions or real window
titles were read during this checkpoint.

## Target policy and workflow dispatch

The initial executable navigation registry contains only:

`youtube -> https://www.youtube.com/`

The canonical HTTPS URL with a trailing slash, or the explicitly supported
root form without a slash, resolves to that destination. Unknown names require
an exact URL or clarification; arbitrary exact URLs can be represented by the
existing planner but are not executable under this registry. No guessed domain,
DNS lookup or private-network exception is added. Credentials, ports, alternate
origins, query strings, fragments, paths, control characters, scripts and
non-HTTPS schemes are rejected. Destination punctuation is preserved. Redirects
and alternate final URLs do not satisfy the proof contract.

Search is a distinct operation with a fixed candidate provider:

`https://duckduckgo.com/?q=<urllib.parse.urlencode-encoded-query>`

The exact original query is bound alongside the encoded destination and provider
in owner authentication and action approval. Queries are bounded to 256 UTF-8
bytes and preserve existing deterministic unsafe-input rejection. They are data,
not argument templates. This provider has not been navigated or live-verified;
search remains disabled in production, and needs separate live approval.

A compiler accepts only the existing complete six-step Firefox plan in its exact
order, with no clarification, extra operation, scope or payload. It collapses
that plan into **one** registered navigation/search handoff request. Unsupported
plans execute zero steps. App-only launch is never used as a partial fallback.
The existing single-action launch, file discovery, VS Code restrictions, L0–L3
routing, permission policies and native synchronization are retained.

## Authentication, approval and execution

1. Validate the immutable operation, destination/query and supported backend.
2. Prepare a typed reviewed executable/session context without desktop I/O.
3. Authenticate with the existing OwnerAuthenticator and hidden terminal input.
4. Require Allow once for the same exact operation, application and target.
5. Bind a one-use lease to target, context and backend; revalidate before acting.
6. Acquire an attributed Firefox window, starting only through a future reviewed
   adapter if necessary. Record launch attempted separately from window proof.
7. Revalidate exact window/process/showing state before navigation.
8. Attempt navigation and obtain a typed navigation receipt.
9. Verify the exact receipt, window, process context and final URL; revalidate
   context and window again before reporting verified success.

The existing ToolManager risk policy and schema checks run before authentication.
Authentication failures/cooldown, missing credentials, denial, persistent-grant
attempts, cancellation and unsupported capabilities prevent unstarted actions.
Every eligible request authenticates and approves afresh. No authentication token
is cached. The real `.env` was not read, printed, copied or modified. Synthetic
credential loaders/providers exercised the authenticator; existing owner-auth
regressions cover Argon2id itself. No passphrase is passed to the model, persisted,
logged, echoed or put in command history.

Only the reviewed six-step plan may reach this dispatcher. Model text cannot
select a backend or produce executable commands. The Snap app-only adapter and
VS Code policies remain unchanged. There is no `shell=True`, arbitrary argv,
`xdg-open`, global keyboard/mouse or screenshot fallback in the new controller.

## Evidence and boundedness

Successful results carry the transitions: authenticated, permission approved,
optional launch attempted, Firefox window attributed, navigation attempted and
navigation verified. Success requires an exact `NavigationProof` tied to the
same target, context, window and navigation identifier, `completed is True`, and
an exact final URL match. A boolean launcher result, process, title, window alone,
wrong window, redirect or stale receipt cannot establish success.

Failures use fixed status-specific messages; the existing ToolResult rule that
failed results contain no data is preserved. Backend exception messages and
browser content never become public errors. Transient phase information is not
written to SQLite, recent work, chat history or model context.

One request permits at most one acquire, one navigate and one verify call, with
no retry loop and only one executing browser task at a time. Revalidation runs
between these bounded stages. Execution has a ten-second cooperative deadline
starting after interactive authentication/approval; those prompts are not
included in that execution timeout. A future backend must additionally bound
its own subprocess/IPC calls, response sizes and waiting at the OS boundary.
The controller cannot force-preempt an arbitrary blocking backend. STOP shares
the existing cancellation event, preventing unstarted actions and stopping at
checks; typing STOP cannot immediately interrupt a blocked synchronous CLI.
Already-completed navigation cannot be undone by cancellation. No owner browser
process is killed, and no continuous observation/polling is introduced.

## Automated validation

| Suite | Result |
| --- | --- |
| New browser execution suite | 51 passed |
| Application handoffs | 32 passed |
| Computer-use | 96 passed |
| Discovery/workflows | 31 passed |
| Tool routing | 28 passed |
| Full regression suite | 1,467 passed; no failures, errors or skips |
| `git diff --check` | Passed |

All browser execution evidence is synthetic. Coverage includes canonical YouTube
forms, exact HTTPS input, query encoding, unknown sites, malformed/private/unsafe
URLs, authentication ordering and cooldown, denial, one-use leases, target and
backend substitution, executable/session changes, wrong/hidden/stale windows,
redirects and stale receipts, already-running/not-running Firefox, cancellation,
timeouts, action counts, no retries/partial launches, provider/model separation,
secret-safe failures, unchanged app-only launching and disabled VS Code handoffs.

An initial development run found 23 failures and two errors: the new integration
used `value` instead of the existing `url`/`query` tool schemas, and the assistant
branch was inserted at the oversized-message guard. Both implementation issues
were corrected; the guard remains non-executable. Assertions were not weakened.
A later full run passed 1,465 tests; subsequent window-revalidation checks added
two tests, requiring the final full run reported above.

## Remaining blockers and exact live-test proposal

**Not ready to authorize a real navigation test yet.** First request separate
approval for a bounded, content-free Firefox-only AT-SPI registration diagnostic:
one existing Firefox instance, no restart/launch, no settings changes, no other
application enumeration, no names/titles/values/page contents/screenshots or
input. One Firefox-only window-list request with a five-second outer deadline,
the existing 64 KiB worker response cap, and no control-tree observation or retry.
Inspect only application/window opaque identity, reviewed executable
fingerprints, role and state with existing worker limits/timeouts. Stop if
attribution cannot be established; do not relax it.

Next, independently review and implement an exact-URL-only verification channel.
Reading an address-field value is outside current metadata-only permission and
requires explicit approval; introducing a remote-debugging/WebDriver mechanism
would also need separately approved configuration/dependencies/security review.
No such mechanism was installed or enabled here. A narrow Snap URL exception
must be reviewed separately if transport needs it, preserving general app-only
launching and existing Snap confinement.

After those blockers are resolved and mock-tested, propose **one** live command:
`open firefox and go to youtube`. The owner enters the passphrase only in FRIDAY's
local hidden prompt, then chooses Allow once for the exact canonical YouTube URL.
One acquire/navigation/verify sequence, ten-second bounded execution, no retries,
no page-content read, screenshots, clicks/typing, settings changes or downloads.
Record only attributed identities and exact-URL verification status. Unexpected
window/URL, redirects, denial, timeout or cancellation stops the task and cannot
be reported as success. A search test to the fixed provider needs a separate
approval. No live test was performed in this checkpoint. Phase 1 remains paused.
