> Historical phase report. The [full feature audit](FRIDAY_FULL_FEATURE_AUDIT.md) records the latest owner policy: approved native folder opens and Q resumes are attempted without cooldown or session suppression. Existing safety limits and trust checks remain.

# Phase 7A: same-window Files navigation investigation

## Findings and support boundary

Read-only inspection of the owner's desktop found Wayland, GNOME Shell
50.1-0ubuntu1.2 and Nautilus 1:50.2.2-0ubuntu0.1. Nautilus already owned its session
D-Bus name. Inspection did not open, focus, close or navigate a window.

Live introspection exposed `org.gtk.Application.Open`,
`org.freedesktop.Application.Open` and FileManager1 `ShowFolders`, `ShowItems`,
`ShowItemProperties`. The latter publishes `OpenLocations` and
`OpenWindowsWithLocations`: identities are observable, but none of these methods
accepts a target window identity. The inspected window's exported GTK actions
include `go-home`, tab controls and menu actions, without a directory navigation
action. Application actions include new/clone window, not directory navigation.
The Home-only action cannot implement approved arbitrary reviewed locations, nor
does it solve secure attribution of a window to a FRIDAY launch.

The matching [Nautilus 50.2.2 implementation](https://raw.githubusercontent.com/GNOME/nautilus/50.2.2/src/nautilus-application.c)
searches for a window already showing the requested location and otherwise
creates a window. Its internal C navigation functions are not a supported remote
API for choosing a window. [FileManager1 implementation](https://raw.githubusercontent.com/GNOME/nautilus/50.2.2/src/nautilus-freedesktop-dbus.c)
delegates folder requests to this opening behavior. Calling Open/ShowFolders
would not meet the owner's same-window guarantee. No such call was added.

Root cause: FRIDAY launched Nautilus again for each distinct approved target;
the previous exact-target cooldown could not prevent cross-location opens or
opens after expiry. Stable descriptor handoff protects the target identity but
does not change Nautilus' window-selection behavior. Desktop entry new-window
flags are not used by FRIDAY. Process startup cannot prove a window or location.

**Blocked:** true, verified same-window navigation on this reviewed desktop API.
No keyboard shortcuts, coordinates, window-title matching, Shell evaluation,
plugins, unrestricted actions or background monitoring were introduced. A future
backend needs a reviewed window-targeting contract, trusted application/window
attribution, exact directory handoff and independent post-operation verification.
Merely discovering a window object or adding a mock backend is insufficient.

## Implemented fallback

`open files` (and Files aliases) explicitly resolves Home; Downloads and Documents
resolve existing trusted home/XDG configuration. `open my friday project folder`
uses Nautilus for the registered folder; `open my friday project` keeps VS Code.
Unknown projects, missing paths, symlinks, sensitive targets and changed resume
identities fail closed. Executable/target descriptors and post-approval checks
remain unchanged. Files requests with URL arguments are rejected.

The narrow controller holds one session-local receipt: application identity,
last accepted approved folder and device/inode, and launch outcome. Reuse support
is false; managed window identity and verified navigation outcome are absent.
It stores no stale window handle and never assumes a manually closed window is
still open. Without a verified API it cannot detect closure safely; explicit
retry is required in that case too. State is cleared at FRIDAY exit.

First viable Files request gets exact typed `navigate_folder` permission with
risk `desktop_navigation`; the prompt explicitly says it will launch. Every
subsequent implicit Files request is blocked across locations for the remainder
of the session, including numbered/latest Q resume, without a permission prompt,
process start, Q write or budget consumption. It never silently selects another
Q activity. This replaces cooldown-only behavior for Files; the existing cooldown
configuration does not restore unsupported navigation.

`retry open files`, `retry open downloads`, `retry open documents`,
`retry open my friday project folder`, and `retry resume my last work` bypass
only suppression. They require new exact typed approval, revalidation and the
unchanged four-process budget, and warn that another window may be created.
Neither accepted launches nor retries grant filesystem reads. No persistent
desktop grant is created. Snap policy, speech and microphone behavior are unchanged.

Q retains the same SQLite table, stable IDs, upsert/eviction transaction and three
distinct activities. New Files activities are folder descriptors, including Home.
Accepted process launches alone refresh Q, with factual startup summaries and
`Window not verified`. Unsupported navigation never creates a Documents/Downloads
entry just because it was requested. Explicit accepted retries reorder without
duplicates. Existing legacy application-only entries remain readable and offer
Home with fresh approval; the new Home folder identity is distinct from the
legacy targetless application identity until old entries age out. No history or
visibility is fabricated and no stored window state survives restart.

## Verification and manual acceptance

Headless tests mock every process launch. Positive verified reuse/navigation is
not claimed or tested as working: no production API satisfying that contract was
found. Tests exercise the supported fallback, state lifecycle, exact permission,
invalid targets, post-approval swaps, denied/failed outcomes, Q resume/persistence,
registered folders, no monitoring/shell, and unchanged launch limits.

Verification completed: **1,114 tests passed**, including 17 new fallback tests;
`make -C native/sync` passed (already up to date); `git diff --check` passed.
Existing tests expecting repeated implicit launches were updated to require
explicit retries, while retaining their validation, Q and failure assertions.
No tests were skipped to obtain this result. Windows opened outside FRIDAY, or
before a restart, cannot be attributed to this session; even the first approved
launch can open another window. This fallback does not guarantee one window
globally and does not claim otherwise.

Run the required checks:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
git diff --check
```

Real GUI acceptance remains **not tested**. Launch FRIDAY manually:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --adaptive
```

Enter these commands in order (numbers are typed only in an active prompt):

1. `open files`, then `1` to allow once. Inspect whether Home opens; FRIDAY reports
   only the process outcome, with window/location unverified.
2. `open downloads`, `open documents`, `open files`, `open downloads`. Each must
   explain unsupported same-window navigation, without approval or another launch.
   Waiting beyond the former cooldown must not change this behavior.
3. `Show Q`: only the accepted Home activity should have been added. Enter its
   menu number: resume must explain the same limitation, without launching.
4. `retry open downloads`, then `3`: denial must leave windows, Q and budget alone.
5. `retry open downloads`, then `1`: fresh approval and possible additional
   window, explicitly unverified. Inspect the actual folder manually. `Show Q`
   now includes Downloads, preserving Home.
6. `retry open documents`, then `1`; `retry open files`, then `1`. Q has at most
   three distinct locations, Home most recent. Four actual starts have occurred.
   `retry open downloads` must hit the launch limit without a permission prompt.
7. `quit`, restart with the same command, and `Show Q`. Entries persist; no window
   receipt persists. Selecting a Files entry requires fresh approval. Manually
   close Files and test suppression versus explicit retry: no closure is inferred.

Acceptance demonstrates the safe fallback, not same-window navigation. Navigate
manually inside Files to obtain the owner's single-window workflow today.
