# Phase 0.5 Checkpoint 3H — executable Firefox YouTube URL handoff

`open firefox and go to youtube` now dispatches an actual, separately reviewed
Firefox Snap URL handoff when its installation/session capability checks pass.
It uses fresh owner authentication and exact Allow once permission. It does not
depend on Firefox AT-SPI registration or exact final-URL verification.

Only `https://www.youtube.com/` is executable through this adapter. The workflow
compiler resolves the YouTube alias to that canonical URL. Search, other sites,
other applications, URL parameters/fragments and arbitrary flags/paths remain
unsupported. Unsupported browser workflows retain their existing plan-only or
fixed refusal behavior. The generic Snap adapter remains app-only; its arguments
and validation are unchanged. The verified-window browser backend stays disabled.

## Reviewed installation and invocation

Read-only installed metadata review confirmed the Mozilla-verified Firefox Snap
revision 8763 (154.0-1), strict confinement, and the existing reviewed content
providers/connections. No package or settings changes were made.

The fixed logical invocation is:

```text
/usr/bin/snap run firefox --new-window https://www.youtube.com/
```

FRIDAY uses `subprocess.Popen` with that fixed list, `shell=False`, an executable
descriptor pinned by the existing administrator-owned native registry, and
`SNAP_REEXEC=0`. It executes the dispatcher through `/proc/self/fd/<pinned-fd>`;
`argv[0]` remains `/usr/bin/snap`. It preserves Snap confinement rather than
executing a browser binary directly outside Snap. Standard input/output/error are
discarded and only the reviewed desktop environment is forwarded. No browser
process enumeration, input, profile inspection or AT-SPI call occurs.

Installed `meta/snap.yaml` declares `firefox.launcher`, the GPU wrapper and the
desktop-launch command chain. The package launcher ends in a quoted forwarding
of its arguments to `$SNAP/usr/lib/firefox/firefox`. The Firefox launcher/scripts,
Snap manifest, GNOME provider launcher and Mesa provider wrapper have explicitly
pinned SHA-256 hashes. They are inspected through regular, root-owned files on
read-only package mounts. Existing Snap validation additionally binds package
IDs, verified publishers, confinement, runtime providers and image metadata.

Snap's installed chain itself uses shell scripts and may source owner-writable
startup data, as already accepted by the existing owner-authorized Snap exception.
FRIDAY does not execute a shell command string or inspect that owner data. This
checkpoint narrows the existing startup trust exception to the one exact URL;
it does not claim the entire packaged launcher chain is shell-free.

Any pinned chain change requires a separate review. Snap/runtime/dispatcher and
desktop-session identity are captured before authentication, then revalidated
immediately before process creation and after a normal exit. No fallback, retry,
remote debugging, WebDriver, installation or configuration switch is added.

## Authentication, approval and truthful results

1. Validate the typed exact canonical URL and installed capability.
2. Prepare and hold the reviewed dispatcher descriptor and immutable context.
3. Call the existing `OwnerAuthenticator` for the Firefox browser-navigation
   operation and exact target scope. Production uses its hidden Argon2id prompt.
4. Request Allow once / Deny for that same operation/application/URL. Reject
   persistent decisions. Authentication grants no executable permission itself.
5. Bind a one-use lease to target, adapter and context; revalidate before spawn.
6. Invoke exactly once, with a five-second execution deadline and bounded wait
   intervals. Cancellation is checked before spawn and during waiting.
7. Accept only exit code zero with unchanged reviewed context, then report:

   `Firefox YouTube navigation request accepted; page load not independently verified.`

The result has `status=request_accepted` and `page_load_verified=false`, distinct
from navigation verification. ToolManager accepts this status only for the exact
YouTube navigation tool/target and fixed truthful message; it does not authorize
other handoffs to return an unverified success. ToolPresenter displays it directly
without sending execution results or credentials to a model or persistent recent
work/chat records.

Wrong passphrases, denial, missing capability and cancellation before execution
start produce no process. Process failures, changed context, timeout and
cancellation never claim verified navigation. Error strings are fixed and never
include subprocess output, backend exception text or credentials.

Already-running Firefox can receive the URL through its existing remoting path,
allowing this invocation to exit normally. No running Firefox is killed or
restarted. If Firefox was closed, the spawned invocation can become a long-lived
browser process: the five-second deadline then reports an uncertain timeout and
kills only the invocation FRIDAY started. A timeout may occur after URL delivery;
the controller does not retry or infer page-load completion. Cleanup has a
separate one-second reap bound. The proposed first live test uses the existing
running Firefox instance.

## Validation and scope

Validation passed: 42 new handoff tests, 324 tests across the targeted handoff,
browser, authentication, Snap, routing, discovery and computer-use suites, and
1,509 full regression tests with no failures or skips. `git diff --check` passed.
The full suite's existing headless socket tests required approved execution
outside the sandbox after sandbox restrictions blocked their IPC.

All new execution tests mock process creation and Snap metadata, with synthetic
credential loaders/providers. A guard rejects any real credential-file access.
Existing Argon2id/hidden-prompt tests remain in the regression suite. New cases
cover exact routing, fresh authentication/approval, wrong secrets/denial,
fixed pinned executable/argv/environment, unsupported URLs/flags/apps,
changed dispatcher/installation/chain/session/adapter, one-use leases, concurrent
handoffs, failure/timeout/cancellation, no AT-SPI dependency, truthful reporting,
credential/content secrecy and unchanged general Snap and verification policies.

A separate read-only check confirmed the implemented production adapter is
available and its prepared context revalidates against the installed Snap. It
called no authentication, read no `.env`, and performed zero launches.

No live YouTube request has been made. Existing uncommitted work is preserved.
No packages, Firefox/Snap/GNOME settings, credentials, commits or pushes changed.
Phase 1 remains paused.

## Exact one-time live-test procedure — pending separate approval

1. Obtain separate approval for **one** real YouTube URL handoff. Coding/mock-test
   approval does not authorize this step.
2. Keep the existing Firefox instance running. Start FRIDAY in a private local
   terminal from `~/Projects/FRIDAY`:

   ```bash
   .venv/bin/python -B -m friday.main
   ```

3. Enter exactly `open firefox and go to youtube` once.
4. Enter the owner passphrase only at FRIDAY's hidden terminal prompt; do not
   put it in chat, argv, environment variables or a script.
5. Check the permission prompt says Firefox and exactly
   `https://www.youtube.com/`, with page load not independently verified.
   Select `1` (Allow once). Select `3` (Deny) for a mismatched prompt.
6. Record only FRIDAY's fixed result. On exit-zero acceptance expect the exact
   message above. Do not label it independently verified YouTube opening.
7. Stop after that one request. Do not retry on timeout/failure or add browser
   content reads, screenshots, input, settings changes or URL verification.
