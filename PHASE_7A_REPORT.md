# Phase 7A implementation report — unreleased foundation

## A. Baseline

Repository: `~/Projects/FRIDAY`; branch: `feature/voice-foundation`.
HEAD before and after work: `e35fcef Merge pull request #2 from
Vigneshwar4053/feature/adaptive-workload`. The starting worktree already contained
modified CLI/core/tool/test files and untracked Phase 6E modules, tests, reports,
documentation and `PHASE_6D_BENCHMARK.json`. These were preserved. No applicable
AGENTS.md was found. Existing architecture and typed filesystem gateway were
inspected before the implementation plan was reported and edits began.

The baseline suite passed **947 tests in 7.541 seconds**. Existing secure
filesystem routing, adaptive L0–L3, voice configuration, capture lifecycle,
automatic speech provenance and private voice turns were retained.

This is an **unreleased Phase 7A foundation**, not a v0.7.0 release. v0.5.0 Phase
6E remains IN PROGRESS pending owner hardware validation. v0.6.0 Phase 6F remains
the planned intervening milestone; no release strategy has been changed.

## B–F. Architecture, intents, identities and permissions

The existing ToolRouter now calls a deterministic DesktopIntentResolver. Five
structured tools execute through ToolManager and its centralized risk policy:
`launch_application`, `open_folder`, `open_project`,
`inspect_running_applications`, `resume_project`. DesktopPermissionAdapter
reuses the same CLIFileApproval and FolderDecision interface as filesystem
approval. A ContextVar carries only the current exact authorization lease; it is
not a privacy or permission setting shared between turns.

Supported phrases include **Open VS Code**, **Launch Visual Studio Code**,
**Start Firefox**, **Open my Downloads/Documents/home folder**, **Open my FRIDAY
project**, **Show running applications**, and **Resume yesterday's project**.
Existing browse phrases such as `open downloads` retain their old meaning.
Instructional questions remain conversation. Model-generated read-only tool
proposals cannot select desktop tools: the translation allowlist is unchanged.
Desktop responses follow deterministic L1 routing without invoking Ollama.

The reviewed registry contains VS Code, Nautilus/Files and Firefox, with exact
aliases, descriptive desktop IDs, fixed native executable candidates and execute
risk. Discovery reads metadata and ELF headers only. Root ownership and absence
of group/world writes are required throughout candidate installation paths.
Scripts, untrusted desktop entries, arbitrary PATH executable discovery, Snap,
Flatpak and terminal launching are unsupported. Aliases are not fuzzy matched.
**No candidate met this trust policy in the current development environment**;
some installed paths appear with a non-root owner here and others are wrappers
or Snap links. This is reported as unavailable, not silently bypassed.

Side effects require typed **1 / Allow once** for the exact operation, executable
identity and actual target. **3 / Deny** rejects the operation. Desktop persistent
approval is intentionally unavailable; **2**, strings claiming approval, absent
approval and non-TTY approval all deny. READ_ONLY inspection also gets typed
approval. Existing read/list grants never authorize launch/open/resume; opening
a folder does not grant FRIDAY read access. No permission engine rules or stored
filesystem grant scopes were weakened.

## G–H. Project sessions and resume

Only the configured FRIDAY project root is initially registered, under `friday`.
No arbitrary path/model output/editor history/home scan can register a project.
The existing SQLite infrastructure gains an additive
`desktop_project_sessions` table and timestamp index, with validated project and
application identity, path, device/inode, UTC timestamps, launch status, UUID,
schema version and `friday_managed` source. Parameterized SQL is used.

Only explicit authorized project launch attempts save metadata. Failed/denied
requests save none. Accepted and outcome-unverified attempts are distinguished;
only accepted requests qualify for resume. Voice-derived requests save neither
this metadata nor conversational messages. All desktop prompts/results remain
outside reusable chat history and automatic speech.

Yesterday is the previous **local calendar day**; each midnight is resolved for
its own timezone/DST offset. Tests cover Asia/Kolkata and a 23-hour DST day.
Stored rows are compared with the current trusted registry; changed directory
identities are rejected. One match proposes reopening via typed approval;
multiple matches request an explicit registered project ID; none returns no
verified session. Lookup is bounded to 128 rows per day and fails safely above
that limit. Resume reopens a project only: no editor buffers, terminal state,
automatic tasks or setup scripts are restored.

## I. Security and executor safeguards

Executable and directory descriptors are verified before approval, named targets
are rechecked afterward, and fixed argument arrays use pinned descriptors through
launch. Existing sensitive-path/no-symlink utilities are reused. The exact home
folder operation is a narrowly scoped desktop exception, with no read grant.
Request schemas reject extra arguments. Shell metacharacters, traversal, flags,
compound actions and unregistered desktop identities cannot produce execution.

Popen never uses a shell. Inherited descriptors are closed except explicitly
verified handoff descriptors; stdio is DEVNULL. Environment forwarding is limited
to fixed safe defaults and verified local graphical session endpoints. Arbitrary
DBus addresses, loader/interpreter variables, tokens and raw errors are omitted.
No process environment, command line, URL or document title is enumerated.

Fresh owner-private VS Code profiles disable extensions and automatic tasks,
enable workspace trust, disable previous-window/buffer restoration, updates and
telemetry. Settings/profile writes use descriptor-relative no-follow operations;
files are 0600, profile directories 0700, under ignored `data/desktop-profiles`.
Reviewed interface references and limitations are in
[the setup document](docs/PHASE_7A_DESKTOP.md).

The child wait is bounded to one second and there are at most four launches per
CLI session. A zero exit is **launch accepted, window/target unverified**;
timeout with a live child is **launch outcome unverified**; nonzero is failure.
Finished children are reaped; owner-approved applications are deliberately left
running on CLI shutdown. No monitoring service is installed. Sensitive outputs,
permission prompts and desktop session details remain text-only under existing
trusted response metadata. Voice still requires explicit microphone activation,
transcript confirmation and a separate typed tool approval.

## C. Exact files in this increment

Created:

- `friday/desktop/__init__.py`
- `friday/desktop/registry.py`
- `friday/desktop/routing.py`
- `friday/desktop/runtime.py`
- `friday/desktop/sessions.py`
- `tests/test_desktop.py`
- `docs/PHASE_7A_DESKTOP.md`
- `PHASE_7A_REPORT.md`

Extended existing files, preserving their prior uncommitted work:

- `friday/main.py`: shared approval wiring, protected profile path, shutdown.
- `friday/core/assistant.py`: private deterministic desktop response branch.
- `friday/tools/manager.py`: existing-policy desktop authorization adapter.
- `friday/tools/router.py`: deterministic desktop intent routing.
- `friday/tools/presenter.py`: accurate, fixed desktop result presentation.
- `friday/memory/database.py`: additive session table/index.
- `friday/memory/manager.py`: validated metadata insertion and bounded lookup.
- `tests/test_tool_routing.py`: registry isolation assertion accounts for five tools.
- `README.md`: unreleased foundation link and scope.

Existing Phase 6E documents, voice modules, voice runtime, configuration and model
were not edited by this increment. Other dirty files shown by Git predate this
task and are not included as new desktop changes.

## J–K. Automated validation

All desktop launches are mocked, with synthetic executable identities and
temporary directories. No live application, microphone or speaker is accessed.
The **77 new tests** cover registry trust/aliases/discovery, typed approvals and
scope boundaries, schema validation, shell injection, pinned target substitution,
private editor configuration, launch/error outcomes and limits, folder/project
resolution, private provenance, voice cancellation/confirmation, existing CLI
commands, SQLite metadata/resume, X11/Wayland unsupported behavior and timezone
boundaries. Existing invalid permission-policy tests retain their fail-closed
assertions; no tests were weakened to accept string labels as permission enums.

Final validation on the completed code:

| Command | Result |
| --- | --- |
| `.venv/bin/python -B -m unittest discover -s tests` | **1,024 passed**, 8.499 s |
| `.venv/bin/python -B -m unittest discover -s tests -p test_desktop.py` | **77 passed**, 0.571 s |
| `.venv/bin/python -B -m unittest discover -s tests -p 'test_voice*.py'` | **177 passed**, 2.753 s |
| `.venv/bin/python -B -m unittest discover -s tests -p test_sync.py` | **31 passed**, 0.208 s; included in full suite |
| `make -C native/sync` | Exit 0; build already current |
| `git diff --check` | Exit 0 |
| `.venv/bin/python -B -m friday.main --check-voice-config` | Exit 0, `verified_files`, microphone OFF |

Verified unchanged runtime hashes:

- Whisper binary: `c488e598e073312a7addb7b5964ca1ae060656e1637df511d4060a49bdb2472a`.
- tiny.en: `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
- Preserved benchmark: `b7c4b5f112f0d65a43bebd7a5d051ed99fc46e8b6bee8b8fe2da92095c1ebdc5`.

## L. Known limitations and acceptance status

The foundation is ready for owner review/headless acceptance. **Actual desktop
launch compatibility is pending**, and native application availability currently
blocks live launch testing under this strict registry. No application has been
proved to open successfully here. Adding packaging support requires review;
no package installation or trust-policy broadening was attempted.

Running-app inspection is explicitly unsupported on both Wayland and X11 in
this initial version, after typed approval. It identifies the session capability
without listing applications. No additional integration was installed.

Linux descriptor handoff, external GUI client forwarding and VS Code's actual
installed-version settings behavior need owner validation. A trusted GUI remains
an independent application, not a sandbox controlled by FRIDAY's read gateway.
Profiles may accumulate editor-created state; safe cleanup/retention is a future
review, not destructive cleanup in this task. No graphical outcome API is used;
accepted process exit does not prove target/window success. Accepted-request
metadata represents exactly that, not independently observed editor activity.

There is no persistent desktop grant, dynamic project registration UI, full
workspace restoration, terminal launch, desktop keyboard/mouse automation,
screenshot/clipboard/browser automation or continuous observation.

## M. Owner acceptance instructions

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive
```

At the prompt type:

```text
Open VS Code.
Open my Downloads folder.
Open my FRIDAY project.
Show running applications.
Resume yesterday's project.
```

For available trusted installations, expect exact target/risk/side-effect typed
approval. First deny with **3**; repeat and allow with **1** only if the target is
correct. Confirm actual window/target yourself. With current unavailable native
identities expect no launch and a useful unavailable message. Inspection returns
unsupported, never a fabricated list. Resume requires an accepted managed launch
from yesterday; otherwise expect no verified session. Multiple registered matches
require an explicit project choice, followed by separate approval.

Also test `hello`, `/q`, `hello`, `/q`, `/q hello`, and `/speak Hello, I am FRIDAY.`
using the existing owner audio procedure. `/q hello` prints usage without toggle
or Ollama. `/voice` remains owner-controlled with typed transcript confirmation;
desktop speech requests must then pass separate typed approval. Hardware results
must be supplied by the owner before microphone/playback success is claimed.

## N. Git and environment safety

The branch and HEAD are unchanged. All prior dirty tracked files/untracked files
remain, with the additional desktop package, tests, documentation and report;
implementation files listed above remain uncommitted. `git diff --check` passes.
No commit, push, merge, tag, reset, rebase, stash, clean or branch switch occurred.
No package/model download, system setting change, microphone gain adjustment,
cloud service, live desktop action or background/startup service occurred.

## O. Recommended Phase 7B work

After owner review, add separately reviewed packaging identities (particularly
Ubuntu Snap), verify executable/client descriptor compatibility and actual target
opening, and consider a privacy-preserving desktop-session API. Add explicit
owner project registration and a bounded editor-profile retention policy. Keep
typed approval and provenance restrictions intact. Release strategy remains an
owner decision; finish v0.5.0 hardware acceptance and preserve the v0.6.0 Phase 6F
milestone before any approved v0.7.0 release.

## Phase 7A enhancement follow-up

See [the enhancement implementation report](docs/PHASE_7A_ENHANCEMENT.md) for
installation failure findings, startup greeting, SQLite Q, safe resume, current
headless verification and exact owner acceptance commands. This follow-up does
not advance a release or claim live GUI validation.
