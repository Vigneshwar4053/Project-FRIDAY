> Historical phase report. The [full feature audit](FRIDAY_FULL_FEATURE_AUDIT.md) records the latest owner policy: approved native folder opens and Q resumes are attempted without cooldown or session suppression. Existing safety limits and trust checks remain.

# Phase 7A desktop integration repair

## Findings and status

**IMPLEMENTED:** session-local duplicate protection for Ubuntu Files and its exact
folder targets; explicit retry with fresh approval; stable pinned folder handoff;
launch-budget preflight; clearer process/window outcome messages. SQLite Q and its
existing status migration are unchanged.

**TESTED:** headless mocked execution, including command routing, the actual CLI
approval flow, Q persistence and descriptor identity after target substitution.
Read-only system/package diagnostics were also performed.

**NOT TESTED:** real window creation, visibility, focus, folder navigation or live
D-Bus acceptance of the descriptor target. No GUI was launched during this work.

**BLOCKED:** Snap Code and Firefox. No Snap backend was enabled, no packages or
system permissions changed, and no unsafe fallback was introduced.

## Actual duplicate-window causes

Every approved request previously called Popen, even immediately after an identical
accepted launch. There was no receipt guard. Q deduplicated its rows but did not
suppress desktop execution. These unnecessary starts consumed the existing
four-process session budget.

FRIDAY does not pass `--new-window` to Nautilus and does not execute its desktop
entry. The installed desktop entry does contain that flag, but changing it would
not repair this launcher. The package database reports Nautilus
`1:50.2.2-0ubuntu0.1`. Matching [GNOME 50.2.2 source](https://raw.githubusercontent.com/GNOME/nautilus/50.2.2/src/nautilus-application.c)
registers a GApplication command-line/open interface, attempts reuse by location
without the new-window hint, and can create a window when no match is found.
Single-instance dispatch does not imply a single window or confirmed focus.

The old folder argument was `/proc/self/fd/N`. When Nautilus forwards arguments
to an existing process, `self` refers to that recipient, which need not have the
launcher's descriptor. Fresh descriptor numbers also need not identify the same
location across launches. This is a concrete targeting/reuse risk, separate from
the missing duplicate guard. The exact live window state causing each owner's
observation cannot be independently established from the current diagnostics.

The environment reports `XDG_SESSION_TYPE=wayland`, `WAYLAND_DISPLAY=wayland-0`
and local `DISPLAY=:0`. `/run/user/1000` is owner-owned mode 0700. A read-only
`pgrep -x nautilus` found no visible PID at inspection time; it proves nothing
about the owner's earlier windows or processes outside this execution namespace.
The installed D-Bus service registers `org.gnome.Nautilus`, invoking the native
binary with its service flag. FRIDAY does not invoke that service directly,
enumerate windows, or treat a service/PID as window evidence.

## Repeated Files and folder requests

The guard stores only monotonic launch receipts in this FRIDAY session. Default
window: **20 seconds**, configurable through trusted
`Settings.desktop_duplicate_window_seconds` (valid range 1–120 seconds). At most
32 receipts are retained; expired receipts are removed lazily on requests. No
thread, timer, process probe or window monitor is added.

Keys contain normalized operation, approved application ID, validated target path
and directory device/inode, and reviewed URL when relevant. `open files`,
`open downloads` and `open documents` are separate activities. Different targets
and unrelated applications are unaffected. Protection is applied only to Ubuntu
Files operations, including the same action reconstructed from Q.

After executable/target validation, an immediate duplicate returns
`duplicate_suppressed` before typed approval. It starts no process, consumes no
budget, creates no profile/pin and makes no Q or project-history write. It reports
that a recent launch may already be open, never that a window exists or was focused.
Suppressed requests do not extend the receipt time. Invalid/missing/substituted
resume targets still fail validation rather than hiding behind suppression.

Explicit commands:

```text
retry open files
retry open downloads
retry open documents
retry resume my last work
```

Retry bypasses only the short guard. The fixed schema, current executable/target
validation, request-local exact approval, post-approval identity checks and
four-process limit still apply. The approval explains that another window may be
created. Denied retry launches nothing. Retry flags are neither persisted in Q
nor interpreted as grants. Compound requests, shell flags and arbitrary executable
names remain rejected. A suppressed numbered resume offers the corresponding
explicit open retry. It never silently chooses another saved activity.

After expiry, another ordinary request may launch after fresh approval; it is not
proof that the earlier window closed. Restart clears receipts and retains SQLite Q.
The guard cannot prevent duplicates created manually or after the short window,
and a retry deliberately permits another launch.

## Folder handoff and lifetime

Downloads/Documents continue to use the existing home/XDG resolver. No username or
folder path is hardcoded. Existing sensitive-path, approved-root, existence and
no-symlink checks remain in place. `list downloads` remains filesystem listing;
`open downloads` performs a separately approved desktop operation and grants no
FRIDAY file-reading authority.

For Nautilus folder requests the executor duplicates the verified directory FD,
keeps it non-inheritable in FRIDAY, and passes:

```text
-- /proc/<FRIDAY-pid>/fd/<held-directory-fd>
```

This names the same pinned directory in either the first child or a receiving
existing instance. Repeated approved requests for that path/device/inode share
the same held descriptor and argument. Name replacement does not retarget it.
There is no fallback to an unpinned canonical pathname or URI. Newly allocated
pins are released if Popen fails before a child is returned. The four-start limit
bounds retained pins; session close releases them and never terminates approved
GUI applications. VS Code retains its existing separate private-profile and
inherited-descriptor launch method.

The parent descriptor path is a session handoff, not a permanent path bookmark:
applications may retain it in their own UI, and it becomes unavailable when FRIDAY
closes. Q stores the original approved alias/path/inode, never PID/FD paths, and
revalidates these at resume. Kernel procfs access controls and application-specific
normalization/forwarding can still make GUI handoff fail. Live acceptance is
pending; no window/target success or focus is claimed merely from a process result.

## Launch budget and outcome messages

The limit remains four actually created processes per FRIDAY session. Failed
nonzero processes count because they were started; Popen failures, denials,
invalid requests and suppressed duplicates do not. A viable request after the
limit is blocked before approval with `launch_limit_reached`. Explicit retry
cannot increase or bypass it. The executor retains its execution-time limit too.

Outcomes remain distinct:

| Outcome | What FRIDAY knows |
| --- | --- |
| Security validation unavailable/blocked | No approved launch attempted |
| Permission denied | No launch authorized |
| `launch_accepted` | OS created the native process; initial launcher exited zero |
| `launch_outcome_unverified` | OS created the process; it remained running at the bounded wait |
| `duplicate_suppressed` | Recent matching receipt; no new process or window launched |
| `launch_limit_reached` | Four processes already started; no new process started |
| `launch_failed` | Initial process returned nonzero |

Neither accepted result verifies a window, focus, displayed folder, or completed
work. Responses now state the process observation and window/target uncertainty
separately. No verified-visible or verified-focused outcome is emitted.

## Snap investigation and security decision

Read-only diagnostics found Code at `/snap/bin/code` (symlink to `/usr/bin/snap`)
and Firefox at `/usr/bin/firefox` (script wrapper); `/snap/bin/firefox` also resolves
to the dispatcher. Snap desktop entries identify `code` and `firefox`, but arbitrary
Exec lines are not executed. Code metadata says classic confinement and an
`electron-launch` script invoking the CLI wrapper with `--no-sandbox`. Firefox
metadata says strict confinement, `firefox.launcher`, and GPU/desktop command chains.
Installed snapd reports `2.76.3+ubuntu26.04`. Fixed `snap run --help` was inspected
without launching any application; `snap list code` and `snap list firefox` timed
out under bounded read-only probes, so daemon registration/trust was not verified.

This environment reports UID 65534 (`nobody`) for `/`, `/usr`, `/snap`, `/snap/bin`
and the dispatcher/native binaries, failing the existing administrator-ownership
policy. That namespace observation is not proof of identical ownership on the
owner's normal host. No ownership/mode was changed to force trust.

A narrow adapter could validate names and constrain arguments, but those steps
alone cannot meet the current contract:

- Pinning the snap dispatcher does not pin the application ELF, selected revision,
  bases or command-chain scripts that snapd ultimately resolves. Rechecking YAML
  before dispatch does not atomically bind dispatch to that validated snapshot;
  revision/metadata can change between check and execution.
- Wrappers and command chains change environment and execute additional components.
  Calling the final ELF directly would bypass the reviewed packaging setup rather
  than preserve Snap's execution semantics.
- Snap helper namespace/FD handling was not shown to preserve the exact approved
  pinned folder/profile descriptor. Code's wrapper must also preserve disabled
  extensions, automatic-task policy and the fresh private profile.
- Trusted daemon registration and helper ownership were not established here.
  Strict confinement is not proof of requested-window identity or target success;
  classic confinement is not a security substitute for the native trust boundary.

[Snap confinement](https://snapcraft.io/docs/explanation/security/snap-confinement/)
and [security policy documentation](https://snapcraft.io/docs/explanation/security/security-policies/)
explain the packaging security model; they do not supply an atomic pinned app and
folder handoff for this runtime. No claim is made that every possible future Snap
integration is impossible. It is not safely implemented or validated under these
current guarantees and observations, so both applications remain fail-closed.

Owner alternative: explicitly review/provision administrator-owned native vendor
installations at the existing fixed paths. Microsoft's
[Linux setup](https://code.visualstudio.com/docs/setup/linux) documents the Code deb
option; Mozilla's [Linux installation documentation](https://support.mozilla.org/en-US/kb/install-firefox-linux)
provides native options. Native Firefox must resolve to the reviewed ELF rather
than a Snap wrapper. The owner must approve any installation separately; nothing
was installed/uninstalled, downloaded or modified in system packages here.

## Q preservation and automated verification

Accepted launches retain the current SQLite policy, including running/window-
unverified outcomes. A real approved retry refreshes timestamp/status, preserves
the stable entry ID, and moves it to first place. A suppression or denied/failed
retry leaves every saved row unchanged. Three-slot eviction, restart persistence,
voice-provenance exclusions, safe descriptors and fresh resume permission remain.
A Q entry is never treated as a persistent execution grant or as window evidence.

Final verification: **1,097 tests passed**, including 26 new desktop repair tests.
`make -C native/sync` passed (already up to date); `git diff --check` passed.
Every GUI/audio execution in automated tests is mocked. Coverage includes first
launch, immediate repeat, retry/denial, expiry, bounded guard configuration,
different target identities, no speculative Q refresh, launch accounting, failure
cleanup, stable parent-FD forwarding, exact folder substitution, numbered resume,
latest-resume suppression without fallback, Q persistence, no shell/monitor,
fixed Snap rejection and native trust checks. Existing repeated-accepted Q tests
now use explicit retry where appropriate; no tests were skipped or hidden.

## Exact files changed in this repair

- `friday/desktop/guard.py` (new)
- `friday/desktop/runtime.py`
- `friday/desktop/routing.py`
- `friday/config/settings.py`
- `friday/main.py`
- `tests/test_desktop_repair.py` (new)
- `tests/test_desktop.py` (structured launch-limit expectation)
- `tests/test_recent_work.py` (explicit accepted retry in the reorder test)
- `README.md`
- `docs/PHASE_7A_DESKTOP.md`
- `docs/PHASE_7A_ENHANCEMENT.md` (follow-up link)
- `docs/PHASE_7A_Q_PERSISTENCE.md` (follow-up link)
- `docs/PHASE_7A_DESKTOP_REPAIR.md` (this report)

Existing unrelated working-tree modifications were preserved. No Git mutation,
release/version change, package action, login setting change, microphone activation
or hidden monitoring occurred.

## Manual acceptance commands — owner execution pending

Run the headless checks from the existing repository:

```bash
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
git diff --check
```

On a normal Ubuntu desktop with already-trusted native Nautilus:

```bash
.venv/bin/python -B -m friday.main --adaptive
```

Type these at FRIDAY, choosing **1** only at the explicit permission prompts:

```text
open files
open files
show Q
retry open files
```

Expect approval on the first request, suppression with no approval on the second,
one unchanged Q entry, and fresh approval for retry. First deny retry with **3**;
request it again and allow with **1**. Observe the real desktop yourself; the CLI
must never claim it focused a window.

Restart FRIDAY to begin a fresh four-start budget, retaining Q. Then:

```text
open downloads
open downloads
open documents
show Q
```

Allow the first Downloads and Documents requests. The repeated Downloads request
must suppress without approval; Documents must not be suppressed by Downloads.
Confirm each actual displayed folder manually, including when Nautilus was already
open before FRIDAY. Keep FRIDAY running while testing the descriptor handoff.
If the handoff fails, retain the error/uncertainty; do not substitute an unsafe path.

In Show Q, select the displayed Downloads number. An immediate resume of the
recently launched target must suppress without approval or Q changes. Use
`retry open downloads` to request a new launch and deny/allow at its fresh prompt.
Alternatively wait more than 20 seconds, Show Q again, and select Downloads:
expect fresh exact-target approval. Then quit/restart and verify the three saved
slots/IDs/order persist; no previous receipt or execution permission persists.

To exercise the unchanged launch limit in a fresh session, make four approved
`retry open files` requests (these may deliberately create extra windows). A fifth
must report the limit without approval or process creation. No extra budget is
available from retry. Test this only if the owner wants four real launch attempts.

Finally type:

```text
open vs code
open firefox
retry open vs code
retry open firefox
```

On Snap-only installations expect explicit secure-launch unavailability, no unsafe
fallback, no Q changes and no retry bypass. The owner may separately approve a
reviewed native installation; this task performs no installation. Close with
`quit`. Real GUI focus/visibility and Snap launches remain NOT TESTED/BLOCKED.
