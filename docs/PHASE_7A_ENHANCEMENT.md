# Phase 7A enhancement — implementation and owner acceptance

Current immediate-repeat behavior: the [desktop repair](PHASE_7A_DESKTOP_REPAIR.md)
adds a short duplicate guard. Use explicit `retry open files`/`retry open downloads`
when testing repeated accepted launches; suppression does not refresh Q or consume
budget. The original investigation below remains historical context.

No release version was changed. Existing uncommitted work was preserved. No Git
commit/push/merge/rebase/reset/stash, package installation, download, GUI launch,
microphone capture, background monitoring or Ubuntu login/startup modification
was performed.

## 1. VS Code failure investigation

The existing router correctly recognized `Open VS Code.` and reached the desktop
adapter. Rejection occurred in ApplicationRegistry's installation preflight,
before typed approval and before Popen. The initial registry only reviewed
`/usr/share/code/code` and `/usr/lib/code/code`; neither exists here. The installed
`/snap/bin/code` is a symlink to the generic `/usr/bin/snap` dispatcher, with
`/snap/code/current` pointing to revision `264`. That dispatcher is not the Code
executable. Simply pinning snap would not pin its selected application revision
or preserve the existing descriptor target/profile handoff. Directly running the
Snap ELF would bypass required packaging environment/confinement setup.

Read-only metadata inspection also found UID 65534 (`nobody`) on `/usr` and
`/snap`, and group-write mode on `/snap/code/264`. These fail the root-owned,
nonwritable native installation boundary. `/usr/bin/firefox` is a shell wrapper,
not an eligible ELF. This workspace's metadata is not evidence that the owner's
actual host has identical ownership.

The boundary was retained. Errors now explain missing native paths, wrappers,
untrusted ownership, writable components or unsupported Snap dispatch and state
the owner action. Provision a reviewed administrator-owned native installation
on the real host; do not change this environment's ownership/modes to bypass
checks. Nothing was installed or repaired in system directories.

## 2. Files changed by this enhancement

Production:

- `friday/desktop/registry.py`: stricter no-symlink checks and explicit diagnostics.
- `friday/desktop/runtime.py`: queue integration, reviewed URL launch, safe resume preflight.
- `friday/desktop/routing.py`: deterministic Q/resume and bare approved-folder grammar.
- `friday/desktop/recent.py`: queue descriptors, validation and stable numbered menu.
- `friday/memory/database.py`, `friday/memory/manager.py`: existing SQLite schema/API extension.
- `friday/main.py`: interactive greeting/menu and slash-command menu isolation.
- `friday/voice/startup.py`, `friday/voice/tts.py`: local greeting and bounded startup speech.
- `friday/tools/router.py`: invalid menu selection presentation.

Tests:

- `tests/test_recent_work.py`: 35 new headless checks.
- `tests/test_desktop.py`: greeting-aware integration expectations and explicit filesystem listing fixture.
- `tests/test_voice.py`, `tests/test_voice_automatic.py`, `tests/test_voice_foundation.py`: filesystem listing fixtures and isolated preexisting turn-speech tests.
- `tests/test_tool_routing.py`: composed registry now contains seven desktop tools.
- `tests/test_file_references.py`, `tests/test_navigation.py`, `tests/test_semantic_locations.py`, `tests/test_workload.py`, `tests/phase6c_demo.py`, `tests/phase6d_benchmark.py`: use explicit listing commands for browsing.

Documentation: `README.md`, `docs/PHASE_7A_DESKTOP.md`, this report and a link from
`PHASE_7A_REPORT.md`. Other working-tree changes predate this task.

## 3. Supported installation layouts

| Application | Reviewed native paths |
| --- | --- |
| VS Code | `/usr/share/code/code`, `/usr/lib/code/code` (reviewed native deb/system layouts) |
| Ubuntu Files | `/usr/bin/nautilus` |
| Firefox | `/usr/lib/firefox/firefox`, `/usr/lib/firefox/firefox-bin`, `/usr/bin/firefox` only when native ELF |

Support requires the fixed path and every reviewed component to have trusted
ownership/mode, no symlinks, an executable regular ELF, and execution-time
identity revalidation. It does not trust every package labeled “VS Code” or a
PATH name `code`. Scripts, arbitrary tarball/user installs, Snap, Flatpak and
unreviewed paths are refused. Desktop IDs are descriptive fixed identities;
no user/system desktop-entry Exec line is parsed or executed.

Official packaging references:
[Microsoft Linux setup](https://code.visualstudio.com/docs/setup/linux),
[Snap classic confinement](https://snapcraft.io/docs/explanation/security/classic-confinement/).
A normal native installation still needs manual verification of application
compatibility with the descriptor-based launch method.

## 4. Greeting

The system's local timezone determines morning (05:00–11:59), afternoon
(12:00–16:59) or evening (17:00–04:59). Interactive startup prints the greeting,
then passes trusted local-greeting metadata through SpeechController. Speech
disabled/unavailable means text only. A once guard prevents duplication.
The production eSpeak communication timeout is five seconds for this greeting,
with bounded existing cleanup; normal speech keeps its prior timeout. No audio
is saved, and no microphone/network service is used. Help, configuration checks,
diagnostics and noninteractive startup skip the greeting.

## 5. Q database and outcomes

`recent_work` lives in the existing SQLite database. Its fields are stable UUID,
unique activity hash, activity type, application ID, approved target identity,
deterministic title/summary, versioned safe resume descriptor, UTC launch timestamp,
safe path/link, launch status and launch order. Transactional upsert retains the UUID and moves
repeats to first place. Transactional eviction keeps only three rows.

Q records authorized process starts with either `launch_accepted` (zero exit)
or `launch_outcome_unverified` (still running after the bounded initial wait).
Failed, denied, unsupported and voice-derived requests are excluded. Neither
accepted status proves a visible window, opened document or completed work.
Summaries describe process starts, and `Status: Window not verified.` is displayed.
This corrects the original zero-exit-only gate; see the
[Q persistence fix report](PHASE_7A_Q_PERSISTENCE.md) for migration and regression checks.
Existing managed project sessions continue to provide yesterday's history,
including projects evicted from Q; they do not provide monitoring evidence.

## 6. Numbered and natural-language resume

Startup and Show Q display up to three entries with Summary/Resume fields.
The menu snapshots stable UUIDs, so queue reorder cannot substitute another slot.
An exact `1`, `2` or `3` selects only in the next active menu context. Invalid
selection or any intervening command closes that menu. Outside it, numbers do
not route to desktop resume. Selection reloads the UUID, validates the fixed
operation descriptor and current alias/path/device/inode, rechecks the executable,
and asks for fresh typed exact-operation Allow once. Explicit IDs never fall
back to another target.

Show my recent work, Show Q and What was I working on display Q. Resume previous
projects filters the three slots. Resume my last work offers the most recent
currently viable saved activity and explains skipped invalid/unavailable entries
in its approval. Resume yesterday's project uses the existing preceding local
calendar day lookup. Missing matches are explained honestly.

## 7. Security and privacy

The fixed registry, ToolManager risk policy, typed owner gateway and request-local
exact authorization lease remain in effect. Read grants cannot authorize launches.
Binaries/directories are pinned by descriptors and named identities rechecked after
approval. Fixed argv arrays never use a shell, model flags or stored executable
paths. VS Code still uses a private fresh profile, disabled extensions, automatic
tasks off and workspace trust enabled. Sensitive target checks remain in force.

All loaded queue metadata is untrusted and checked against deterministic
reconstruction. Invalid metadata is refused; terminal controls are escaped.
Only the reviewed `https://github.com/` URL is accepted. Credentials, private or
unreviewed paths, query strings, fragments and all unsafe schemes are rejected.
No activity/window/keystroke/clipboard/editor/browser-history monitoring is added.
Desktop results and targets stay out of reusable chat history and automatic speech.
Voice-derived requests retain typed approval requirements and suppress persistence.

## 8. Verification

The totals below describe the original enhancement run. The subsequent
[persistence fix report](PHASE_7A_Q_PERSISTENCE.md) records current regression results.


Final headless suite: **1,061 tests passed**, including 35 new startup/Q tests.
These cover time boundaries/local timezone, disabled/missing speech, once-only
speech, help/diagnostics suppression, five-second startup timeout, queue sizes,
eviction/reordering/stable IDs/persistence, invalid numbers and context isolation,
denied/failed/voice exclusions, fresh approvals, missing/modified targets,
untrusted binaries, unsafe/sensitive URLs, escape injection, descriptor poisoning,
voice persistence exclusion, fixed argv/no shell and interactive menu integration.
Every GUI/audio execution in tests uses mocks; no real desktop application or
speaker was launched. `make -C native/sync` passed (already up to date), and
`git diff --check` passed.

## 9. Remaining limitations

This inspected Snap-only/ownership-remapped environment cannot launch the reviewed
native applications. Live GUI behavior is unvalidated. GUI clients that resolve
or forward `/proc/self/fd` targets may not support the pinned handoff; no unsafe
pathname fallback exists. The existing four-spawn-per-session limit remains.
A long-running GUI process enters Q as a process start with window unverified;
owner observation is not fabricated as runtime evidence. No subsequent process
or window monitoring upgrades or changes that recorded observation.
Only FRIDAY is initially registered as a project, and github.com is the sole
reviewed link. Q is limited to three activities and does not restore tabs, unsaved
buffers, editor sessions or work performed outside FRIDAY. Application capability
is separate from FRIDAY permission: this launcher is not a GUI sandbox. Running
application inspection remains unsupported.

## 10. Exact manual acceptance commands

First run these read-only/headless commands from the repository:

```bash
.venv/bin/python -B -m unittest discover -s tests
make -C native/sync
git diff --check
.venv/bin/python -B -m friday.main --help
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive --diagnostics
```

The voice check may exit nonzero if no owner configuration exists; it must not
record/play audio. In diagnostics, verify no startup greeting audio, then type
`quit`. To verify noninteractive greeting suppression without any launch:

```bash
.venv/bin/python -B -m friday.main --adaptive < /dev/null
```

For owner-approved GUI acceptance on a host with reviewed native applications,
start an ordinary local Ubuntu terminal session:

```bash
.venv/bin/python -B -m friday.main --adaptive
```

Verify one local greeting, microphone OFF, then an honest saved-work menu. If
speech is unavailable the greeting must still print. Type these exact requests
at the FRIDAY prompt. At every viable launch approval first type **3** to deny;
repeat that request and type **1** to allow. Observe the GUI yourself.

```text
Open VS Code.
Open Firefox.
Open Downloads.
Open Documents.
Open my FRIDAY project.
Open github.com in Firefox.
Show my recent work.
Show Q.
What was I working on?
Resume my last work.
Resume previous projects.
```

The existing four-process limit means restart FRIDAY to test more than four
successful launch attempts. Check that Q survives restart, only contains accepted
requests, evicts the fourth distinct activity and moves a repeat to first place.
While Show Q's menu is active, type `1`, then **3** at the separate permission
prompt: no resume should occur. Show Q again, type `1`, then **1** to approve.
Repeat for valid slots `2` and `3`. Show Q then type `4`: expect an invalid-selection
message. Show Q then `/q`, then `1`: the number must not resume anything. `/q`
changes speech only; it does not open Q. Type `Show Q.` again to reactivate choices.

After an accepted FRIDAY-managed project launch on the preceding actual local
calendar day, run:

```text
Resume yesterday's project.
```

Expect fresh typed approval; without eligible history expect an honest no-match
message. Do not alter timestamps to fabricate work. To test speech disabled, type
`/q` until Speech Output is disabled, then send an ordinary greeting: text should
remain available without speech. Missing eSpeak, timezone boundaries, target
substitution and malicious database metadata are covered by safe headless fixtures;
do not tamper with system installations or valuable project directories for them.

These requests must never launch or record an activity:

```text
Open VS Code --disable-sandbox.
Open Firefox && echo forbidden.
Open https://github.com/?token=example in Firefox.
Open javascript:alert(1) in Firefox.
```

On the inspected environment, unavailable/untrusted native-installation errors
are the expected safe result. They do not count as GUI acceptance. Finish with
`quit`.
