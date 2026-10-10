# FRIDAY full feature audit

Audit date: 2026-10-10. Workspace: `~/Projects/FRIDAY`.

## Verdict and evidence standard

FRIDAY starts, responds through local Ollama, executes deterministic computation,
uses native POSIX mutex synchronization and closes SQLite sessions cleanly.
**The requested overall desktop acceptance is partial.** The owner authorized a
separate app-only Snap policy for Firefox and VS Code, including their writable
startup-file risk. Both now receive a real launch attempt after one approval.
Six authorized requests were exercised through the actual interactive FRIDAY CLI.
Application/window visibility remains unverified without owner confirmation.
Nautilus's pinned folder URI also has a confirmed lifetime limitation after the
FRIDAY process exits; canonical-path substitution would require the separate
security decision requested from the owner. No user windows were closed.

Statuses distinguish functionality from evidence. WORKING below means the
specific relevant behavior was exercised against its real implementation/resource.
It does not mean every edge case passed a desktop test. PARTIALLY WORKING means
some parts were verified while important dependent behavior remains unverified.
NOT TESTED means required live evidence is absent. BROKEN means an observed
behavior fails the requested requirement. NOT IMPLEMENTED means the source has no
production implementation; EXPERIMENTAL denotes deliberately limited development
features, regardless of successful synthetic tests. Automated launch mocks never
establish that a visible window appeared.

## Actual history

Read `git tag --list`, full chronological `git log`, and each tag's file tree.
All recorded commits are dated October 7–8, 2026.

| Actual tag / phase | Evidence | Implemented scope |
|---|---|---|
| v0.1.0 | `f9d233c` | CLI, assistant, configuration, local Ollama provider, initial core/provider/CLI tests |
| v0.2.0 | `5417485`; memory commit `c3ea202` | SQLite sessions/messages/structured memories and restoration |
| v0.3.0 | `632d4db`; `b20c531`, `d2106d7` | Model registry/job/queue/runtime manager; native synchronization with Python fallback |
| v0.4.0 | HEAD `e35fcef`; merged adaptive commit `831a954` | Safe tools and routing, Phases 6A/6B/6C, adaptive Phase 6D |
| v0.5.0 experimental / Phase 6E | No v0.5.0 tag or release commit; dirty/untracked working tree | Voice, offline TTS, voice configuration/capture/confirmation, response speech privacy |
| Phase 7A | No release tag or release commit; dirty/untracked working tree | Native desktop registry/runtime, project sessions, startup greeting, Q, experimental managed browser and repairs |
| Later roadmap releases | README roadmap only | Wake word, broader desktop automation/integrations and general installed-app discovery are plans, not releases |

The active branch is `feature/voice-foundation`, at the same commit as v0.4.0,
main and origin/main. This audit performed no fetch, checkout, commit, push,
merge, rebase, reset or stash. Existing owner changes were present before work.
There is no standalone changelog file or pyproject/package manifest in the
inspected tree. README phase sections and report test counts are historical
snapshots; they are not authoritative current release identifiers.

## Feature inventory

| FEATURE | VERSION | STATUS | TEST METHOD | NOTES |
|---|---|---|---|---|
| CLI startup/configuration/clean exit | v0.1, extended phases | WORKING | Actual CLI with temporary SQLite; `--help` | Adaptive banner, native sync, speech toggle, greeting response and closed session observed |
| Local Ollama connection/model presence | v0.1 | WORKING | Real local `/api/tags`, provider inference | `qwen3:4b` installed; no configuration changes or downloads |
| Ordinary AI conversation | v0.1 / L2 current | WORKING | Actual FridayAssistant → ModelManager → Ollama | Public tuple question returned a complete nonempty answer |
| Identity/system prompt | v0.1 | WORKING | Actual local adaptive greeting; source/test inspection | Configured identity, not inferred personal knowledge |
| SQLite sessions/messages | v0.2 | WORKING | Actual temporary-memory CLI and live adaptive driver; SQLite tests | Session closure, public message retention verified; owner conversation bodies not read |
| Structured memories | v0.2 | PARTIALLY WORKING | Real SQLite tests; source | API exists; automatic fact extraction is absent |
| Model registry, FIFO jobs and serialization | v0.3 | WORKING | Actual ModelManager inference + runtime/queue tests | One model request per tested L2/L3 operation; no parallel scheduler daemon |
| Native C synchronization | v0.3 | WORKING | Actual library backend + mutex tests/build | Real backend reported Native C (POSIX mutex), without fallback |
| Python synchronization fallback | v0.3 | NOT TESTED | Headless fallback tests only in this audit | Available at initialization failure; no live native failure was induced |
| Typed tool schemas/registry/risk gateway | v0.4 phases 1–5 | WORKING | Actual computation gateway + tool/routing tests | Production runtime registers 21 tools; no generic model-command execution |
| Bounded numerical operations | v0.4 phase 4 | WORKING | Actual CLI `sum of 2, 3` → `sum: 5.0` | Infix `calculate 2 + 3` is unsupported and was correctly refused |
| System/CPU/RAM/disk/process tools | v0.4 phase 3 | PARTIALLY WORKING | Tool tests use real system APIs and fixtures; source | Narrow `/proc`/OS interfaces; desktop window visibility inspection is unavailable |
| Project and approved-root read/list/info | v0.4 phase 2 / 6A | PARTIALLY WORKING | Real filesystem fixtures + permission/security tests | Bounded reads/listing, sensitive paths and symlink restrictions; no live personal-folder listing performed |
| File write implementation | v0.4 phase 2 | PARTIALLY WORKING | Write tests; source | Tool exists but normal policy requires approval; no chat write approval implementation, so normal chat cannot write |
| Filesystem owner approval/revoke/grants | Phase 6B | PARTIALLY WORKING | CLI/grant/TOCTOU tests; actual noninteractive deny path | Persistent filesystem read grants exist; desktop grants remain one-use and separate |
| Temporary file explanation/privacy filtering | Phase 6B/6C | PARTIALLY WORKING | File reference/privacy/context tests | File bodies stay temporary; no private live file explanation tested |
| Hybrid intent translation | Phase 6C | NOT TESTED | Strict proposal/parser tests | Model proposals only for reviewed read/list grammar; live hybrid translation not exercised |
| Terminal listing history and numbered file references | Phase 6C | PARTIALLY WORKING | Navigation/reference tests | Distinct from Q; managed-browser history can take precedence for go back/forward |
| Adaptive L0 | Phase 6D | WORKING | Actual `hello` | 0 model calls; about 0.0001 seconds in isolated run |
| Adaptive L1 | Phase 6D | WORKING | Actual CLI computation | 0 model calls; deterministic tool result verified |
| Adaptive L2 | Phase 6D | WORKING | Actual public-topic inference | 1 model call, 46.302 seconds in this run |
| Adaptive L3 | Phase 6D | WORKING | Actual explicit deep public-topic inference | 1 model call, 68.080 seconds in this run; CPU responsiveness remains limited |
| Bounded profiles/context/final-answer checks | Phase 6D | WORKING | Actual L2/L3 + profile/reliability tests | Thinking field not printed; timeout/token truncation fail closed; this is not proof of answer correctness |
| Provider error handling / incomplete-answer rejection | v0.1 / Phase 6D | WORKING | Actual CLI rejected a token-limit response and continued to clean exit | No incomplete answer was labeled successful; model quality remains request-dependent |
| Redacted workload metrics | Phase 6D | WORKING | Actual driver emitted public scalar metrics | No private prompts or answers recorded in audit results |
| Saved voice configuration/model pin | Phase 6E | WORKING | Actual `--check-voice-config` | Trusted configured Whisper binary and tiny.en checksum verified |
| Offline eSpeak synthesis | Phase 6E | WORKING | Actual synthesis to temporary public-phrase WAV | No playback or personal audio; temporary synthetic files removed |
| Audible `/speak`, automatic speech and `/q` | Phase 6E | PARTIALLY WORKING | `/q` actual toggle; synthesis + speech safety tests | Real audible playback/output device NOT TESTED; speech starts enabled if eSpeak is available |
| Offline Whisper transcription | Phase 6E | PARTIALLY WORKING | Actual configured backend on synthetic PCM | Nonempty transcript, but did not match “Hello Friday” exactly; execution verified, accuracy not established |
| Microphone availability | Phase 6E | WORKING | `arecord -l` metadata only | Card 1 ALC256 Analog capture device exists; no recording |
| Microphone capture/readiness | Phase 6E | NOT TESTED | Headless capture/error tests | Owner interaction and explicit activation required; never activated during audit |
| `/voice` and typed transcript confirmation | Phase 6E | EXPERIMENTAL | Voice/provenance/confirmation tests | Fixed reviewed device, bounded capture, private temporary audio; real microphone end-to-end pending |
| Startup spoken greeting | Phase 7A | PARTIALLY WORKING | Timezone/once/config/missing-TTS tests + source | Noninteractive startup skipped greeting as intended; actual audible interactive greeting pending |
| VS Code native ELF launch backend | Phase 7A | NOT TESTED | Native executor/identity tests | Reviewed native package not installed; no GUI launch |
| Firefox native ELF launch backend | Phase 7A | NOT TESTED | Native executor/identity tests | `/usr/bin/firefox` is a wrapper, not supported native ELF |
| Installed Snap VS Code launching | Phase 7A repair | PARTIALLY WORKING | Actual approved CLI launch + snapd/immutable package validation | Launcher running after bounded wait; new Code GUI window not verified |
| Installed Snap Firefox launching | Phase 7A repair | PARTIALLY WORKING | Actual approved CLI launch + fixed publisher/provider checks | Launcher running after bounded wait; Firefox executable observed; new GUI window not verified |
| Native Ubuntu Files/folder routing | Phase 7A | WORKING | Actual production composition + deterministic route tests | Bare commands select native backend, never FRIDAY Browser |
| Native Files visible folder opening | Phase 7A | PARTIALLY WORKING | Four actual approved CLI requests; Nautilus D-Bus declarations | Requests accepted, registered Nautilus observed; FD URI is not durable after FRIDAY exits; visible correct folders unverified |
| Repeated native folder attempts | Current repair | NOT TESTED | Headless real gateway/SQLite, mocked process | Suppression removed; each approved request attempts launch up to existing limit; live GUI pending |
| Exact native window ownership/closing | Phase 7A requested | NOT IMPLEMENTED | Reviewed desktop API/source investigation | No reliable FRIDAY-created window attribution; no closing, broad kills or unsafe automation |
| FRIDAY Browser | Phase 7A experiment | EXPERIMENTAL | Actual worker loop/socket protocol with GTK stand-ins | Explicit commands only; real GTK persistence pending; no native interception |
| Q atomic storage/order/max-three/dedup | Phase 7A | WORKING | Real SQLite transactions/restarts in tests; read-only owner DB query | Owner DB had 3 rows and 0 duplicate activity keys; no row was rewritten during read-only inspection |
| Q desktop launch recording/resume | Phase 7A | PARTIALLY WORKING | Real permission/path/SQLite fixtures with mocked GUI processes | Accepted outcomes only; stable IDs, exact target revalidation, fresh approval; real accepted launches stored; extra GUI resume not authorized in six-request plan |
| Historical Q compatibility/backend conversion | Phase 7A repair | PARTIALLY WORKING | Legacy SQLite/version/label/conversion tests | No automatic rewrite; approved repeats upgrade metadata with stable identity; explicit Browser conversion retains backend distinction |
| Registered project/yesterday resume | Phase 7A | PARTIALLY WORKING | Mapping/inode/date/permission tests | Actual project GUI resume pending; no invented external work history |
| General installed-app discovery/other apps | Planned desktop phase | NOT IMPLEMENTED | Registry/source and desktop-entry inventory | Only Files, Firefox and VS Code approved; Calculator, Text Editor, Terminal, LibreOffice and others installed but not automatically trusted |
| Wake word/always-listening/unrestricted automation | Roadmap | NOT IMPLEMENTED | Source inventory | No background microphone/window monitoring or generic shell/tool execution |

Expected/current source and test map:

| Subsystem | Source files | Expected/current behavior | Automated coverage |
|---|---|---|---|
| CLI/config/provider | `friday/main.py`, `config/settings.py`, `providers/ollama.py` | Startup, identity, lazy voice configuration, local HTTP/error handling, clean exit | `test_cli`, `test_core`, `test_ollama`, `test_ollama_final_answers` |
| Memory | `memory/database.py`, `manager.py`, `models.py` | Sessions/messages/memories; SQLite Q and project sessions | `test_memory`, `test_recent_work`, `test_managed_browser` migration cases |
| Runtime/sync | `models/{manager,queue,registry,job,profile}.py`, `sync/{native,fallback,base}.py`, `native/sync/friday_sync.c/.h` | Synchronous bounded jobs; POSIX mutex; startup-only fallback | `test_model_runtime`, `test_sync`, `test_l2_reliability`, `test_l3_reliability` |
| Safe tools | `tools/{base,registry,models,manager,permissions,files,filesystem,grants,access,sensitive,system,computation}.py` | Exact schemas, denied writes, bounded roots/FD operations, scoped permissions | Tool/file/multi-folder/system/computation/filesystem-permission tests |
| Routing/context | `tools/{router,locations,intent_translator,presenter}.py`, `core/{assistant,context,workload,navigation,file_context,response}.py` | Deterministic before bounded model proposals; context/privacy and workload policy | Tool-routing, semantic-location, translator, navigation, file-reference, workload tests |
| Voice | `voice/{configuration,backend,cli,tts,startup}.py` | Offline dependencies; explicit capture and transcript confirmation; safe speech | `test_voice`, `test_voice_foundation`, `test_voice_capture`, `test_voice_automatic`, `test_recent_work` |
| Desktop/Q/browser | `desktop/{registry,runtime,routing,recent,sessions,navigation,guard,browser,browser_worker}.py` | Fixed approved identities; one-use launch/navigation; Q persistence; explicit experimental browser | Desktop/navigation/repair/recent/browser/lifecycle/native-opening-policy tests |

## Confirmed fixes

1. Removed the production native Files session suppression and cooldown checks.
   A previous launch receipt is no longer authority to refuse another approved
   target. Each requested native location is revalidated, approved once and
   attempted. No new window-management framework was introduced.
2. Updated the former suppression tests to assert the new owner policy, retaining
   denial, stale paths, no-shell, no-read-grant, budget and truthful-outcome checks.
   Five additional regressions cover bare native defaults, VS Code wording,
   repeated Firefox persistence, Downloads ordering/resume denial, and Home aliases.
3. Kept Q deduplication independent from launch suppression. Its unique key is
   reviewed application identity plus approved canonical target, with legacy
   operation-based keys normalized safely. Application aliases converge on the same ID; Files/Home aliases
   converge on the same folder activity. Browser and Nautilus activities remain
   distinct applications. Repeats refresh one stable record and recency.
4. Initially improved Snap rejection diagnostics rather than substituting PATH.
   After the explicit owner decision, added the separate app-only reviewed Snap
   adapter described below; the general native policy remains unchanged.
5. Updated current README guidance and labeled superseded desktop reports as
   historical, with this audit as the current behavior/evidence reference.

The limit still permits four actual process starts per session. Denials,
validation failures and process-spawn exceptions consume none. This audit did
not remove/increase that protection. Six successful launch requests in one
session, including the owner's full future Firefox/Code/Files sequence and Q
resume, would exceed it. The acceptance plan must use two FRIDAY sessions unless
the owner separately approves a launch-budget policy change.

## Snap security findings and implementation gate

Installed read-only diagnostics:

| App | Package | Revision | Verified publisher | Snap ID | Confinement |
|---|---|---|---|---|---|
| VS Code | code | 264 / 7debcd0e | vscode | Ht0aUHi7ofh9Fbwh6m7jUN2pAy6kzBiu | classic |
| Firefox | firefox | 8763 / 154.0-1 | mozilla | 3wdHCAVyZEmYsCMFDE9qt92UV8rC8Wdk | strict |

Metadata came from the local root-owned snapd socket and actual installed files,
not PATH alone. Both `/snap/bin` app links point to `/usr/bin/snap`. Desktop entries
identify the correct app, but arbitrary Exec fields are not execution authority.
Code's entry includes `--force-user-env`; Firefox's `/usr/bin/firefox` wrapper can
change browser defaults and desktop favorites, so that wrapper is not an
acceptable substitute under the owner's no-system-desktop-change requirement.

Both packages reside on read-only squashfs mounts. Code's root-owned mount/source
files advertise group-writable mode bits, but the filesystem is read-only; a safe
future implementation must explicitly verify immutability rather than ignore
writable bits. Static root ownership alone is insufficient for the whole chain.

Concrete execution-chain blockers:

- `/snap/code/264/electron-launch:60` sources
  `$SNAP_USER_DATA/.last_revision` as shell code. The corresponding installed
  owner file has mode 0664. The package also supplies `--no-sandbox`; this audit
  did not introduce or execute that flag.
- Firefox's installed GNOME content provider
  `/snap/gnome-46-2404/164/command-chain/desktop-launch` sources
  `$SNAP_USER_DATA/.last_revision` and owner `user-dirs.dirs` as shell code.
  Its GPU/desktop command chain also crosses independently updated content mounts.
- Pinning `/usr/bin/snap` does not pin the final application's ELF or its complete
  dispatch/command chain. `snap run` has no inspected application-revision launch
  option that preserves the existing final-executable FD contract. No shell/debug
  launch mode was used. Canonical describes the separate snap/snap-confine/snap-exec
  pipeline in its [snapd architecture](https://github.com/canonical/snapd/blob/master/ARCHITECTURE.md).

The owner subsequently explicitly authorized the startup-file trust risk for
normal **app-only Firefox and VS Code** launches. `desktop/snap.py` implements
that separate exception without changing `ApplicationRegistry.executable`.
It pins the root-owned ELF `/usr/bin/snap`, checks root-owned helpers, fixed Snap
IDs and verified publishers, active/no-devmode/no-ignore-validation registration,
expected package image and current revision, read-only mounted package metadata,
and fixed Canonical runtime-provider identities. Firefox's exact content plugs
must resolve to the reviewed GNOME/Mesa/theme providers. Metadata fingerprints
are compared after approval and immediately before spawn. Code uses its reviewed
core20 base; Firefox uses core24. These dependencies receive **no launch exception**.
`SNAP_REEXEC=0` is fixed and only structured `run code`/`run firefox` arguments are
allowed. Editor startup uses a fresh private profile with fixed safety settings.
No user-supplied flags, shell mode, desktop Exec execution, or distro Firefox
wrapper is used. Xauthority is forwarded only as an owner-private regular-file
path beneath the verified session runtime; cookies are never read or logged.

This deliberately delegates the final launch chain to trusted snapd rather than
claiming a final-ELF FD contract. Snap refresh is not atomically locked by this
adapter; trusted daemon/package updates can race dispatch after final validation.
The installed Code package itself adds `--no-sandbox`; FRIDAY does not add it.
Owner-authored startup shell content is part of the expressly accepted risk, and
Code is classic-confined. This is not permission for FRIDAY-generated shell code.
No owner startup files were modified by this work; normal applications can have
their own startup side effects. App-only approval does not authorize project/file
or URL arguments. Those remain blocked because Snap closes/internally redispatches
FDs and a durable exact-target handoff has not been proven. Native reviewed Code
still supports descriptor-pinned projects/files. No broader exception was assumed.

An alternative is an owner-provisioned reviewed native installation matching
`registry.py` candidates. For VS Code, `/usr/share/code/code` or `/usr/lib/code/code`;
for Firefox, an actual native ELF at the reviewed `/usr/lib/firefox` candidates.
Administrator ownership, non-writable ancestors, no symlinks and ELF verification
remain required. No install/uninstall, system permission or package change was
performed or authorized automatically. Existing Snap installations remain intact.

## Real runtime, voice and GUI evidence

Actual core tests used the configured installed model/service and native library,
with temporary SQLite and only public prompts. The first infix calculation attempt
was rejected; the documented grammar was then tested and returned 5.0. L0/L1
made zero model calls; L2/L3 each made one. Public conversation answers were checked
for completed/nonempty final output, not factual accuracy or every intent class.
No model was downloaded, service configuration changed or private conversation
read. Actual CLI help and voice dependency diagnostics also completed. A separate
noninteractive CLI check sent `3` after a denied native request. Noninteractive
approval refused before reading a choice, so `3` was correctly outside permission
context and became an ordinary model request; Ollama hit the completion limit.
FRIDAY showed a fixed error, continued and exited cleanly. This is a real observed
failure, not a successful AI answer, and was not hidden by mocked tests.

Actual voice checks: eSpeak NG 1.52.0, pinned tiny.en configuration verified;
ALC256 capture hardware listed. A public synthetic WAV was resampled to the
backend's required finalized 48 kHz/stereo/16-bit PCM and passed through the
actual Whisper backend. Its result was nonempty but not the exact expected phrase.
The clip was temporary and removed; there was no playback or microphone recording.
A real `/voice` capture, human transcription accuracy and audible `/speak` remain
NOT TESTED and need the owner's participation.

The inherited desktop environment exposes `DISPLAY=:0`, `WAYLAND_DISPLAY=wayland-0`,
`XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=ubuntu:GNOME`, and a trusted
`/run/user/1000` session. Local D-Bus is reachable outside the execution sandbox;
Nautilus did not own its bus name during the initial read-only check. This proves
session availability, not application visibility.

The owner-approved six-request plan was executed over two real PTY CLI sessions
using `--adaptive --diagnostics`, `/q` to disable speech, and `1` at each actual
exact-operation prompt. No mock provider, approval override, or fake process was
used. Each session retained its four-process launch ceiling.

| Real request | Attempted | Runtime outcome | Application process evidence | GUI window verified | Owner confirmation |
|---|---|---|---|---|---|
| Firefox once | YES | Launcher alive after 1-second wait | Firefox ELF processes observed; existing instance also present, new launcher later exited | NO | Required for new window |
| VS Code once | YES | Launcher alive after 1-second wait | Existing Code ELF processes observed; distinct new GUI process not established | NO | Required |
| Ubuntu Files Home once | YES | Launcher exited 0 | No lasting Nautilus instance established at the first process check | NO | Required |
| Downloads once | YES | Launcher alive after bounded wait | `org.gnome.Nautilus` bus ownership observed | NO | Required for requested folder |
| Documents once | YES | Launcher exited 0 | Existing Nautilus registration available | NO | Required for requested folder |
| Registered FRIDAY folder once | YES | Launcher exited 0 | Existing Nautilus registration available | NO | Required for requested folder |
| Q numbered resume on real GUI | NO | Not included in six authorized launches | Headless fresh-approval/resume tests only | NO | Separate test needed |
| FRIDAY Browser real GTK | NO | Not in owner plan; never intercepts native defaults | Headless worker lifecycle tests only | NO | Remains experimental |

Nautilus's `org.freedesktop.FileManager1` introspection reported `OpenLocations`
and `OpenWindowsWithLocations` containing the FD URI sent by FRIDAY. A window
registration is not compositor visibility, exact ownership, or proof of the
approved canonical folder. In particular the URI is `file:///proc/<friday-pid>/fd/<pin>`;
when the CLI exits that pathname disappears. This confirms a **durable folder
handoff bug**, even though OS acceptance is truthful. It cannot be resolved by
closing user windows, a cooldown, or guessing a Nautilus window identity. The
owner was asked whether to authorize canonical approved path handoff with inode
and symlink checks but without an atomic FD contract; no such relaxation is
implemented without an answer. No extra GUI launches or broad kills were used.

The final real Q menu contained FRIDAY — Ubuntu Files, Documents — Ubuntu Files,
and Downloads — Ubuntu Files. The second session used the same SQLite database
and native defaults. The GUI plan did not repeat a command; equivalent-wording
and duplicate-name behavior are covered by temporary synthetic tests only.

## Original discovery functionality and restored named resolution

Git source at `65a11e0` and tool merge `084c307` contains descriptor-backed
`ListDirectoryTool`, file metadata/info and bounded supported-text reading.
Phase 6B added exact read/list approvals and persisted read-only roots. Phase 6C
added XDG semantic locations and `NavigationManager` references/history from
verified terminal listings. Those implementations remain in use. No historical
bounded recursive arbitrary-name finder was found; claiming one was restored
would invent history. The new small `tools/discovery.py` component reuses those
boundaries rather than replacing the file tools or adding another GUI/framework.

| FEATURE | VERSION | STATUS | TEST METHOD | NOTES |
|---|---|---|---|---|
| Existing explicit listing/text references | v0.4.0 / Phase 6C | WORKING | Actual descriptor-backed temporary trees and existing tests | Content approval remains separate; prior terminal reference semantics retained |
| Named bounded metadata discovery | Current Phase 7A repair | PARTIALLY WORKING | Synthetic descriptor tests + actual CLI no-match search | Authorized project root searched; owner portfolio content untouched; successful live selection pending |
| Duplicate-name target selection | Current Phase 7A repair | PARTIALLY WORKING | Multiple temporary portfolio directories + actual routing/gateway | No automatic first-match launch; live owner selection pending |
| Resolved native Code project/file handoff | Current repair | NOT TESTED | Pinned descriptor/approval mocks | Native Code not installed; no real GUI target verification |
| Resolved Snap Code project/file handoff | Current repair | NOT IMPLEMENTED | Explicit rejection regression | App-only authorization cannot preserve exact target FD through Snap redispatch |
| Canonical Q aliases/compact menu | Current repair | WORKING | Real SQLite migrations, restarts, routing tests + actual CLI menus | At most three distinct activities; old metadata archived when normalized |

`open NAME`, `find NAME`, `where is NAME`, `show NAME location`, `open NAME in
LOCATION`, `open NAME in APPLICATION`, and `open NAME from LOCATION in APPLICATION`
are parsed deterministically. Supported explicit search locations are Downloads
and Documents; unqualified searches use configured/persistently authorized roots
only. No all-machine search is inferred. Root/system trees are forbidden.
Scopes without an existing grant require exact `search_directory` approval,
metadata only and Allow once only. Search never creates read/content grants.

Limits: maximum depth three, 1,000 examined entries, 20 results and a cooperative
two-second traversal deadline excluding permission waiting. Hidden entries,
sensitive names and all symlinks are skipped. Descriptor-relative child traversal
checks entry inode against the opened descriptor. Local filesystem syscalls may
block beyond the cooperative deadline; no background search thread is added.
Incomplete results say so and do not automatically launch the sole candidate.
A no-match message identifies searched scopes and suggests an explicitly approved
Downloads/Documents search. Ambiguous matches and destination choices have
120-second, one-input numeric context; unrelated/slash commands clear it.

Selected targets and search-scope inodes are revalidated before and after desktop
approval. No file-content bytes are read during discovery. Regular files offer
only the reviewed editor action; directories offer Code or Ubuntu Files. Existing
explicit supported-text commands and listed-name terminal references retain their
old behavior; destination-qualified commands choose desktop opening in that
context. All discovery results/choices stay out of ordinary chat, speech and
conversation SQLite history. Voice-derived accepted operations cannot persist Q.

The installed Code is Snap-only. `open portfolio from downloads in vs code` can
find and disambiguate the target, but currently returns a precise unsupported
exact-target message rather than broadening the owner's app-only exception.
No owner's portfolio content was inspected, changed, created or launched.
The real CLI additionally exercised `find portfolio` and `open portfolio` within
its existing authorized FRIDAY project root: no match existed there. Both used
L1 deterministic discovery with zero model invocations, reported the actual
scope and bounds, and offered an explicitly approved Downloads/Documents search.
No new filesystem scope was approved and no GUI launch followed discovery.
Duplicate-match and successful selected-project behavior remain synthetic tests;
the owner's real portfolio location was not inferred or searched outside grants.

## Q persistence and privacy review

Current additions: descriptor version 4 uses stable application + target keys
independent of command wording and separates the search scope's inode from the
selected target inode. A validated read view folds equivalent historical default
Browser/native locations while preserving the actual latest record's application
label and resume backend. Version 4 explicit Browser requests are distinct
user-selected workflows. Read-only display does not delete or rewrite history.
On an accepted equivalent repeat, the latest stable UUID survives and superseded
legacy metadata is retained in `recent_work_legacy_archive` within the same SQLite
transaction before normalization. Existing alias duplicates are normalized before
trimming so they cannot evict a third distinct activity. Ordinary fourth-activity eviction remains the
documented three-slot queue policy. The default menu shows only location/app;
`show Q diagnostics` exposes factual summary and window-unverified status.

The actual existing owner SQLite database has tables `sessions`, `messages`,
`memories`, `desktop_project_sessions` and `recent_work` (plus SQLite sequence).
A read-only query found three Q rows and zero duplicate activity keys, including
historical `folder` rows and a newer `nautilus_location` row. No conversation,
private title, URL or folder contents were printed. No history was deleted.

Q uses a UNIQUE activity key, stable UUID, canonical target identity, versioned
fixed resume descriptor, factual summary, accepted/confirmed status, timestamp
and monotonic launch-order column. Atomic upsert and eviction cap visible rows
at three. Descriptor versions 1/2/3/4 remain validated; new exact repeats update the
same row/type rather than duplicating it. Version 4 adds canonical app/target keys and resolved search scope identities. Historical application-only Files
records have no saved folder identity and are not silently conflated with a
verified location. Browser/Files backend differences remain explicit.

Only OS-accepted or still-running launch outcomes enter native Q, with window
unverified. Denied, failed, untrusted and unsupported operations do not. Browser
navigation requires its own exact acknowledgment. Voice requests use persist=False;
unconfirmed voice requests never execute. Every resume revalidates descriptor,
registered mapping, path device/inode and executable, and requests fresh approval.
SQLite errors are contained and report that saving failed; they do not falsely
record activity or silently grant execution. Display strings and stored metadata
are sanitized/validated against control injection.

## Dead code, overlap and documentation mismatches

- `RecentLaunchGuard` and `FileManagerNavigationController.blocked()` are retained
  compatibility helpers but are no longer consulted to suppress native launch.
  Their existing configuration validation and bounded receipt bookkeeping remain;
  they are not a new cooldown or background monitor. Future cleanup can remove
  obsolete compatibility machinery after owner review.
- Native Files and FRIDAY Browser are separate backends, not equivalent identities.
  Only explicit Browser commands select the experimental GUI. Their earlier default
  command migration and suppression guidance is superseded by this audit.
- Terminal directory history, Q numeric context and Browser history serve distinct
  purposes. While Browser history is active, generic go back/forward targets it;
  that remains an experimental UX overlap to resolve before broader rollout.
- Generic `inspect_running_applications` intentionally returns unsupported; it is
  a declared tool, not a verified visible-window inspection implementation.
- WriteFileTool is implemented but normal chat lacks a write approval gateway.
  Documentation must not imply unrestricted or automatic editing.
- Structured memory API exists without automatic personal fact extraction.
- NativeSemaphore is a historical name; C uses a POSIX error-checking mutex,
  not a semaphore. ModelManager is synchronous, not a background inference service.
- README combines historic phase counts/roadmap with uncommitted later additions.
  Claims such as future Phase 7 or completed voice should be read against current
  source and the statuses above. No additional release was invented.

## Automated verification and changes

Final full headless verification: **1,208 tests passed**; no failures/errors/skips.
`make -C native/sync` succeeded (target already up to date).
`git diff --check` passed. GUI processes are mocked in automation. The worker's
socket tests use GTK stand-ins; execution outside the socket-restricting sandbox
was required, with no real GUI launch. Temporary synthetic voice/core checks are
separate actual-runtime audit actions, not default test-suite behavior.

Focused files changed in this audit:

- `friday/desktop/runtime.py`: remove native launch suppression.
- `friday/desktop/registry.py`: truthful Snap boundary diagnostic.
- `friday/desktop/snap.py`: separate owner-authorized, fixed app-only Snap backend.
- `friday/desktop/routing.py`: native defaults, aliases, discovery selection and Q diagnostics.
- `friday/desktop/recent.py`: canonical version-4 identities, validated legacy dedup view and compact display.
- `friday/tools/discovery.py`: bounded metadata search, scope approvals, target/application selection, scope/target revalidation.
- `friday/main.py`: compose discovery with existing filesystem access; clear selection context on slash commands.
- `friday/core/assistant.py`: preserve existing terminal listing/reference behavior while routing new deterministic discovery privately.
- `friday/memory/manager.py`: atomic legacy normalization/archive with stable queue UUIDs.
- `tests/test_desktop_navigation.py`, `tests/test_desktop_repair.py`,
  `tests/test_browser_lifecycle.py`: update superseded native suppression expectations.
- `tests/test_native_opening_policy.py`: five native routing/approval/Q regressions.
- `tests/test_discovery.py`, `tests/test_reviewed_snap.py`: synthetic discovery, scope and target substitution, Q migration and exact Snap exception tests.
- `tests/test_recent_work.py`, `tests/test_managed_browser.py`, `tests/test_tool_routing.py`, `tests/test_navigation.py`: assert compact Q versus diagnostics, preserved lifecycle/registry and unknown-name discovery without expanding once-only read grants.
- `README.md`: current audit link and native opening policy.
- `docs/PHASE_7A_BROWSER_REUSE.md`, `PHASE_7A_NAVIGATION.md`,
  `PHASE_7A_DESKTOP_REPAIR.md`, `PHASE_7A_MANAGED_BROWSER.md`: historical banners.
- This audit report.

Current scope inventory: 63 Python modules, native C/header/build files and 34 automated test modules; all Python modules parsed successfully. Source review plus test/runtime evidence is not a formal proof of security or exhaustive GUI behavior.

All unrelated tracked/untracked owner work was preserved. No release identifier,
package, microphone setting, system permission or desktop configuration changed.

## Next priorities

1. Resolve the separately requested Nautilus canonical-path handoff decision. The FD URI cannot remain usable after FRIDAY exits; do not quietly weaken target substitution protection.
2. Obtain owner window/folder confirmation for the completed six-request GUI plan; investigate any confirmed application failure without unauthorized relaunches. Do not report the desktop success criteria
   as complete before this evidence exists.
3. Retest Q end-to-end against accepted native/Snap launches and owner-visible
   resume, preserving fresh approval and the maximum-three policy.
4. Review the four-launch session budget's impact on ordinary acceptance without
   silently changing it. Six real launches require two current sessions.
5. Improve real voice accuracy with authorized human capture; keep microphone
   opt-in and temporary audio. Investigate CPU response latency and experimental
   browser/history UX after basic application launching is reliable.

## Owner acceptance script

```bash
cd ~/Projects/FRIDAY
source .venv/bin/activate
python -B -m friday.main --adaptive
```

Enter the requested sequence, choosing Allow once at each actual exact-operation
prompt (Denial must leave Q unchanged):

```text
open firefox
open vs code
open files
open downloads
open documents
show Q
1
```

**Current expected result:** Firefox and VS Code now attempt their fixed reviewed
Snap app-only launches after one approval. Files/folders attempt native Nautilus;
no FRIDAY Browser prompt or cooldown is involved. Actual visible acceptance is
still pending, and native FD locations are not durable beyond their FRIDAY session.
Six requests cannot fit the unchanged four-launch budget: use session A for
Firefox, Code, Files, Downloads; restart for session B Documents, project folder,
Show Q. An owner-operated numbered resume is an additional freshly approved
attempt. `show Q diagnostics` exposes truthful status; the default Q menu is compact.

Discovery acceptance (use an existing real target; do not create/modify owner files):

```text
find portfolio
find portfolio in downloads
open portfolio in downloads
open portfolio from downloads in vs code
show portfolio location
show Q
```

Search scope approval is separate from desktop launch approval. An unqualified
search uses only configured/persistently authorized roots; Downloads is not
silently searched unless already authorized or explicitly requested. Multiple
matches require numeric selection and unspecified destination requires choosing
VS Code or Ubuntu Files. On this Snap-only Code installation, resolved project
opening explains the app-only limitation and does not pretend it launched.

For optional owner-operated voice acceptance, run `--check-voice-config` first.
In an interactive FRIDAY session, `/voice` keeps the microphone OFF until the
owner presses Enter at its activation prompt; speak only after SPEAK NOW, then
explicitly confirm or deny the transcript. `/speak Hello Friday` tests audible
output; `/q` toggles automatic output. These actions were not performed during
this audit and require the owner's choice/interaction, not synthetic activation.
