# Phase 2A additional desktop requirements — implementation report

Date: 2026-10-31. Current checkout: `/home/vigneshwar/Projects/zorvyq`.
This extension preserves the existing assistant, RAG authorization/citation pipeline,
native POSIX synchronization, models, approved knowledge and prior uncommitted work.
The historical `/home/vigneshwar/Projects/FRIDAY` directory is absent. No directory
move, commit, push or GitHub modification was performed here.

Before editing, 68 starting modified/untracked files were archived with hashes and
a binary Git diff under ignored `data/migration/phase2a-additional/`. `.env` was
excluded and never read. Existing migration/Phase 1F/1G work remains present.

## Implemented behavior and evidence boundaries

| Capability | Current state | Verification boundary |
| --- | --- | --- |
| GUI launcher | Available in checkout; installed wrapper repair pending | Isolated desktop installation, exact environment/argv and offscreen GUI tests |
| Welcome | Available; local-time greeting, real approved recent work, dismissal | Clock fixtures, temporary metadata and offscreen rendering |
| VS Code chooser | Available; clicks and numbered chat replies, direct authorized child folders | Mocked process tests; no real VS Code launch |
| Recent projects | Available; existing SQLite store, up to ten activities, deduplication, restart restore, dismiss/clear | Temporary database persistence and reopened-instance tests |
| Answer Length | Available; Short default, Balanced, Detailed; explicit detail/code/citation preservation | Both model prompts tested with mocked chat; real style acceptance pending |
| Voice settings | Experimental; installed inventory, speed, volume, explicit preview, preferences | 141 actual inventory rows; mocked playback/errors; audibility unverified |
| Microphone | Experimental; session OFF default, one-shot approval and reviewed transcript | Existing mocked capture tests; physical device acceptance pending |
| Qwen/RAG | Existing architecture retained; exact-scope permission and citations | Full regression and synthetic citation/permission tests; no inference or reindexing |
| Foundation-Sec | Experimental manual ordinary chat; availability check and explicit fallback guidance | Mocked selection/template/structured-output contract tests |
| Specialist RAG/automatic routing | Unavailable pending owner acceptance and future reviewed rollout | Production Qwen guard retained; no routing enabled |
| Nmap | Installed; experimental explicit bounded discovery adapter | Argument/permission/expiry/cancellation mocks; no scan executed |
| Other security tool execution | Unavailable pending individual review | Existing registry inspection; no exploit framework added |
| Model status/unload | Available; metadata only at startup, serialized native gate, conflict refusal and warned unload | Mocked residency/unload checks; external clients can race service snapshots |
| Login integration | Partially implemented; exact reversible migration available, inactive | Temporary-home tests; actual login migration needs approval |

About/capability entries describe implementation, permission and evidence. No new
capability is marked WORKING merely because its code or mocked test exists.

The legacy terminal trigger is `~/.config/autostart/friday.desktop`, with
`Terminal=true` and an enabled CLI Exec against the old FRIDAY path. A separate
unreferenced `~/.local/bin/friday-start.sh` explicitly opens GNOME Terminal. Installed
`~/.local/bin/zorvyq` also points to the stale checkout. All were left untouched.
See the [startup migration guide](ZORVYQ_STARTUP_MIGRATION.md) for exact findings,
installation command, approval, backup and restoration procedure.

## Tests performed

- Final full regression: **1,780 tests passed** in 15.350 seconds.
  Log: `/tmp/zorvyq-full-regression-final.log`.
- A prior sandbox run had four browser IPC PermissionErrors with four paired failures;
  the successful reruns used the approval mechanism for local Unix-socket access.
  This did not authorize or trigger models, scans, audio playback or VS Code.
- Earlier focused run: 106 tests passed across the extension, controller, offscreen
  UI, existing recent-work and specialist contract tests. The final full regression
  includes subsequent stale-wrapper and cross-workspace chooser checks.
- Staged installation at `/tmp/zorvyq-launcher-review`: all ten launcher verification
  checks passed, including `Terminal=false`, correct interpreter, executable wrapper,
  desktop specification and icon. A stand-in interpreter verified that manual
  wrapper invocation needs neither virtual-environment activation nor Terminal.
- `git diff --check` passed. New/modified Python modules were imported by the suite.
- Tests use temporary project folders/databases/preferences and mocked side effects.
  Offscreen desktop tests were isolated from the owner's recent-work/preferences.
  No real Qwen/Foundation-Sec/Nomic inference, network discovery, VS Code window,
  microphone capture or audio playback was run during this extension.

The new tests cover response-length modes and detail override prompts, unchanged
citations, actual-format voice inventory, selection/fallback/preferences/errors,
startup identification/approval/preflight/stale wrappers/backup/restoration/toggles,
project enumeration/mapping/invalid/cancel/stale/expiry/space names/symlink escapes,
subprocess arrays, successful-launch-only persistence, bounded history, restart,
missing paths, removal/clear, no specialist auto-routing and bounded Nmap denial,
argument construction, expiry and cancellation. Existing synthetic specialist tests
cover unknown/missing/malformed citations, revoked sources and retrieval denial.

## Owner approvals still required

1. Repair the three installed ZORVYQ launcher/icon/application metadata files from
   the current checkout. The concrete replacement is staged for inspection at
   `/tmp/zorvyq-launcher-review`. This persistent user-system change was not made.
2. After actual GUI launcher acceptance, approve disabling exactly
   `~/.config/autostart/friday.desktop` with its reversible backup and replacing it
   with the GUI login entry. The runtime settings dialog requests this exact approval.
3. Any package installation or live RAG dependency repair, if necessary, needs
   separate approval. No packages were installed.
4. Specialist automatic routing, further security-tool execution and GitHub renaming
   remain separate owner decisions. No commit or push is included.

## Manual acceptance sequence

1. Use Ubuntu Run Application to launch
   `/home/vigneshwar/Projects/zorvyq/bin/zorvyq`. Confirm a graphical dashboard,
   greeting, no Terminal window, no inference/audio and no automatic app reopening.
2. Type “ZORVYQ, open VS Code”, inspect the exact list, select a project by number,
   and verify VS Code's actual workspace path. Repeat by clicking; test Cancel.
3. Close/reopen the GUI, then reboot when convenient. Confirm the chosen projects
   remain offered and Continue opens the exact saved folder. Test entry dismissal.
4. Settings → Answer Length: try Short, Balanced and Detailed. Ask for detail while
   Short is selected and check completeness, uncertainty, code and source citations.
5. Settings → Voice: enable output, select an installed voice, adjust speed/volume,
   press Test Voice, and confirm actual sound. Restart and check preferences. No
   claim is made that the earlier offline audio failure is fixed.
6. Confirm microphone actions start OFF. Only if desired, enable actions, explicitly
   activate once, review/discard a transcript, and verify Send is separate.
7. Cybersecurity: Qwen + approved knowledge must request exact access and verify
   citations; denial must produce no general-model fallback. Dependencies may need
   separately approved repair. Specialist+approved knowledge must refuse. Ordinary
   specialist chat requires manual selection and disabling approved knowledge.
8. Review Nmap status and arguments. Only after confirming authorization, use an
   isolated lab target if testing execution; check Cancel. No production network
   assessment or specialist routing is part of automated acceptance.
9. After launcher approval/installation, open ZORVYQ from Applications. Separately
   approve the exact startup migration, log out/in and check a single GUI, no legacy
   terminal, and normal manual Ubuntu Terminal behavior. Test OFF/ON if desired.

Further details: [Voice](ZORVYQ_VOICE_SETTINGS.md),
[Recent projects](ZORVYQ_RECENT_PROJECTS.md),
[VS Code chooser](ZORVYQ_VSCODE_PROJECT_CHOOSER.md),
[Cybersecurity](ZORVYQ_CYBERSECURITY_INTEGRATION.md).
