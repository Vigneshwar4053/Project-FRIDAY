# Persistent dashboard cards

## YOUR LAST 3 ACTIVITIES

Uses the dedicated activity database: `kind=application AND state=completed`, ordered by normalized UTC end timestamp descending, then stable hashed event ID descending, `LIMIT 3`. Browser details are attached to a separate browser timeline so overlapping browser observations are not displayed as another completed computer activity. Current, idle-only, unknown and interrupted activity do not enter the card. Ingestion reconciles source-event idle corrections and suppresses replay duplicates.

Each item shows application name, optional owner-associated project/domain, end timestamp, known active seconds, category and details/resume action. Zero, one or two records produce zero, one or two entries. Empty text:

> No recent activity recorded. Enable activity monitoring to start building your local history.

No examples are seeded into the owner database. The persistent query runs on dashboard opening and source revisions, not only in widget state. Storage survives desktop restarts and reboot; physical reboot acceptance remains an owner step.

VS Code resume uses `Projects.validate` and `Projects.open`, verifies an existing approved direct-child directory, asks confirmation and opens that exact directory. A project can be associated intentionally from Activity History. No project is guessed from a window title. Firefox browser-detail resume is available only for a retained, revalidated sanitized URL and only after a click. Domain-only records have no invented target. Terminal provides details only: no command replay or shell history restoration.

## RECENTLY COMPLETED TASKS

Uses existing Phase 2C `TaskStore.recent_completed()`, not the activity database. Selects only `Completed` with a real completion timestamp, ordered chronologically using UTC seconds and fractional seconds descending, then stable task ID descending (without losing sub-millisecond precision), at most three. This respects mixed timezone offsets in legacy timestamps. A partial expression index supports the query without replacing the task table.

Shows title, completion time, optional project and View task. The action opens My Tasks filtered to the title, preserving its existing editing/confirmation behavior. Reopened and deleted tasks disappear on task-panel refresh, and dashboard opening queries persisted state anew. Empty state: No completed tasks yet. Existing Phase 2C database shape and records are retained.

## Existing recent work

Inventory found three approved recent-work launch records and zero stored tasks (counts only; task titles were not inspected). Existing `RecentWorkQueue` verifies stored launch descriptors and existing `Projects` validates paths. Those records have launch timestamps but no reliable completion timestamps or durations. They remain in the existing recent-work area with the existing approved launcher; they are not misrepresented as completed observed activities or copied into another tracker. Recent launches and completed computer activity remain distinct.
