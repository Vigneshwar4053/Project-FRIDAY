> Historical phase report. The [full feature audit](FRIDAY_FULL_FEATURE_AUDIT.md) records the latest owner policy: approved native folder opens and Q resumes are attempted without cooldown or session suppression. Existing safety limits and trust checks remain.

# Browser lifecycle and exact window ownership repair

## Findings and scope

The adapter and ManagedBrowser object persist across interactive tool calls. The
worker contains a persistent GLib loop; completing a request removes its callback,
not the event loop. The prior worker made every response, including health ping,
wait for GTK mapping. The prior parent treated every failed/late health response
as closure, terminated the child, cleared transport state and requested another
launch. Execution failures also terminated a still-live renderer. This is a
concrete destructive lifecycle defect, rather than evidence that a new adapter
was created per call. Previously stderr and failure reasons were discarded, so
we cannot establish which exact GTK event or crash triggered the owner's past
session. No renderer was live during the read-only inspection.

The reviewed owner session is Wayland with GNOME 50.1 and Nautilus 50.2.2.
The [desktop investigation](PHASE_7A_NAVIGATION.md) records live API inspection
and matching upstream source. Open/ShowFolders may reuse an existing location or
create another window; they do not return a FRIDAY creation token. Observable
window paths, process IDs, titles and before/after enumeration cannot prove
ownership, especially with concurrent user actions. Nautilus did not own its
D-Bus name in the current read-only check. No desktop window was launched or closed.

**Blocked:** safe Nautilus window replacement and verified native same-location
reuse. No exact-window close operation or approval prompt is added because there
is no verified window on which that operation could safely execute. FRIDAY never
closes a Nautilus process or guesses ownership. Subsequent implicit native launches
remain suppressed across locations without consuming approval or launch budget.
Explicit retry may leave multiple windows; it is not a one-window guarantee.

## Implemented lifecycle

Health ping acknowledges the live managed loop independently of mapping. Navigation
still requires a mapped GTK window and matching location label. This confirms
application state, not compositor visibility or user work. Closing the GTK window
quits the loop and closes IPC; confirmed process exit is reaped before a replacement
can be offered with fresh launch and navigation approvals.

Timeouts preserve the live child and pending request. The next requested health
check can consume that exact late acknowledgment, then request a fresh ping.
Malformed/forged acknowledgments latch the channel unusable. An inconclusive check
never starts a replacement, kills a live child or silently chooses another Q row.
The owner can close the managed window manually and retry after exit is detected.
Navigation failures save no Q entry and do not implicitly relaunch. FRIDAY session
exit still cleans up its own isolated renderer, never another application's process.

Diagnostics retain at most 16 fixed event codes, process state and exit code.
Worker stderr is nonblocking and only reviewed static codes are exposed. Private
paths, directory contents, IPC FDs/tokens and raw exception text are not logged.
`show browser status` is an explicit read-only diagnostic, without background checks.

Both initial typed approvals precede process creation. Every subsequent navigation,
including repeat, history and Q resume, needs a fresh exact navigation approval.
An already-selected response is reported only after the renderer acknowledges it.
Navigation uses no additional slot; actual browser creation still consumes one of
the unchanged four-process desktop launch slots. Existing interpreter/helper trust,
private socketpair, schema/sequence checks, target inode/mapping validation and
separate filesystem listing permissions remain in place. There is no shell,
unrestricted desktop action, microphone activation or automatic file modification.

## Commands and Q compatibility

The latest owner requirement restores bare `open files`, `open downloads`,
`open documents` and `open my friday project folder` to Ubuntu Files / Nautilus.
This changes the preceding managed-browser default and is documented explicitly.
Use `open friday browser` for Home, or `open downloads in friday browser`,
`open documents in friday browser`, `open home in friday browser` and
`open my friday project folder in friday browser` for managed navigation.
`go back` / `go forward` use its bounded session history while active.

New Q descriptors have version 3 and explicit `nautilus_location` or
`friday_browser_location` activity types. Versions 1/2 remain readable and validated
against their original schema. Showing historical data changes no SQLite row;
application labels make the backend explicit. Stable activity keys retain the old
folder namespace, so a later approved repeat refreshes the existing stable ID.
The atomic upsert updates its type alongside its new descriptor only after an
accepted action. No startup bulk rewrite/migration occurs.

A plain menu number resumes the displayed original application with fresh approval.
While the Q menu is active, `resume Q 2 in friday browser` offers that stored
approved folder in the separate browser. The permission effect explains the change.
The stored alias/path/inode are revalidated, and denial/failure changes no history.
A confirmed conversion records a separate browser activity without rewriting the
native row, subject to normal three-slot eviction. Entries without a saved folder
identity cannot be converted. Q represents recent managed actions, never currently
open windows; closing a window does not delete its Q activity.

## Verification and manual GUI acceptance

Headless tests run the actual worker callbacks/protocol with GTK stand-ins over
private socketpairs, as well as the existing approval/SQLite fixtures. They cover
persistent commands, hidden-window health, close detection, replay/malformed
rejection, pending response recovery, no implicit replacement, budgets, denied
conversion, historical-row preservation and stable identities. No real GUI is
launched. The execution sandbox denies socket send/receive, so these headless tests
require execution outside that sandbox; they do not need a graphical session.

Run from the repository:

```bash
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
git diff --check
```

For manual acceptance on the owner's Ubuntu session:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday
```

Enter these commands, choosing `1` (Allow once) only at each permission prompt:

```text
open friday browser
show browser status
open downloads in friday browser
open documents in friday browser
open home in friday browser
open downloads in friday browser
open downloads in friday browser
go back
go forward
show browser status
show Q
```

Expect one Browser window, launch approval only on the first operation, fresh
navigation approval each time, a `worker_started` event in the first diagnostic
response, and no additional launch budget use. The 16-event ring may evict that
early event; it is not a total launch counter. Minimize then navigate to check health/reuse; do
not infer compositor visibility from diagnostic or mapped-widget status. Close
that Browser window manually and navigate again: fresh launch and navigation
approvals must appear before one replacement window is created. Deny either
permission to verify no launch/Q update.

For a labeled historical Nautilus folder, enter `show Q`, then its displayed
number. Confirm the native application is explicit and requires fresh permission,
or receives the honest session suppression message. Enter `show Q` again and
`resume Q 2 in friday browser` using the actual native row number. Approvals must
explicitly offer Browser conversion; the old row stays intact until normal queue
eviction. Restart FRIDAY, show Q and resume a Browser row to verify persistence
and new-session approvals.

For the native limitation, restart FRIDAY, enter `open files`, approve, then
`open downloads`. The second request must explain that exact ownership/replacement
cannot be verified; no window is closed. `retry open downloads` requires fresh
permission and may create a second Nautilus window. No one-window claim is made.

**Not tested:** real GTK persistence, mapping and compositor behavior on the owner
GUI. Those require the manual sequence above. No packages, permissions, releases
or Git history were changed.

Files changed for this repair: `friday/desktop/browser.py`, `browser_worker.py`,
`runtime.py`, `routing.py`, `recent.py`, `navigation.py`, `friday/memory/manager.py`,
`tests/test_managed_browser.py`, `test_browser_lifecycle.py`, `test_desktop.py`,
`test_recent_work.py`, `test_tool_routing.py`, `README.md`,
`docs/PHASE_7A_MANAGED_BROWSER.md`, `docs/FRIDAY_BROWSER_DESIGN.md`, and this report. Other pre-existing owner changes
were preserved.

Final checks: **1,167 automated tests passed**, native sync build was up to date, and `git diff --check` passed. Real GUI acceptance remains pending.
