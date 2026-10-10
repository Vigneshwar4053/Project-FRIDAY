# Phase 7A Q persistence correction

Current immediate-repeat behavior: the [desktop repair](PHASE_7A_DESKTOP_REPAIR.md)
adds a short duplicate guard. Use explicit `retry open files`/`retry open downloads`
when testing repeated accepted launches; suppression does not refresh Q or consume
budget. The original investigation below remains historical context.

## Root cause and full request trace

The reproduced behavior was the original queue outcome policy, not lost SQLite
writes. `DesktopPermissionAdapter.execute` gated recording with
`result['status'] == 'launch_accepted'`. Ubuntu Files remained running after the
executor's one-second wait, which returns `launch_outcome_unverified`. That status
failed the gate: `RecentWorkQueue.record` and `MemoryManager.record_recent_work`
were never called. Show Q correctly read an empty table.

The complete typed request flow is:

1. `open files` deterministically resolves through DesktopIntentResolver/ToolRouter
   to `launch_application`, with fixed `application_id='files'`.
2. FridayAssistant's desktop branch forwards `persist=True` as
   `ToolManager.execute(..., persist_metadata=True)`. It bypasses model construction
   and conversational history persistence.
3. ToolManager validates the fixed schema and risk policy. The desktop adapter
   prepares the verified application lease and requests exact-operation typed
   approval. Only `FolderDecision.ALLOW_ONCE` authorizes it. Named executable and
   held descriptors are revalidated after approval.
4. DesktopExecutor uses the approved fixed argv and pinned ELF descriptor without
   a shell. Popen's successful process creation followed by a bounded-wait timeout
   yields `launch_outcome_unverified`: process started, GUI visibility unknown.
5. Previously that result skipped Q recording. Now either `launch_accepted` or
   `launch_outcome_unverified` qualifies for Q, when persistence is enabled.
6. RecentWorkQueue builds a fixed application-only descriptor. For Files,
   `project_id`, `path`, and directory identity are absent by design. The outcome
   is passed explicitly and validated. Q does not require a project; the separate
   project-session branch still does.
7. MemoryManager atomically upserts `recent_work` by activity key and trims it to
   three entries in one SQLite transaction. Repeats retain their UUID, refresh
   timestamp/outcome and move to first place. A failed transaction rolls back.
8. `show Q` resolves to `show_recent_work`, validates stored metadata, and reads
   `MemoryManager.recent_work()` from the same database connection. The CLI passes
   its single configured MemoryManager to the desktop adapter, which uses it for
   both record and retrieval. The data remains after the CLI closes/reopens it.

Typed input is not affected by voice exclusions. Confirmed voice input explicitly
uses `persist=False`; both accepted outcome types still suppress Q persistence for
those turns. Queue rows are persistent SQLite data, not session-local menu state.
Only the numbered menu's stable-ID snapshot is session-local.

Write exceptions were already caught with `recent_work_recorded=False` plus
`Recent work could not be saved.` in the displayed result. Private SQLite details
are not disclosed. The regression forces eviction failure with a SQLite trigger
and confirms both the warning and rollback. The observed reproduction had no
write exception: it never reached the write.

## Files changed for this correction

- `friday/desktop/runtime.py`: broaden only the Q outcome gate and pass actual outcome.
- `friday/desktop/recent.py`: validate accepted outcomes, version-2 factual summaries,
  honest status/resume display and backwards-compatible version-1 decoding.
- `friday/memory/database.py`: constrained launch-status column and idempotent migration.
- `friday/memory/manager.py`: explicit-column insert/upsert with refreshed launch status.
- `tests/test_recent_work.py`: live-sequence and storage/approval regression tests;
  replace the obsolete test expectation that running launches cannot enter Q.
- `README.md`, `docs/PHASE_7A_DESKTOP.md`, `docs/PHASE_7A_ENHANCEMENT.md`, this report:
  align documentation with the corrected policy.

Routing, tool risk policy, assistant provenance, CLI database composition, project
history, executable registry and speech infrastructure were inspected and left
unchanged. No unrelated functionality or release version was changed.

## SQLite and launch-outcome policy

`recent_work.launch_status` accepts only `launch_accepted` and
`launch_outcome_unverified`. Fresh databases create it directly. Existing Phase
7A databases receive an idempotent ALTER migration with default `launch_accepted`,
matching the only outcome that could previously populate that table. IDs, targets,
order and timestamps survive. Version-1 descriptors remain validated and resumable;
the menu reconstructs accurate summaries instead of displaying old “Opened” text.
New records use version-2 factual process-start summaries. Repeated launches update
status along with descriptor/summary, retaining the stable ID. Separate database
paths remain separate queues; no second database or storage system is introduced.

An authorized initial native process start can be recorded even when it keeps
running beyond the bounded wait. Neither a zero exit nor a running process proves
window visibility or completed work. Both outcomes display:

```text
[1] Ubuntu Files
    Summary: FRIDAY started Ubuntu Files.
    Status: Window not verified.
    Resume: Open Ubuntu Files.
```

Denied launches, failed/nonzero launches, spawn exceptions, unavailable/untrusted
executables and voice-derived requests remain excluded. There is no background
monitoring or later upgrade of the saved observation. Yesterday-project lookup
retains its preexisting stricter eligibility policy; this change only affects Q.
Every resume still revalidates stored targets and applications and requests fresh
exact-operation typed approval. There are no persistent desktop execution grants,
filesystem bypasses, arbitrary commands, microphone activation or Snap trust changes.

## Verification

- `.venv/bin/python -B -m unittest discover -s tests`: **1,071 tests passed**.
- `make -C native/sync`: passed; already up to date.
- `git diff --check`: passed.

Ten added tests cover the exact Show Q → Open Files → typed Allow once → running
process → Show Q sequence; recording call/metadata; repeat ordering and outcome
refresh; restart with fresh denied resume approval; denied/failed Files requests;
voice exclusion; distinct CLI database paths; transaction rollback/reporting;
legacy schema migration and safe resume; and invalid outcome rejection. Existing
headless tests retain target, executable, URL, terminal display and no-shell checks.
All GUI/audio execution is mocked. No real GUI launch, package installation,
release operation or Git mutation command was performed.

## Manual acceptance

From a normal local Ubuntu terminal on a host with the already-reviewed native
Ubuntu Files installation:

```bash
.venv/bin/python -B -m friday.main --adaptive
```

At the FRIDAY prompt, type:

```text
Show Q
open files
```

At the separate exact-operation prompt choose **1 — Allow once**, then type:

```text
show Q
```

Whether the initial result is accepted/zero-exit or running/window-unverified,
expect an Ubuntu Files entry with the factual summary and unverified status above.
Neither output is proof that a GUI window appeared; observe the GUI separately.
Existing entries need not be cleared to test this.

Launch another approved activity to create a second entry, then repeat:

```text
open files
```

Allow once, then `Show Q`: Ubuntu Files must be first, with no duplicate. Quit and
restart using the same command/configured database path. Show Q must retain the
entry. Type its displayed number, then **3 — Deny** at the new permission prompt:
no resume should occur. Show Q again, select its displayed number, then **1 — Allow
once** to explicitly resume. Every resume must ask again.

For denied-launch exclusion, note Q before `open files`, deny with **3**, then Show
Q: entries/order/timestamps must not refresh. Failed launches, migration, database
path isolation and write rollback are covered safely by headless tests; do not
break the real installation or change valuable data to reproduce them. The
existing four-process limit requires a restart after four launches. If the native
installation is unavailable/untrusted, that safe refusal must not create a Q entry.
