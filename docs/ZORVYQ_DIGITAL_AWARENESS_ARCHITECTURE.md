> Current implementation: see [Phase 2D-LIVE report](ZORVYQ_PHASE2D_LIVE_REPORT.md) and [runtime integration](ZORVYQ_ACTIVITYWATCH_INTEGRATION.md). The description below is the historical Phase 2D baseline. LIVE adds the opt-in managed runtime/user service, three-second event polling, one-second GUI snapshot display, schema v5, custom categories and explicit status states.

# Digital awareness architecture — Phase 2D

The engine is an in-process, opt-in consumer of ActivityWatch, not a replacement desktop tracker. Importing it or starting the desktop with default preferences opens no ActivityWatch connection, watcher, extension, microphone or model.

## Components

- `zorvyq/awareness/store.py`: separate owner-only SQLite repository, migrations, bounded search, deterministic aggregates, corrections, deletion tombstones and explicit exports.
- `adapter.py`: read-only `/api/0/buckets/` and bucket events. Numeric `127.0.0.1:5600` only; no environment proxies, DNS endpoints, redirects, server-side query language or arbitrary LLM endpoints. Two-second socket timeout, 2 MB response limit, maximum 100 buckets, fewer than 512 events per request. Saturated responses fail closed rather than silently truncate totals.
- `monitor.py`: one worker and owner-only advisory lock per activity database. Polls at most once per 30 seconds while enabled. System samples at most once per minute. No event queue or unbounded accumulation. Temporary failures retry on the next interval; disabling never starts a watcher. GUI has its existing single-instance lock too.
- `privacy.py`: application and domain scopes, private browsing refusal, sensitive metadata exclusions, title filtering, URL minimization.
- `intelligence.py`: fixed query grammar, deterministic totals, existing expiring one-use operation permission tickets. No LLM SQL or unrestricted database handle.
- `desktop/awareness.py`: async bounded history/dashboard queries, real-record cards, intentional actions and consent controls. Settings and dashboard provide pause controls. Queries refresh at page opening, task changes and activity revisions; a one-second timer reads controller revision/status, not activity history or desktop state.

## Persistent storage

Uses the established desktop storage convention: beside `desktop.json` and the existing `tasks.sqlite3`, normally `~/.config/zorvyq/activity.sqlite3` (`XDG_CONFIG_HOME` supported by existing Preferences). Nothing is stored in the cybersecurity/RAG or My Tasks databases. SQLite schema versions 1–3 migrate transactionally; future versions are refused. The file uses 0600, rejects symlinks, checks ownership and performs a quick integrity check at open. New parent directories use 0700; existing shared directories are not chmodded. SQLite journals inherit restrictive database permissions.

Tables: `activities`, `preferences`, `system_metrics`, `monitoring_events`, `deleted_events`. Browser details share the normalized activity table with `kind=browser`; this avoids a second competing timeline. Activities have stable hashed IDs, normalized UTC start/end, measured interval duration, category and optional minimized metadata. Indexes cover start, end/ID, application, category and source. Source hashes allow corrected idle intervals to replace earlier intervals; deletion tombstones prevent reimport from the same source. No task contents are copied here.

Retention defaults to 30 days for activity and seven days for metrics. Activity retention supports 7, 30, 90 or custom 1–3650 days. Cleanup runs hourly during authorized collection; with collection disabled no background cleanup service runs. Clear history removes activity, metrics and diagnostic state records, retaining only deletion hashes until retention cleanup to prevent reimport. Export creates a new 0600 JSON file with selected minimized records, at most 1000; there is no upload.

## Event semantics

A successor foreground event proves an observed interval ended. The current final heartbeat stays open; stale final observations may be stored as interrupted, excluded from completed cards and completed totals. Unknown or unapproved applications produce no invented usage. Observed timestamps and durations are never filled from launch timestamps or wall time. Active intervals intersect `not-afk` evidence; overlapping contradictory idle evidence fails closed. Missing idle/foreground buckets fail closed. Exactly one foreground and one idle stream are required; multiple sources need a future explicit selector and currently report unavailable.

The manager reconciles changes in idle evidence without replaying duplicate source events. There is no collection across pause, process downtime, reboot or permission changes: a fresh boundary applies. A poll retrieves a bounded one-hour overlap, so long disconnections or events starting before that horizon may be omitted. This is intentionally incomplete history, never a claim of continuous coverage. ActivityWatch idle classification is an estimate and can be corrected retrospectively; source corrections are reconciled while in the overlap window. ZORVYQ does not invent input, focus or presence evidence.

System metrics reuse `ResourceMonitor` and System Operations disk/read collectors: CPU counters, RAM, process RSS, load, disk and uptime. No process command lines, network scans, packet inspection, screenshots or model loading. Actual continuous resource overhead has not been benchmarked: all monitor tests use fixtures.

## Lifecycle and boundaries

Only opted-in ingestion starts with ZORVYQ; no startup entry, system service or existing autostart configuration is modified. Collection is bounded to the application lifetime. Pausing/disabling serializes against writes and stops the consumer; outstanding bounded HTTP reads are discarded after a privacy change. Shutdown joins the worker with a finite wait. External ActivityWatch/Firefox watchers are independently owner-managed: ZORVQ's pause stops its own ingestion, not those external processes. Their upstream collection, privacy configuration, history deletion and retention must be managed separately.
