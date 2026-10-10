> Historical phase report. The [full feature audit](FRIDAY_FULL_FEATURE_AUDIT.md) records the latest owner policy: approved native folder opens and Q resumes are attempted without cooldown or session suppression. Existing safety limits and trust checks remain.

> Current lifecycle repair and native command defaults are documented in [Browser reuse and ownership repair](PHASE_7A_BROWSER_REUSE.md). The test count below belongs to the initial implementation.

# Reliable single-window folder navigation: implementation report

## Root cause and selected toolkit

The prior backend only suppressed Nautilus launches. Nautilus's reviewed Open
and ShowFolders interfaces do not accept a target window; they may reuse a window
already at a requested location or create another. Its published window/location
map cannot supply navigation control. Existing terminal `go back` uses listing
history, which a desktop launch did not populate. That explains both live failures.
See the [read-only desktop investigation](PHASE_7A_NAVIGATION.md).

The owner desktop has system Python 3.14.4, PyGObject 3.56.2 and GTK 4.22.4 on
Wayland/GNOME 50.1. GTK imports successfully with system Python; it is absent from
the venv. The reviewed backend uses a separate pinned native system interpreter,
isolated Python imports and fixed SHA-256-verified GTK helper code. Runtime
preflight outside the sandbox passed without creating a window. No packages or
models were installed. The package/type-library paths currently review Ubuntu
x86_64; other installations fail closed pending review.

## Security architecture and lifecycle

The [design recorded before implementation](FRIDAY_BROWSER_DESIGN.md) describes
the permission boundary. One private anonymous Unix SOCK_SEQPACKET socketpair
connects parent and renderer. Only the child endpoint is inherited; no listener,
port, public service or token file exists. FD possession authenticates the channel
within FRIDAY's existing trusted owner-process boundary. Sequence numbers, bounded
packets, exact schemas, matching location/op responses and mapped GTK widget state
protect acknowledgment/commit. Unsolicited read/write/execute requests are rejected.
This is not an OS sandbox against a compromised owner process or system GTK.

GTK creates one Window and updates its current-location label and authorized
listing in that object. GTK's mapped state and matching label acknowledge the
operation; neither compositor visibility nor focus is claimed. Window close ends
the helper. Health checks occur only for requested operations, not background
window monitoring. Confirmed exited helpers are reaped before reopening. An uncertain live helper
is retained and blocks replacement; health checks do not depend on mapping. Only the
managed helper may be terminated; unrelated windows/applications are untouched.
FRIDAY exit closes its managed browser.

Interpreter ownership/ELF identity is validated and pinned, then revalidated after
approval. Helper bytes must match the reviewed hash and be a regular owner/root
file without group/world write permission (the new helper is mode 0644). Target
folders use existing no-symlink walks, sensitive-path checks, fixed aliases and
registered projects. Resume/history mappings and device/inode identity are checked
again; directory substitution during approval prevents execution. The worker never
gets filesystem target descriptors or file-opening authority, only sanitized
labels and already-authorized bounded listing strings.

The GUI uses a fresh mode-0700 internal profile under `data/browser-profiles`,
passed by FD for HOME/config/data/cache. This avoids personal GTK CSS, user fonts
and application settings. Fixed local GIO and in-memory settings backends prevent
remote location dispatch; GTK still loads trusted system assets. Internal toolkit
cache directories may remain after exit, with no browser listing/history storage.

Permissions stay separate:

| Action | Authorization |
|---|---|
| New browser process | Typed `launch_browser`, allow once only |
| Select exact approved folder | Typed `navigate_browser`, allow once only |
| Display directory names/types | Existing `list_directory` filesystem gateway, roots and grants |
| Open file | Unavailable in this minimal GUI |
| Modify file | Unavailable in this minimal GUI |

Both launch and initial navigation approvals precede process creation. Navigation
alone displays a location, with contents hidden. `list browser contents` obtains
a separate bounded filesystem listing, guarded against target replacement; it
does not read file contents or follow listed symlinks. Existing configured read
roots/persistent read grants retain their meaning. No desktop approval creates a
filesystem grant. Home listing remains forbidden by the existing root policy;
Home navigation is allowed as a location landmark. No directory scanning occurs
on navigation. No file activation, modifications, thumbnail generation, network
requests, microphone changes or shell execution are implemented.

## Commands, history, Q and launch budget

| Command | Current behavior |
|---|---|
| `open friday browser` | Managed browser Home |
| `open files` / `open file manager` | Ubuntu Files at Home; safe replacement unsupported |
| `open downloads in friday browser` / `open documents in friday browser` / `open home in friday browser` | Same managed window, exact approved location |
| `open my friday project folder in friday browser` | Registered folder in managed browser |
| `go back` / `go forward` | Managed browser history while it is active |
| `list browser contents` | Separately authorized bounded GUI listing |
| `Show Q`, menu number, `Resume my last work` | Original saved backend; fresh exact approval |
| `open ubuntu files` / `open nautilus` | Existing Nautilus native launcher |
| `open downloads in ubuntu files` | Existing Nautilus folder backend and honest reuse limitation |
| `retry open downloads in ubuntu files` | Fresh-approved possible extra Nautilus window |
| `list downloads` | Existing terminal filesystem listing |
| `open my friday project` | Existing VS Code project command |

This is an intentional documented command migration, not a replacement for
Nautilus. GUI navigation is terminal-driven so all approvals remain typed in the
existing gateway; clicking displayed filenames cannot launch or modify anything.
Other terminal listing navigation commands retain their behavior when managed
browser history is absent. While that history is active, go back/forward selects
it; history is session-local and limited to 16 exact targets. Failed/denied
navigation never moves the cursor. Repeated current locations do not append, and
new visits discard forward history. Every transition clears displayed contents.

Q keeps three distinct activities using the same SQLite table/upsert/eviction
transaction, persistent stable IDs and original validated resume targets. Browser
identity is `friday_browser`, separate from `files`. Outcome `navigation_confirmed`
means a verified managed renderer response, not a process-only inference. Summaries
describe managed navigation; visibility remains explicitly unverified. Denied,
failed or unsupported actions do not refresh Q, and voice-derived actions remain
excluded from persisted metadata. Repeated navigation refreshes the same entry.

SQLite's old CHECK constraint is extended through a transactionally rebuilt
known table, preserving all old columns, entries and IDs. Unknown custom
indexes/triggers on an old table cause a clear fail-closed database initialization
error, with no partial migration. Newer tables need no rebuild. Historical
`launched_at`/`launch_status` column names now also hold the last acknowledged
managed navigation timestamp/outcome. They do not imply a new process start.

First process start counts toward the shared four-launch limit, even if GTK then
fails. Existing-window navigation consumes no slot, including at the launch limit.
Closing/reopening requires fresh launch and navigation approvals and another slot.
A failed Popen does not consume a slot. No launch limit was removed or increased.

## Exact files changed

- `friday/desktop/browser.py` (new controller transport/history)
- `friday/desktop/browser_worker.py` (new fixed GTK renderer)
- `friday/desktop/runtime.py`
- `friday/desktop/routing.py`
- `friday/desktop/navigation.py` (explicit Nautilus retry wording)
- `friday/desktop/recent.py`
- `friday/main.py`
- `friday/memory/database.py`
- `friday/memory/manager.py`
- `tests/test_managed_browser.py` (new headless regressions)
- `tests/test_desktop.py`
- `tests/test_desktop_navigation.py`
- `tests/test_desktop_repair.py`
- `tests/test_recent_work.py`
- `tests/test_tool_routing.py`
- `README.md`
- `docs/PHASE_7A_DESKTOP.md`
- `docs/FRIDAY_BROWSER_DESIGN.md` (new design)
- `docs/PHASE_7A_MANAGED_BROWSER.md` (this report)

Historical Nautilus tests now issue explicit Ubuntu Files commands; none were
skipped. Owner changes outside these focused edits remain untouched. No commits,
release operations, package changes or system permission changes were performed.

## Verification and owner acceptance

Headless tests cover one renderer, Home/Downloads/Documents/back/forward, closed
window reopen, bounded history, denied launch/navigation/listing, stale mappings,
symlink escapes, invalid targets, authenticated channel/response rejection, private
runtime configuration, no automatic listing or file reads, launch budget, Q's
three-slot persistence/migration/resume, voice exclusion and an actual CLI sequence.
All GUI/process creation is mocked; no real GTK window or Nautilus launch occurred.

Completed verification: **1,154 tests passed**, including 40 new managed-browser
tests. `make -C native/sync` passed (already up to date), and `git diff --check`
passed. Read-only production interpreter/source preflight passed outside the
sandbox; this verifies launch prerequisites, not real GUI behavior.

Required checks:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
git diff --check
```

**Real desktop acceptance remains not tested.** Start:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --adaptive
```

1. Enter `open friday browser`. Approve launch with `1`, then separately approve Home
   navigation with `1`. Verify exactly one **FRIDAY Browser** window appears with
   Home in its location display and contents hidden. Nautilus must not be opened.
2. Enter `open downloads in friday browser`, then `1`. Enter `open documents in friday browser`, then `1`. Verify the
   same window's location changes each time, without additional launch prompts.
3. Enter `go back`, then `1` (Downloads); repeat (Home). Enter `go forward`, then
   `1` (Downloads). Verify the same window and location display each time.
4. Enter `list browser contents`. Approve the separate filesystem listing if
   prompted. Verify bounded names/types appear, without opening any file. Navigate
   again and verify that contents are hidden until separately requested.
5. Enter `open documents in friday browser`, then `3`. Verify location, history and Q do not change.
   `Show Q` should contain accepted distinct locations only. Choose Downloads by
   its displayed number, then `1`; verify fresh navigation approval and reuse.
6. Close the FRIDAY Browser using its window close control. `open documents in friday browser` now
   requires launch and navigation approvals again; approve each with `1`. Verify
   one replacement managed window, with no stale-window claim.
7. `quit`, restart, then `Show Q`. Saved locations persist; select one and approve
   launch plus navigation separately. No old window handle/history is persisted.
8. In a fresh session, close/reopen the browser four times total, approving both
   actions each time. While the fourth window stays open, navigate repeatedly:
   this must remain possible. Close it; a fifth reopen must hit the launch limit
   without another launch approval. Native launches share that same limit.
9. Optional compatibility check: `open ubuntu files`, approve `1`. It remains
   Nautilus; it is not the managed browser. Do not expect managed back/forward
   commands to control that window.

Limitations: fixed approved landmarks/projects only; no child-folder clicking,
file activation/modification or GUI permission shortcuts; Home contents remain
restricted; no independent compositor focus/visibility verification; toolkit or
trust failures fail closed; system package paths require review on other platforms.
The one-window guarantee is per FRIDAY session's managed renderer, not across
multiple independently started FRIDAY processes or unrelated Nautilus windows.
