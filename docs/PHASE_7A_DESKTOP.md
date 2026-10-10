# Phase 7A — unreleased desktop foundation

This foundation does not release v0.7.0 or change the release sequence. Phase 6E
v0.5.0 still needs owner hardware validation; v0.6.0 Phase 6F remains planned.
No application, microphone or speaker was activated during development.

## Supported requests

Start the existing CLI:

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --adaptive
```

Type these at its prompt (without typing `You:`):

```text
Open VS Code.
Launch Visual Studio Code.
Start Firefox.
Open my Downloads folder.
Open my Documents folder.
Open my home folder.
Open my FRIDAY project.
Show running applications.
Resume yesterday's project.
```

Optional `please` and approved exact aliases are supported. Instructional questions
such as “How do I open VS Code?” retain normal conversational routing. Compound
actions, shell syntax and user-supplied executable flags are rejected. Bare `Open Downloads.` and `Open Documents.` now request desktop opening.
Use `list downloads` and `list documents` for filesystem listings. `/q`, `/q hello`, `/speak`, `/voice`, `/bye`,
`exit` and `quit` retain their existing contracts.

## Architecture and authorization

The existing ToolRouter uses DesktopIntentResolver before filesystem routing.
Seven registered tools pass through ToolManager, the existing risk policy and a
DesktopPermissionAdapter. The adapter reuses CLIFileApproval and FolderDecision;
it does not implement another permission database. Desktop results use trusted
tool metadata, remain text-only and do not enter conversational history.

Each viable action displays its exact operation, application/executable identity,
target directory, risk and intended side effect. Type **1** for Allow once or
**3** for Deny. Persistent desktop approval is unsupported: **2** is denied.
Existing persistent read/list grants cannot authorize desktop actions. Opening a
folder grants no FRIDAY permission to read its files. Non-interactive approval
fails closed. A confirmed voice transcript still requires separate typed desktop
approval; a transcript cannot grant permission.

The adapter creates a request-local authorization lease. It opens verified
executable and directory descriptors before approval, rechecks named identities
after approval, and keeps the descriptors through launch. Existing lexical-path,
sensitive-path and no-symlink descriptor utilities protect directories. Only the
exact home-folder operation permits the home root; this grants no reading scope.

## Reviewed application identities

| Identity | Aliases | Reviewed native candidates |
| --- | --- | --- |
| vscode | VS Code, Visual Studio Code, Code | `/usr/share/code/code`, `/usr/lib/code/code` |
| files | Files, Ubuntu Files, file manager, Nautilus | `/usr/bin/nautilus` |
| firefox | Firefox | `/usr/lib/firefox/firefox`, `/usr/lib/firefox/firefox-bin`, `/usr/bin/firefox` |

Availability is discovered by reading metadata and ELF headers, never launching
a probe. Candidates, the installation root and their parent components must be root-owned
and not group/world writable. Symlinks, including installation-root ancestor
symlinks, are refused; native binaries are held open and rechecked after approval. Desktop-entry identifiers are descriptive metadata;
arbitrary `.desktop` Exec lines, PATH lookup, scripts, user installations, Snap,
Flatpak and Terminal are not supported. Ambiguous aliases do not resolve.

In the inspected environment `/snap/bin/code` points to `/usr/bin/snap`; neither
reviewed native Code candidate exists. `/usr`, `/snap` and their installed files
report UID 65534 (`nobody`), failing root ownership; `/snap/code/264` also reports
group-writable mode. Firefox is a script wrapper at `/usr/bin/firefox`.
These observations describe this workspace environment, not every Ubuntu host.
The implementation reports specific unavailable/untrusted reasons without fallback.
Supporting additional packaging needs reviewed identities and separate owner
approval for any installation, rather than relaxing ownership checks.

## Execution boundaries

The executor accepts approved leases, never raw commands. It uses fixed argument
arrays, no shell, closed inherited descriptors, DEVNULL standard streams and a
small environment allowlist. Loader/interpreter variables and arbitrary bus
addresses are not inherited. Only supported local X11/Wayland session endpoints
are forwarded; the runtime directory must be owner-owned and mode 0700.

Each VS Code launch uses a fresh mode-0700 profile below the already Git-ignored
`data/desktop-profiles/`, with mode-0600 settings. Extensions are disabled, automatic
tasks off, workspace trust enabled, existing window/buffer restoration disabled,
and telemetry/updates disabled. The fixed command uses `--new-window`,
`--disable-extensions`, `--skip-add-to-recently-opened` and `--user-data-dir`.
These controls follow the [VS Code CLI](https://code.visualstudio.com/docs/configure/command-line)
and [workspace trust](https://code.visualstudio.com/docs/editing/workspaces/workspace-trust)
interfaces. The application-scoped `task.allowAutomaticTasks` setting is defined
in [VS Code's task configuration source](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/tasks/browser/task.contribution.ts).
Compatibility with the owner's installed version still needs live validation.

Executable and editor-profile handoff uses verified `/proc/self/fd/` paths.
Nautilus folders use stable `/proc/<FRIDAY-pid>/fd/<held-fd>` paths retained
through the session, so forwarding to another process does not reinterpret self.
This blocks pathname replacement in FRIDAY's handoff, but compatibility with GUI
clients that canonicalize paths or forward requests to another process is not
yet verified. There is no automatic fallback to an unpinned path.

The initial child wait is bounded to one second. A zero exit means **launch
request accepted**, not proof that a window or target opened. A still-running
process means **launch outcome unverified**. Nonzero exit means launch failed.
At most four processes are started per CLI session. Finished children are reaped;
approved GUI applications are not terminated when FRIDAY exits. No monitoring
daemon or process enumeration is created. An application remains independently
capable of its normal filesystem/network activity; this adapter is not a GUI
sandbox or a permission system for the application's own actions.

## Folders and projects

Downloads and Documents use the existing semantic resolver and XDG user-directory
configuration. Missing, sensitive, substituted or symlinked targets fail safely.
The project registry is immutable application configuration: initially only
`friday` maps to FRIDAY's actual configured project root. Model text and stored
session rows cannot add projects or supply paths. No project setup script or
terminal command is executed.

## Project metadata and resume

The existing SQLite database gains `desktop_project_sessions`. It stores UUID,
registered project ID/path, application ID, directory device/inode, UTC opening
and last-interaction timestamps, launch status, source and schema version.
Records come only from explicit authorized FRIDAY-managed project launches.
It stores no document contents, editor/terminal history, audio or transcript.
Voice-derived turns suppress this metadata too. Desktop prompts/results never
enter reusable chat history. Profiles can contain editor-created cache/state;
they remain private and excluded from Git, and are not automatically deleted
while an approved application may still use them.

“Yesterday” means the preceding calendar day in the process's local timezone,
with each midnight resolved independently for daylight-saving transitions. Only
accepted launches for currently registered projects with matching stored paths
are eligible; unverified outcomes are excluded. Directory identity is verified
again before approval. Exactly one match proposes reopening through typed
approval. Multiple matches request `Resume yesterday's <project_id> project`.
No match returns an honest no-session result. A project opened today cannot
populate yesterday's history. Resume does not restore unsaved buffers, tasks,
terminals or application state, and never scans the home directory/editor history.

## Running applications and privacy

Inspection requests pass through typed read-only approval, then return an
explicit unsupported-capability result on X11, Wayland or headless sessions.
This foundation has no reviewed privacy-preserving window enumeration backend.
It collects no PID list, command lines, environment, URLs or document titles and
does not fabricate running applications. Additional desktop integration is a
future reviewed extension.

## Owner acceptance — pending

Run the CLI above and try each supported request. Where a trusted application
and session are available, first deny with **3** and verify no launch. Repeat and
allow with **1**. Confirm the actual window/target yourself; terminal acceptance
alone is insufficient. In the current environment expect an unavailable message
for native launches and an unsupported message for inspection. Do not interpret
either as a successfully implemented packaging/window integration.

Test `Open my FRIDAY project` without accepting workspace tasks/trust casually.
After an accepted launch on a preceding local calendar day, test resume and its
separate typed approval. With no eligible history, expect no verified session.
Test malicious compound requests and ensure no permission/launch side effect.
Check existing `/q`, malformed `/q hello`, manual `/speak` and owner-controlled
`/voice` separately. Microphone remains OFF until explicitly activated. Existing
voice hardware validation remains pending.

Headless verification:

```bash
.venv/bin/python -B -m unittest discover -s tests -p test_desktop.py
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
.venv/bin/python -B -m unittest discover -s tests -p test_sync.py
.venv/bin/python -B -m friday.main --check-voice-config
git diff --check
```

## Startup greeting and Recent Work Queue (Q)

Interactive terminal startup uses the system local timezone: morning 05:00–11:59,
afternoon 12:00–16:59, evening 17:00–04:59. It prints “Good morning! Welcome back.”
(or afternoon/evening), then uses SpeechController with trusted local-greeting
metadata. Speech follows the existing enabled state and safety checks. The eSpeak
startup communication timeout is five seconds, followed by bounded process cleanup;
normal response speech retains its existing timeout. Missing eSpeak continues in
text mode. Help, voice configuration checks, workload diagnostics and noninteractive
startup skip the greeting. One StartupGreeting instance has an idempotence guard;
the CLI invokes it once. No audio file, microphone, network request or startup/login
setting is added. `/q` continues to toggle speech for this session; `Show Q` shows
recent work and is a different command.

The existing SQLite database adds `recent_work`, with stable UUID, unique activity
key, activity type, application ID, approved target identity, title, factual
summary, versioned fixed resume descriptor, UTC launch timestamp, safe link/path, structured launch outcome
and ordering counter. Upsert and eviction are one transaction. Repeat launches
retain their UUID and move to first place; a fourth distinct activity evicts the
oldest. At most three rows are retained. Existing project-session metadata remains
available for yesterday's local-calendar-day lookup, independently of Q eviction.

Both `launch_accepted` (zero exit from the initial bounded wait) and
`launch_outcome_unverified` (OS process start observed, still running at that wait)
populate Q after authorization. Neither status proves a window appeared or work
was completed. The menu displays `Status: Window not verified.` and factual
summaries such as `FRIDAY started Ubuntu Files.`. Application-only resume displays
`Open Ubuntu Files.`. Summaries describe FRIDAY-managed process starts only. Denied, unsupported,
failed, untrusted and voice-derived requests never populate Q. No window contents,
keystrokes, clipboard, browser history or editor state is inspected or monitored.

After the greeting, startup displays `YOUR RECENT WORK`, numbered entries with
`Summary:` and `Resume:` fields, or `No recent work saved yet.`. It never opens
anything automatically. `Show my recent work.`, `Show Q.` and `What was I working
on?` display the same queue. `Resume previous projects.` filters the three Q slots
for projects; it does not invent or import older history. `Resume my last work.`
offers the most recent currently viable saved activity, explicitly noting skipped
invalid/unavailable activities in the approval effect. If none is viable it explains
the failure. `Resume yesterday's project.` retains the existing managed-history
lookup using local-calendar midnights (including DST) and fresh exact approval.

The displayed menu snapshots stable UUIDs. Only exact inputs `1`, `2`, `3` at the
next menu prompt select a slot. Invalid numbers report an error and close that
menu; any intervening command, including slash/voice commands, closes it. Outside
the menu a number has no desktop meaning. Number selection reloads that UUID,
validates the descriptor against fixed operations, checks the current project or
XDG alias mapping and stored directory device/inode, validates the executable,
then requests typed Allow once. Explicit selected IDs never fall back to another
activity. Denial launches nothing. Reordering Q cannot change the selected target.
Missing, substituted, sensitive or untrusted targets produce a clear error.

All loaded rows are untrusted. Titles/summaries are checked against deterministic
reconstruction; malicious/inconsistent rows are refused. Display fields escape
terminal controls and are single-line bounded. Saved descriptors contain only
fixed operation/alias fields and approved target identity, never command strings,
scripts, executable paths, credentials or model output. App executables are always
resolved from the current fixed registry. Existing filesystem read grants and
previous desktop approvals have no authority here. Desktop responses remain
outside reusable conversation history and automatic speech.

`Open github.com in Firefox.` approves the exact reviewed link
`https://github.com/`. This intentionally small code-reviewed URL catalog refuses
all other URLs, including HTTP, javascript, data, file, userinfo, queries, fragments
and unreviewed private paths. URLs enter a fixed argv array with no shell; they
never become a command or downloaded executable. More links or installation
layouts need separate review; no arbitrary URL field is exposed through model
translation. Native Firefox without a URL resumes only the approved application,
not a browser tab guessed from history.

Owner action for Snap-only Code: provision the vendor's reviewed APT/deb native
installation on the actual host, with root-owned nonwritable native components,
then validate the GUI manually. Do not chmod/chown this workspace image to make
its trust checks pass. FRIDAY does not install anything. Microsoft's
[Linux installation documentation](https://code.visualstudio.com/docs/setup/linux)
describes the official deb and Snap packages. Snap dispatch is deliberately
unsupported because pinning `/usr/bin/snap` does not pin the selected app revision,
and direct Snap ELF invocation bypasses packaging setup/confinement. Snap's
[classic confinement documentation](https://snapcraft.io/docs/explanation/security/classic-confinement/)
explains why classic is not a substitute for this trust boundary. No system/user
`.desktop` Exec line is executed; desktop IDs remain fixed descriptive registry
metadata. PATH names and user desktop overrides cannot establish trust.

Full implementation report and exact owner commands:
[Phase 7A enhancement](PHASE_7A_ENHANCEMENT.md).


### Q persistence policy correction

The previous zero-exit-only gate excluded normal long-running GUI processes.
The [persistence fix report](PHASE_7A_Q_PERSISTENCE.md) traces that cause and the
regression checks. The existing SQLite table gains a constrained `launch_status`
column; an idempotent migration preserves existing entries as `launch_accepted`.
New version-2 descriptors store factual process-start summaries. Version-1
entries remain validated and resumable, and their displayed summaries are
reconstructed without asserting window visibility. No permissions, executable
trust checks or yesterday-project history eligibility were broadened.


## Desktop repair: immediate repeats and explicit retry

**Current command compatibility:** open files/downloads/documents/project folders
now use the separate [FRIDAY Browser](PHASE_7A_MANAGED_BROWSER.md), with independent
launch/navigation/read approvals. The following historical Nautilus behavior
applies to explicit `open ubuntu files` / `open downloads in ubuntu files`
commands and legacy Nautilus Q descriptors. Managed browser back/forward and Q
resume reuse its own authenticated renderer; no Nautilus API assumption changed.

**Historical cooldown behavior below is superseded for Files by the
[same-window navigation investigation](PHASE_7A_NAVIGATION.md).** Current Files
requests resolve Home/Downloads/Documents/registered project folders through a
session-local `FileManagerNavigationController`. Nautilus' reviewed interfaces
cannot navigate a specified window, so an accepted launch receipt blocks every
further implicit Files launch until session exit. Explicit retries retain exact
target validation, fresh typed approval and the four-process budget. The receipt
is not proof of an existing window. No navigation, window identity or visibility
is invented; failed/denied/suppressed actions never update Q. Prompt operation is
`navigate_folder`, risk `desktop_navigation`; the executable and target are still
pinned/rechecked by the existing adapter. Legacy application-only Files Q entries
offer Home with fresh approval; their old metadata stays valid. New Files actions
store original approved Home/folder paths, never proc paths or window handles.
No new SQLite schema or persistent permissions were introduced.

The [desktop repair report](PHASE_7A_DESKTOP_REPAIR.md) documents actual package
and Wayland diagnostics, the Nautilus forwarding repair, Snap rejection findings,
current tests and exact pending owner GUI acceptance steps. Ubuntu Files uses a
20-second bounded session receipt guard; Files, Downloads and Documents are
separate operation/target identities. Suppressed duplicates never prompt, launch,
consume budget or update Q. `retry open files`, `retry open downloads` and
`retry resume my last work` request a fresh launch through the existing exact
approval gateway. The four-process limit and all trust checks remain. This applies
to numbered Q resume too; latest-work suppression never chooses another activity.
Accepted retries still deduplicate/reorder Q. No focused/visible window is claimed.
Parent-held directory paths expire when FRIDAY closes; Q stores the original
approved target and revalidates it, never a transient proc path. No real GUI
acceptance or Snap launch was performed during development.
