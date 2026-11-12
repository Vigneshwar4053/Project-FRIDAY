# ZORVYQ Phase 2C implementation report

Date: 2026-10-31. Status: implemented and fixture-tested; physical voice and live diagnostic acceptance pending owner operation.

## Confirmed findings and changes

- The desktop did not dispatch speech after answers, had no spoken welcome path, and saved speech was disabled. Existing eSpeak NG, 141 installed voices, the local Whisper executable and checksum-pinned tiny.en model were present. ALSA capture identity matched the approved ALC256 device and was closed during metadata inspection; desktop audio sockets existed. This does not verify sound, microphone permission or transcription compatibility.
- Existing offline adapters are retained. Speech enable/disable, installed voice fallback, speed, volume, test and owned-process stop are connected. Default output routing remains Ubuntu-controlled. Voice state, bounded explicit capture, cancellation, local transcription, editable review and explicit final Send are connected without background listening or cloud fallback.
- Existing trusted response provenance controls conversational speech. Private, unknown, tool and RAG answers do not speak automatically. Explicit visible-answer speech requires confirmation. Structured/long answers use brief speech while keeping full visible text. Model choices, response modes, synchronization and RAG approvals remain intact.
- Welcome speech defaults off, waits briefly for desktop audio, attempts once per startup and uses actual task counts. Existing recent-work controls remain available. No autostart file was changed.
- My Tasks is a separate SQLite store with transactional create/update/status/delete, UUIDs, timestamps, priority, description and project association. Deterministic text/confirmed-voice intents use explicit forms and confirmations. Ambiguous matches require selection. Task content is not passed into model/chat history.
- Reminders persist and run through an in-app Qt timer. Missed reminders are claimed on next launch, with persistent duplicate prevention. No background scheduling service is installed. Desktop notifications are attempted only when supported, with an in-app fallback.
- Existing operations already reached the registry, approval and worker in mocks. Confirmed output/report gaps are repaired: planned commands, live complete-line stdout/stderr, exit/time/status, copy action, readable report sections and Markdown/JSON export. System Health adds reviewed free/df/uptime argv; Network Overview adds a socket summary. The same allowlisted Runner handles commands.
- No live reproduction establishes the original operation-button failure's runtime cause. Read-only executable resolution found Node and Docker absent from reviewed paths, while initial health/network/security previews resolved. Missing tools remain unavailable; no packages were installed.

## Verification

Targeted command:

```sh
PYTHONPATH=tests:. QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m unittest test_zorvyq_phase2c test_zorvyq_operations test_zorvyq_desktop test_voice_capture test_voice_automatic
```

Full regression command:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m unittest discover -s tests
```

The initial full run was blocked by sandbox Unix-socket permissions in four existing headless browser tests (four errors plus four cleanup failures). A permitted rerun outside that restriction passed. Final verification passed: **152 targeted tests**, **1,862 full regression tests**, and `git diff --check`. Offscreen plugin warnings are expected and do not certify physical desktop behavior.

Fixtures cover speech disabled/enabled, voice fallback/missing inventory, playback failure/stop, state and startup-once behavior, microphone permission denial, transcription errors, editable/cancelled review, no model dispatch before Send, task CRUD/restart/dates/reminder claims/rescheduling, ambiguous selection and confirmation, GUI → real engine with mocked collectors/command transport, preview argv consistency, permission denial, stream labels, nonzero/timeout/cancellation/output bounds, export, and AI failure retaining the report. Existing voice and operation suites cover native WAV validation, prerequisite failures and arbitrary-command rejection.

No real model inference, microphone capture, audio playback, live diagnostic command, Nmap scan, privileged operation, firewall modification, package installation or reindex was performed. Audio metadata and executable/model inventories were inspected only. Existing uncommitted work was retained. No commit or push was made.

## Acceptance and limitations

Use the detailed owner checklists in:

- [Voice diagnosis](ZORVYQ_VOICE_FAILURE_DIAGNOSIS.md)
- [Voice interaction and acceptance](ZORVYQ_VOICE_INTERACTION.md)
- [Task manager and reminders](ZORVYQ_TASK_MANAGER.md)
- [Operation lifecycle and acceptance](ZORVYQ_LIVE_OPERATIONS_REPAIR.md)

The owner must verify actual audible playback, recognition accuracy, Wayland interaction, desktop notification support and live approved command execution. Capture retains the existing exact ALSA device and English tiny.en model. Early stop discards incomplete capture. No output-device chooser is available in the current backend. Reminder delivery requires the application to run; a crash after a persistent claim can suppress that reminder. Command reports stay session-only unless explicitly exported. AI analysis remains optional and unverified. No required speech dependency is missing from the inspected configuration, so no download/installation approval is currently needed.
