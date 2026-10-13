# Checkpoint 3L: website registry and deterministic Google search

Status: implementation and mocked verification complete; production URL/search
execution is disabled until the reported live Firefox handoff failure has an
established cause and a reviewed repair. No live navigation was performed.
Phase 1 ChromaDB/RAG remains paused.

## Existing support and registry

The existing immutable `WEBSITES` and `SITE_ALIASES` mappings in
`friday/desktop/websites.py` are extended, not replaced. The workflow compiler,
typed browser target, fresh hidden owner authentication, exact Allow once/Deny
approval, reviewed Snap launcher, five-second deadline and cancellation remain
the execution path. App-only Snap launch policy is unchanged.

| Destination | Exact URL | Aliases |
| --- | --- | --- |
| GitHub (existing) | https://github.com/Vigneshwar4053 | github, my github |
| LinkedIn (existing) | https://www.linkedin.com/in/sameti-thirumani-vigneshwar/ | linkedin, my linkedin |
| WhatsApp (existing) | https://web.whatsapp.com/ | whatsapp, whatsapp web |
| PW Study (existing) | https://www.pw.live/study-v2/study | pw study, physics wallah, pw_study, gatewall, gatewalla, my gatewall, my gatewalla |
| YouTube (existing) | https://www.youtube.com/ | youtube |
| Google (new) | https://www.google.com/ | google |
| Stack Overflow (new) | https://stackoverflow.com/ | stackoverflow, stack overflow |

`open <alias>` and `open firefox and go to <alias>` resolve without a model.
Gatewall aliases use the existing PW Study entry following the owner's update;
there is no guessed domain and no duplicate destination.

Explicit website intent (`open website unknownsite`, `open unknownsite website`,
`open unknownsite in firefox`, an unregistered URL, or the explicit Firefox
navigation grammar) requests an exact HTTPS URL for review without filesystem
discovery. Supplying a URL does not itself register or authorize it. Ambiguous
bare names such as `open portfolio` remain legitimate filesystem discovery.

## Search target and authorization

Supported grammar:

- `search firefox for python tutorials`
- `open firefox and search for python`
- `search google for cybersecurity`
- `search for OWASP top 10`
- `google python decorators`
- `search stackoverflow for python errors`
- `search <registered alias> for <query>`

`urllib.parse.urlencode({'q': query})` constructs the query component beneath
the fixed `https://www.google.com/search` endpoint. For example, the first
command resolves to `https://www.google.com/search?q=python+tutorials`.
Unicode uses UTF-8 percent encoding; ampersands, plus signs, percent signs,
question marks and fragments stay inside `q`. Flags such as `--private` are
query text, never additional arguments. Existing shell-marker and compound
action rejection remains in place. Queries are bounded to 256 UTF-8 bytes;
the complete encoded URL is bounded to 2048 ASCII bytes. Domain-specific
queries include the `site:<registry hostname>` prefix inside that bound.
Unknown domains, including explicit unregistered `site:` operators, are denied.

Search and navigation use the same reviewed handoff with fixed arguments:
`/usr/bin/snap run firefox --new-window <exact URL>`. There is no shell, extra
flag, arbitrary search provider, profile access, browser inspection or retry.
The complete encoded URL and original query form the owner-authentication and
Allow once scope. Targets and context are revalidated before process startup;
successful results must match the exact target again at the gateway.
An exit of zero means request acceptance only, never verified page load.
The existing acceptance wording is retained for both URL operations.

## Live handoff blocker

Read-only checks on 2026-10-12, outside the sandbox's UID remapping, found:

- Firefox revision `8763`; package/runtime registration and dispatcher checks passed.
- All seven fixed launcher-chain hashes matched. No hash was changed.
- Context preparation took about 86 ms; revalidation took about 43 ms.
- The environment passes `XDG_RUNTIME_DIR=/run/user/1000/snap.code` and constructs
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/snap.code/bus`.
  That socket is absent; `/run/user/1000/bus` exists.

The absent constructed bus is a concrete validation gap and a plausible runtime
cause, not proof of the failed invocation's exit stage. Existing code discards
launcher stderr and merges startup exceptions, nonzero exit and revalidation
exceptions into `url_handoff_failed`. Timeout and cancellation have separate
statuses; the original terminal status, return code and elapsed time were not
provided. Current metadata cannot prove past identity changes or process outcome.
No navigation was used to reproduce the failure.

Accordingly, `FirefoxUrlHandoff` defaults to `UnavailableFirefoxUrlAdapter`.
The assistant explicitly reports the blocker, with no authentication prompt or
launch. The real adapter remains implemented and is constructor-injected by
mock tests. There is no environment toggle or CLI bypass. No speculative bus
rewrite, deadline extension, fingerprint relaxation, Snap-interface change or
success assumption was applied. Re-enabling requires a separately reviewed
repair supported by failure-stage evidence. The verified-window backend remains
unavailable in production.

## Verification and one-time owner live test

Mock tests cover all registry entries and aliases, Gatewall routing, explicit
unknown website intent, retained local discovery, search encoding and bounds,
domain restrictions, fresh authentication, denial, target substitution, changed
launcher/context fingerprints, timeout, cancellation, no shell, redacted errors
and the disabled production default. The full suite uses temporary credential
fixtures; the project's `.env` is never read or modified during development.

Final validation: 188 targeted tests passed; 1,545 full-suite tests passed outside
the sandbox; `git diff --check` passed. The initial sandbox suite hit the four
known headless IPC permission errors; its two exact-URL regression failures
were corrected by retaining the original raw navigation allowlist check before
canonicalization. No failures remain in the final suite.

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest test_checkpoint3l test_firefox_url_handoff test_website_handoffs test_browser_execution test_discovery_workflows test_tool_routing
.venv/bin/python -B -m unittest discover -s tests
git diff --check
```

**Do not perform a live test on this checkpoint while the blocker remains.**
After failure-stage evidence establishes the cause and a repair/re-enablement
has been reviewed, the owner can perform this exact one-time procedure:

1. Start FRIDAY from a normal desktop terminal with
   `.venv/bin/python -B -m friday.main`. Keep the microphone off. Existing speech
   startup behavior is unchanged; use `/q` to disable automatic speech if needed.
2. Enter `open gatewalla`. Verify the approval scope is exactly
   `navigate_firefox_to_exact_url [firefox] https://www.pw.live/study-v2/study | value: https://www.pw.live/study-v2/study`.
   Enter the owner secret only through hidden terminal authentication; choose
   `1` (Allow once) only for that scope.
3. Record only the fixed result status and elapsed time. Acceptance does not
   establish page load. On failure, timeout or cancellation, stop; do not retry.
4. Only if step 3 is accepted, enter `search firefox for python tutorials` once.
   Verify the exact scope is
   `search_firefox_for_query [firefox] https://www.google.com/search?q=python+tutorials | value: python tutorials`.
   Authenticate freshly and choose `1` only for that exact scope.
5. Record the fixed result and stop. Do not inspect or share browser content,
   credentials or raw launcher diagnostics. A denial at either approval must
   produce no invocation.

No packages were installed, Snap permissions changed, commits made or pushes
performed by this checkpoint.
