> Phase 2D-LIVE (2026-11-10) supersedes the installation and watcher-setup status below. The verified release and reviewed GNOME watcher are now installed locally; an actual empty-server health check passed. Owner extension activation and live event acceptance remain pending. See [the LIVE report](ZORVYQ_PHASE2D_LIVE_REPORT.md) for current files, tests, privacy boundaries and exact owner steps. This report is retained as historical evidence.

# ZORVYQ Phase 2D implementation report

Date: 2026-11-03. Branch: `feature/voice-foundation`. No commit or push.

## Delivered checkpoints

| Checkpoint | Result |
| --- | --- |
| 2D-1 Inventory/preservation | Read architecture, Phase 2C tasks, recent-work validation, dashboard, operation permissions, voice review/Send flow, QThread worker pattern and unittest conventions. No AGENTS.md was found. Initial branch/status/diff-check recorded; extensive pre-existing tracked and untracked work preserved. Read-only schema/count inspection: zero tasks, three approved recent launches. |
| 2D-2 SQLite | Dedicated 0600 database beside desktop preferences; schema v3, safe incremental migrations, integrity check, UTC indexes, retention, source corrections, replay suppression, selected deletion, clear and selected export. |
| 2D-3 Dashboard | Prominent YOUR LAST 3 ACTIVITIES and RECENTLY COMPLETED TASKS, persistent queries and explicit actions. Existing launch-based recent work remains intact. Task timestamps sort with timezone and microsecond precision. |
| 2D-4 ActivityWatch | Bounded, loopback-only read adapter; malformed/unavailable/reconnect tests. Exact official stable release metadata verified. No installed executable or port-5600 listener verified. Download/install approval pending. |
| 2D-5 Manager | One bounded thread with database-level advisory lock; foreground switches, idle intersection, current/idle/unknown status, completion/interruption, correction reconciliation, privacy boundaries, pause/disable/shutdown and retry. No real collection enabled. |
| 2D-6 Browser | Optional Firefox event adapter with independent consent, positive domain scope, private-state checks, sensitive exclusions and URL minimization. No extension installed or browser profile read. Real compatibility pending. |
| 2D-7 Intelligence | Fixed query grammar, deterministic facts/totals and existing one-use exact-plan permissions. Push-to-talk uses existing reviewed transcript/Send route. Optional selected local model summary receives only numeric category totals after separate approval; no inference run in tests. |
| 2D-8 Frontend | Activity History sidebar page, async history queries, search/date/app/category filters, compact day-grouped rows, details, owner project/category association, privacy controls and source-backed monitoring status. |
| 2D-9 Tests | Synthetic backend and offscreen GUI tests plus full existing regression; see results below. |
| 2D-10 Report | Five required documents created, including explicit upstream privacy boundaries and owner acceptance gates. |

## Functional scope

Both dashboard cards query actual persistent records. No illustrative activities or tasks are seeded. No completed computer activities are imported from launches, since launches do not prove completion or duration. Browser detail rows do not double-count foreground Firefox in computer-activity cards. My Tasks retains its Phase 2C schema/records; only a bounded query and partial ordering index are added. Activity history persists on disk across restarts; no global startup/service change is needed for persistence.

Monitoring, browser collection, titles, URL retention and stored metrics all default OFF. A fresh responsive server alone is insufficient for ON: actual fresh foreground and idle evidence is required, with an additional Firefox source for browser ON. UI shows current approved application, idle or unknown state separately. Privacy changes create a new collection boundary; no pre-consent or downtime history is imported. Historical source corrections reconcile idle intervals rather than duplicating them. Deleted sources remain suppressed.

Activity queries supported: last three activities, yesterday's work, today's applications, programming duration, today's websites, studying duration, completed tasks today and project continuation. Studying needs an intentional category assignment; projects need explicit approved association. Missing data is reported, never guessed. Deterministic queries operate without a model. Optional model failure leaves facts intact. Task titles never enter model summaries.

## Validation results

- Targeted Phase 2D backend and offscreen UI suite: **32 tests passed**, using temporary SQLite stores, synthetic timestamps/events, mocked HTTP and disconnected GUI services.
- Phase 2C plus Phase 2D integration pass: **44 tests passed** before the final source-status refinement; the final full suite includes both.
- Full regression: **1894 tests passed** on the final implementation (final execution log: `/tmp/zorvyq-phase2d-regression.log`).
- `git diff --check`: passed.
- Python compilation checks: passed.
- Initial sandbox regression encountered existing headless managed-browser local IPC PermissionErrors. The approved out-of-sandbox rerun passed; no unrelated browser source changes were made to accommodate the sandbox.

Coverage includes local transport restrictions, finite timeouts, malformed responses, unavailable/reconnection, opt-in defaults/denial, switches/completion/current/unknown, idle exclusion and corrections, duplicates, separate browser consent/private-state/domain rules, URL/title filtering, schema migrations, permissions, retention, bounded/indexed queries, 0–6 activity ordering/ties/restart/deletion, completed-task ordering including sub-millisecond offsets/reopen/deletion/restart, single controller, metric opt-in, deterministic queries, one-use permission consumption, no unapproved model access, model-unavailable fallback and GUI refreshes.

Tests did not monitor owner applications, capture audio/screenshots/keystrokes, access actual browsing history, open Firefox/VS Code, install software/extensions or run live inference. Offscreen tests do not establish physical desktop, audio, live watcher compatibility or Ubuntu reboot acceptance. Continuous resource overhead is not benchmarked.

## Approval gates and limitations

1. ActivityWatch is **not verified installed or running**. Official v0.14.1 classic ZIP: **196,236,767 bytes**, exact source/hash and unpack-only plan in the integration document. An approval question was submitted; no installation authorization received at report time. No archive download occurred.
2. Classic `aw-watcher-window` does not support native GNOME Wayland tracking. A compatible watcher and Focused Window D-Bus GNOME extension need separate owner approval, version verification, upstream privacy filtering and real acceptance. Experimental upstream Tauri packaging is documented, not substituted automatically.
3. Firefox watcher installation, normal permission dialogs, upstream exclusion/filter configuration and browser opt-in remain owner-operated. No private-window permission should be granted. Actual watcher schemas and app identifiers must be checked on the owner session.
4. ZORVYQ pause/disable stops its own consumer. Independently running ActivityWatch/Firefox watchers must be stopped separately; their upstream history and richer URL/title retention are not controlled by this database. Consent dialogs disclose this.
5. One foreground and one idle source are supported. Ambiguous streams, event-limit saturation, authenticated APIs without supported credentials, missing private-state flags and stale sources fail closed. The bounded one-hour import overlap can omit long or disconnected work. No duration is invented for those gaps.
6. Retention cleanup occurs hourly while authorized collection is running. Disabling collection also stops that background maintenance; history can still be cleared explicitly.
7. Both cards have storage-level restart tests. A real GUI reopen/logout/reboot and physical resume/voice acceptance remain manual owner steps.

## Manual owner acceptance

1. Open ZORVYQ without enabling collection: verify both cards, truthful empty states, Activity History and Monitoring OFF. Reopen the application and verify existing completed tasks/recent launches remain.
2. Complete at least four real My Tasks items; verify only the latest three, then reopen/delete one and check immediate removal. Reopen ZORVYQ and later reboot to verify persistence.
3. Review installation proposal and upstream privacy behavior. Approve desired ActivityWatch installation and GNOME interfaces separately. Configure application allowlists and title suppression upstream before launching any watchers. Verify the real server stays loopback-only and native GNOME foreground/idle bucket schemas match the adapter.
4. Explicitly enable ZORVYQ activity monitoring. Switch between approved apps, then become idle. Confirm only source-completed active intervals appear, current/idle/unknown status is truthful, and missing evidence reports unavailable. Pause/disable and verify no new ZORVYQ records; stop independent watchers too if upstream capture must cease.
5. Open history; search and filter; inspect details; associate a real approved project. Intentionally resume through the existing project launcher and confirm the exact directory. Confirm Terminal never replays commands.
6. Only if desired, manually install/review the official Firefox watcher, leave private-window access disabled, configure upstream filters, approve exact domains and separately opt in. Verify excluded/private pages produce no ZORVYQ browser rows. Domain-only entries must not open invented URLs. Independently approve retained URLs before testing intentional resume.
7. Ask supported activity questions in chat and reviewed push-to-talk. Deny access and confirm no query/model runs. Allow once and compare facts with stored rows. Explicitly request the optional local aggregate summary only when desired.
8. Verify selected deletion/export and restrictive permissions, privacy revocation of titles/URLs, retention settings, app restart and real Ubuntu reboot persistence. Confirm autostart configuration, models, voice, tasks and cybersecurity knowledge remain intact.

## Preservation

No Git reset/clean, untracked-file deletion, database replacement, RAG reindex, model installation change, package installation, autostart modification, global service change, automatic extension installation, cloud upload, commit or push. Existing unrelated tracked changes were left in place. New production files are under `zorvyq/awareness` and `zorvyq/desktop/awareness.py`; integration edits are confined to the existing desktop app/tasks, TaskStore and optional local-summary service.
