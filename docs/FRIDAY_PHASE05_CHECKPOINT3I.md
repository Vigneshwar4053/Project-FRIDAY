# Phase 0.5 Checkpoint 3I — owner-approved website handoffs

The reviewed Firefox Snap URL handoff now supports five exact owner-provided
destinations. Every requested standalone alias and Firefox compound command
routes deterministically to execution through the existing authentication and
permission gateway. No model decides a destination and no live website was opened.

## Registered destinations and aliases

| Key | Exact URL | Aliases following `open` |
| --- | --- | --- |
| youtube | https://www.youtube.com/ | youtube |
| linkedin | https://www.linkedin.com/in/sameti-thirumani-vigneshwar/ | linkedin, my linkedin |
| whatsapp | https://web.whatsapp.com/ | whatsapp, whatsapp web |
| github | https://github.com/Vigneshwar4053 | github, my github |
| pw_study | https://www.pw.live/study-v2/study | pw study, physics wallah, pw_study |

The same site aliases resolve within `open firefox and go to <alias>`; the
existing reviewed compound grammar also retains its prior supported verbs.
Command aliases are case-insensitive. The direct handoff tool requires an exact,
case-sensitive URL from the immutable registry, including each registered path
and trailing-slash choice. No generic GitHub homepage or alternate profile URL
is substituted for the owner-provided profile. Unknown site names do not resolve
to inferred domains. Other existing file/folder discovery grammar remains intact.

The historical YouTube compiler form without the root trailing slash still
resolves to the canonical destination; the raw tool URL must remain canonical.
Other URL variants, query strings, fragments, credentials, unsafe schemes and
unapproved paths are not executable. Arbitrary HTTPS URLs can retain the existing
plan-only/refusal behavior, but cannot pass the handoff allowlist. Search remains
non-executable in production. No URLs are obtained from browser content.

## Implementation and security

Files changed in this checkpoint:

- `friday/desktop/websites.py`: immutable exact URL registry and alias resolver.
- `friday/desktop/workflows.py`: standalone site commands and shared browser plan
  construction; uses the same registry for compound site resolution.
- `friday/desktop/browser_execution.py`: compiler/typed target policy accepts only
  the owner-registered destinations and preserves canonical target binding.
- `friday/desktop/firefox_url_handoff.py`: reuses the Checkpoint 3H adapter; only
  the validated final URL varies, while launcher, flags and trust checks remain
  fixed. Approval and results refer to the actual requested URL.
- `friday/desktop/handoffs.py`: content-free handoff errors now apply to all sites.
- `friday/tools/manager.py`: request-accepted output must match the exact requested
  allowlisted URL, fixed truthful message and explicit unverified-page status.
- `tests/test_firefox_url_handoff.py`: reusable mock fixture and updated imports.
- `tests/test_website_handoffs.py`: registry, aliases and execution security tests.
- This report and the phase overview link.

Each request follows the existing sequence: validate capability and exact URL,
prepare the pinned dispatcher/context, freshly authenticate with the existing
hidden Argon2id `OwnerAuthenticator`, request exact Allow once / Deny, bind the
one-use target/adapter/context lease, revalidate, then perform one bounded handoff.
Owner authentication is separate from executable permission. Persistent grants
are rejected. Neither repeated requests nor moving between sites reuse an
authentication or approval decision.

The logical fixed structure is:

```text
/usr/bin/snap run firefox --new-window <one exact registered URL>
```

The dispatcher is executed through its pinned file descriptor with `shell=False`,
`SNAP_REEXEC=0`, discarded standard streams and the existing reviewed desktop
environment. Launcher hashes, Snap package/provider validation, strict confinement,
process waiting, cancellation, five-second execution deadline and one-second
cleanup bound are unchanged from Checkpoint 3H. The general Snap app-only adapter
is not modified. No arbitrary executable paths, application choices or flags are
accepted. AT-SPI and independent URL verification remain outside this handoff.

Changing the approved target to another allowlisted URL still invalidates the
original lease. A returned result for a different URL is rejected by both the
controller and ToolManager. Incorrect passphrases and denied permission cause no
process; cancellation before start likewise prevents process creation. A normal
launcher exit yields only:

`Firefox navigation request accepted; page load not independently verified.`

This is `request_accepted`, with `page_load_verified=false`; it is not independently
verified navigation. Process failures, timeout, changed fingerprints and
cancellation do not turn into retries or stronger success claims.

## Validation

- 23 new website tests passed, including parameterized checks of all five URLs
  and all fourteen listed standalone/compound commands (including the retained
  Firefox YouTube command).
- 347 targeted tests passed across websites, existing URL handoffs, browser
  execution, application handoffs, Snap, owner authentication, routing, discovery
  and computer use.
- Full regression suite: 1,532 passed, with no failures, errors or skips. Existing
  headless socket tests used approved execution outside the sandbox.
- `git diff --check` passed.

New execution tests use mocked process creation, synthetic installation metadata,
and synthetic credential loaders/providers. A fixture guard rejects real credential
file access. Coverage includes aliases, canonical matching, incorrect passphrases,
denial, unknown destinations, substitution between approved URLs, injection,
changed launcher fingerprints, cancellation, timeout, accurate acceptance,
YouTube preservation, Snap restrictions and content/credential-safe reporting.

No `.env`, cookies, passwords, account information, browser profiles, messages,
conversations, repositories or page contents were read, displayed or modified.
No login automation, website opening, navigation, input or screenshots occurred.
No installation, Snap configuration change, commit or push occurred. Existing
uncommitted changes are preserved. Phase 1 remains paused.

## Remaining limitations

Page load, final URL, redirects and login state are not independently verified.
FRIDAY does not read web content or select links from it; ordinary server-driven
browser redirects are not controlled or observed by this launcher-only adapter.
Site login is left to the owner. Approved profile/study URLs are fixed in reviewed
code and require another implementation checkpoint to change.

Pinned launcher chain changes fail closed pending review. The installed packaged
chain retains the previously accepted Snap startup trust exception. If Firefox
is initially closed, the spawned invocation may become a long-lived browser
process and time out; only the invocation FRIDAY started is stopped, never an
already-running owner Firefox. A timed-out request may already have reached
Firefox; no automatic retry follows.

## Exact procedure for a separately approved one-time live test

1. Obtain separate approval for one request: `open github`, targeting exactly
   `https://github.com/Vigneshwar4053`. Implementation approval does not authorize
   real navigation.
2. Keep an existing Firefox instance running. In a private local terminal from
   `~/Projects/FRIDAY`, start:

   ```bash
   .venv/bin/python -B -m friday.main
   ```

3. Enter `open github` exactly once.
4. Enter the owner passphrase only at FRIDAY's hidden prompt, never in chat,
   command arguments, scripts or environment variables.
5. Check the permission prompt identifies Firefox, browser navigation, and
   exactly `https://github.com/Vigneshwar4053`. Choose `1` (Allow once) only for
   that exact prompt; otherwise choose `3` (Deny).
6. Record the fixed acceptance/failure response. Acceptance must say page load
   was not independently verified. Stop after this one request; do not retry,
   automate login, inspect browser content, take screenshots or add other sites.

A live test of any other registered destination requires its own exact approval.
