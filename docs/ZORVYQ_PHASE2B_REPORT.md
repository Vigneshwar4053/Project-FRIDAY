# Phase 2B report — 2026-10-31

**ZORVYQ — Zero-cloud Orchestrated Reasoning, Your Qualified Intelligence.**
Checkout: `/home/vigneshwar/Projects/zorvyq`. Branch: `feature/voice-foundation`.
This is an incremental extension of the existing assistant and desktop, not a rewrite.

## Preservation and diagnosis

The requested `git status --short`, branch, diff-stat and diff-check inventories ran
before implementation. The starting tree already contained substantial Phase 1/2A
tracked and untracked work. All 76 starting work files were archived with SHA-256
hashes and a binary diff in ignored `data/migration/phase2b/`. No starting file was
removed. No destructive Git command, commit, push or repository rename was performed.
Owner `.env`, knowledge bodies, models, local databases, POSIX symbols and startup
entries were preserved. Only explicitly approved read-only model metadata was
requested from local Ollama; no inference ran.

Confirmed blockers: ChromaDB is absent; the old cybersecurity controls permitted an
incompatible specialist+RAG selection; several distinct failures had generic UI
presentation. Approved read-only SQLite metadata still verifies **20 sources and 312
indexed chunk records**. This is not a live Chroma integrity certification. The
reported Wayland focus warning could not be correlated with a lost owner submission;
o backend/warning suppression change was made. See the
[failure diagnosis](ZORVYQ_CYBERSECURITY_FAILURE_DIAGNOSIS.md).

## Checkpoint outcomes

| Checkpoint | Implemented result | Evidence / outstanding boundary |
| --- | --- | --- |
| 2B-1 | Protected checkpoint, request-lifecycle diagnosis, safe fixed failure categories | 22 initial focused tests; physical Wayland correlation unconfirmed |
| 2B-2 | Both exact model identities in AI Chat; composer Short/Medium/Deep Analysis; persisted selections; controls freeze during work | 70 early focused tests; actual model output quality remains owner acceptance |
| 2B-3 | Separate Specialist Chat and Approved Knowledge; source-verification labels; stage progress and expandable safe status | Qwen RAG guard/authorization/schema/citations retained; Chroma installation gate remains |
| 2B-4 | Immutable plans, reviewed registry, one-use permission, sequential scheduler, bounded command runner, parser/collector/reporting | 17 initial synthetic engine tests; no generic shell or elevation |
| 2B-5 | Eight initial bounded adapters: health, local network overview, authorized discovery, security overview, process monitor, logs, storage, developer environment | Experimental; partial metrics and missing tools reported; no real diagnostic execution accepted |
| 2B-6 | Separate System Operations and Cybersecurity Operations cards, details, dry-run, exact approval, console, cancellation and explicit export | Offscreen tests; physical owner execution pending |
| 2B-7 | Bounded read-only Full System Diagnosis using existing stages | Excludes discovery/repairs/stress tests; synthetic orchestration only |
| 2B-8 | Slow-laptop investigation card, observed thresholds and separately labeled evidence-based hypotheses | Snapshot-only foundation; historical trends/dynamic expansion unavailable |
| 2B-9 | Registry-only unavailable future hardware/OS/network/developer/advanced/maintenance modules | No fake executable implementations or automatic privileged activation |
| 2B-10 | Optional selected-model analysis of numeric observations, strict schema/references; deterministic report retained on failure | Mocked analysis; generated interpretations remain unverified hypotheses |
| 2B-11 | Resource limits, cancellation/group cleanup, output/schema/privacy/permission tests and regression | 1,819 tests pass; no real scans/models/audio/apps launched for acceptance |
| 2B-12 | Architecture, failure diagnosis/repair, model modes, operation-engine, system-diagnosis and this report | Owner manual steps and limitations recorded |

## Exit behavior requested by owner

Normal desktop generation and Nomic requests use zero keep-alive. Shutdown now runs
cleanup on a worker: it cancels owned operation processes, denies unfinished permission
requests, waits for bounded in-flight generation, and releases unchanged app-created
model residency leases before closing service resources. No forced QThread termination
is used. Pre-existing/changed/unknown shared model residencies are not silently evicted;
AI Models retains explicit warned unload. The same-name foreign-model case is refused
before a request can reuse it and then unload it automatically.

**ZORVYQ stops models it can safely identify as its own; it does not stop the shared
Ollama daemon or unrelated clients.** Ollama exposes no complete client-ownership API,
so external races and crashes remain limitations. A failed unload is unconfirmed,
not reported successful. See [model residency details](ZORVYQ_MODEL_MODES.md).

## Verification performed

- Final targeted acceptance: **102 tests passed** in 2.909 seconds.
  `/tmp/zorvyq-2b-acceptance-final.log`.
- Final full regression: **1,819 tests passed** in 16.819 seconds.
  `/tmp/zorvyq-2b-final-complete.log`.
- The first full sandbox run showed the known four browser IPC PermissionErrors with
  four paired failures. Approved reruns with local Unix-socket access passed.
- `git diff --check` passed.
- Tests cover model/depth persistence and selection, unavailable provider/specialist,
  incompatible thinking parameters, no auto-routing, RAG/citation regression, focus /
  Enter / Shift+Enter / Send, worker responsiveness and clean shutdown. Engine tests
  cover registry/allowlisting, scope/authorization, dry-run, denial, single-use tokens,
  timeout, cancellation, output limits, partial failures, numeric analysis, redaction,
  explicit safe export and unavailable future modules. Synthetic `/proc` counters and
  directory fixtures exercise collectors. Project collectors use no-follow directory
  descriptors to prevent a validated directory being swapped for an escaping symlink.
- Inference, operation subprocesses and scan execution are mocked. Real pipe objects
  carry synthetic bytes to test bounded subprocess transport; no actual diagnostic
  utility, Nmap, private file content, VS Code, microphone or speech playback was used.
  The existing GUI metadata probe remains bounded/read-only; no operation starts at
  application launch.

Automated verification is not owner-operated hardware, Wayland, live inference,
retrieval or network acceptance. Capability/card states remain experimental or
available, not WORKING merely because code exists. Raw operation reports and chat
are session-only. Settings persist locally; report export requires a new owner-chosen
file. No data is uploaded to a cloud service.

## Remaining approval gates and limits

1. **Live RAG remains blocked by the absent ChromaDB dependency.** Review compatibility
   with the preserved environment and pinned requirements before approving an install.
   No package or alternative environment was silently created.
2. **Physical/live acceptance remains owner-operated.** Foundation-Sec may produce
   incorrect facts or unsupported JSON; invalid responses are withheld. Specialist
   RAG and automatic routing remain blocked pending separate acceptance/review.
3. **Diagnostic modules are bounded first versions.** No GPU/SMART/RAM-fault health
   certification, recursive private-directory sizing, raw private-log analysis,
   authentication-failure counting, historical trend tracking, automatic repair or
   dynamic model-defined follow-up operations is implemented.
4. **Startup is unchanged.** The previously identified stale installed launcher and
   legacy `~/.config/autostart/friday.desktop` still need the separate approvals
   documented in [startup migration](ZORVYQ_STARTUP_MIGRATION.md). No unrelated terminal
   setting, service or launcher was changed. No GitHub change is included.
5. **Privileged/state-changing/destructive operation classes are denied.** Installing
   tools, changing firewall/SSH, updating packages, cleanup, backups/restores, disk
   repair and rootkit/stress tooling need individual design and approval.

## Exact manual launch and acceptance

Use Ubuntu Run Application with:

```text
/home/vigneshwar/Projects/zorvyq/bin/zorvyq
```

It uses the existing project `.venv` and Qt without manual activation or a terminal.
The installed Applications launcher still needs the prior approved path repair.

1. Confirm the dashboard opens without inference, diagnostics, recording, scans or
   application reopening. Check greeting, recent-work and existing desktop features.
2. In AI Chat, switch Qwen/Foundation-Sec, try Short/Medium/Deep, request explicit detail,
   confirm controls freeze during work and preferences restore after restart.
3. In Cybersecurity, test Specialist Chat, then Approved Knowledge. Inspect technical
   failure categories and source-verification labeling. Resolve the dependency gate
   before claiming live RAG success. Deny/allow an exact request and inspect citations
   when ready. Repeat typing/Enter/Send under the actual Wayland session.
4. Preview and approve a local System Health operation; inspect measured metrics and
   NOT CHECKED sensors. Try the other read-only cards, Full System Diagnosis and the
   slow-laptop investigator. Confirm no repair executes and the console stays responsive.
5. Cancel an operation and inspect its partial report. Optionally run AI analysis;
   an Ollama error must leave measured results available. Review and export a new file.
6. Discovery is an explicitly authorized isolated-lab test only. Review target, purpose,
   exact argv and limits before Run. Verify public/oversized scope denial and Cancel.
7. Close during a diagnostic, then during bounded generation; verify orderly shutdown.
   Inspect Ollama residency afterward: app-owned models should unload; unconfirmed
   unrelated workloads and the shared daemon should remain unaffected.
8. Separately approve installed-launcher repair and actual login migration only after
   GUI acceptance. Verify ordinary Ubuntu Terminal behavior remains unchanged.

Detailed guides: [architecture](ZORVYQ_PHASE2B_ARCHITECTURE.md),
[operations](ZORVYQ_OPERATION_ENGINE.md), [cybersecurity](ZORVYQ_CYBERSECURITY_REPAIR.md),
[model modes](ZORVYQ_MODEL_MODES.md), [diagnosis](ZORVYQ_SYSTEM_DIAGNOSIS.md).
