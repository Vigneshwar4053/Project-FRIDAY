# Checkpoint 3M: reviewed Firefox handoff diagnosis

Production navigation/search remains disabled. No live navigation, credential
request, project `.env` access, browser-profile/cookie access, installation,
Snap permission change, commit or push was performed. Checkpoint 3L's registry,
aliases and deterministic Google query encoding remain unchanged.

## Findings

The exact canonical `BrowserTarget` is compiled from the immutable website
registry or the fixed Google search encoder. Its scope binds operation, Firefox,
complete URL and query/value to fresh hidden owner authentication and an exact
Allow once/Deny request. A one-use lease binds target, adapter and context.

The command is `/usr/bin/snap run firefox --new-window <exact URL>`. Execution
uses the verified dispatcher's open file descriptor via `/proc/self/fd`, with
`shell=False`, fixed arguments, pinned FD inheritance, sanitized environment,
no input/output content capture and no arbitrary Firefox flags. The Snap
installation/runtime identities, immutable launcher hashes, FD fingerprint and
environment are revalidated before startup and after a zero exit.

Read-only host checks on 2026-10-12 again found Firefox revision `8763`, passing
dispatcher/Snap/launcher checks (about 87 ms) and passing context revalidation
(about 43 ms). Two existing process executables resolved to that revision's
Firefox ELF binary. Only process name, state, PID and executable path were read;
command lines, environment, profiles, tabs and browser content were not accessed.

The installed GNOME desktop launcher ends with `exec "$@"`; the reviewed
Firefox launcher ends with `exec "$SNAP/usr/lib/firefox/firefox" "$@"`.
Consequently, the invocation can become Firefox itself. Waiting for that PID's
exit is suitable for classifying a short-lived forwarding invocation but cannot
establish submission for a persistent browser process. Its lifetime may exceed
the five-second deadline even if the browser received the request. A mocked
persistent invocation reproduces the timeout-and-cleanup path, but this does
**not** establish that the earlier live failures were timeouts.

The Python adapter supplies a constructed D-Bus address whose socket is absent.
It does not itself connect to that address or require socket existence. Installed
launcher inspection provides no URL-submission acknowledgement over that bus.
The child or its libraries may depend on the bus; the missing socket alone does
not establish causation. No bus rewrite or environment repair was justified.

The original live failure's terminal stage, return code and timing remain
unavailable. Current passing metadata cannot reconstruct a past spawn error,
nonzero exit, identity race, timeout or cancellation. A proven historical failure
mechanism has therefore **not** been established.

## Smallest justified changes

- `firefox_url_handoff.py`: fixed, immutable failure-stage labels and a typed
  exception distinguish capability rejection, installation/dispatcher trust,
  launcher fingerprint changes, environment validation, invalid context, spawn
  failure, nonzero exit, deadline, cancellation and uncertain cleanup. No raw
  exception text, stderr, query or URL enters a failure diagnostic.
- Preparation retains verification-stage failures instead of collapsing them
  into a generic capability result. Empty verification context fails closed.
- `runtime.py`: a real adapter's failed preflight returns its fixed stage rather
  than being confused with the unavailable verified-window browser backend.
- `tools/manager.py`: failure results append only an allowlisted fixed label;
  result data remains absent and the existing failure status is preserved.
- Execution `KeyboardInterrupt` is now classified as cancellation rather than
  a generic failure. Cleanup errors explicitly refuse acceptance.
- Mocked stage coverage was added in `test_checkpoint3m.py`; existing handoff
  assertions permit only the original fixed message or an exact allowlisted
  suffix, retaining their redaction checks.

These are diagnostic and classification repairs, not a claimed fix for the
historical navigation failures. The dispatcher, hashes, Snap interfaces, target
policy, authentication/approval, one-use authorization, five-second deadline,
owned-invocation termination and no-retry behavior are retained.

## Acceptance contract and process lifetime

Acceptance requires a zero exit within the deadline and successful final context
revalidation. It reports `page_load_verified=False`. A nonzero exit is failure.
A persistent invocation is timeout/submission-uncertain; it is never upgraded to
success. Deadline or cancellation after startup can follow a request already
received by Firefox; only the invocation FRIDAY started is stopped and reaped,
never a discovered Firefox PID or existing process group. Cleanup has a separate
one-second wait; inability to confirm it is failure.

Process start, executable identity, a live PID, window visibility and elapsed
time do not prove acceptance of the exact URL. There is no reviewed positive
acknowledgement protocol in this launcher path. A future long-lived submission
contract would need an independent exact-request acknowledgement plus bounded,
owned process lifecycle management. Detaching the process or calling a timeout
success would not satisfy this contract and was not implemented.

Production continues to use `UnavailableFirefoxUrlAdapter`. There is no CLI or
environment bypass. Mock adapter injection exercises the reviewed implementation
without launching anything. Unsupported page verification remains distinct from
this URL handoff's acceptance-only contract. Phase 1 ChromaDB/RAG stays paused.

## Tests and conditional one-time owner test

Final results: **203 targeted tests passed; 1,560 full regression tests passed;
`git diff --check` passed.** The full suite initially hit the same four synthetic
headless IPC permission errors and four corresponding cleanup failures inside
the sandbox; all passed outside it. The 15 new Checkpoint 3M tests use only mocked
processes, synthetic authentication and isolated fixture paths.

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest test_checkpoint3m test_checkpoint3l test_firefox_url_handoff test_website_handoffs test_browser_execution test_discovery_workflows test_tool_routing
.venv/bin/python -B -m unittest discover -s tests
git diff --check
```

Live testing is not enabled by this checkpoint. After failure evidence supports
a separately reviewed repair and production re-enablement:

1. Start `.venv/bin/python -B -m friday.main` in the owner's normal desktop
   terminal. Keep the microphone off; `/q` disables automatic speech if needed.
2. Enter `open youtube` once. Authenticate only through the existing hidden
   prompt. Verify the approval target is exactly
   `navigate_firefox_to_exact_url [firefox] https://www.youtube.com/ | value: https://www.youtube.com/`.
   Choose `1` (Allow once) only for that target.
3. Record only the fixed result, failure-stage label if present and elapsed time.
   Do not share credentials or raw launcher/browser output. Do not retry a
   failure, timeout or cancellation. Acceptance still does not prove page load.
4. Only after acceptance, enter `search firefox for python tutorials` once.
   Authenticate freshly and verify
   `search_firefox_for_query [firefox] https://www.google.com/search?q=python+tutorials | value: python tutorials`
   before choosing `1`. Record the fixed result and stop.

Choosing Deny must create no invocation. With this checkpoint's current disabled
default, website/search commands report the blocker without asking for owner
authentication or starting Firefox.
