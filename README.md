# ZORVYQ — Local AI Assistant

**Zero-cloud Orchestrated Reasoning, Your Qualified Intelligence.**

ZORVYQ adds a native Ubuntu desktop to the existing local assistant. The public
`zorvyq` package delegates to the established `friday` services. Source approvals,
verified citations, native synchronization and local data retain their identities.

Launch the desktop with `bin/zorvyq` from this checkout, or `zorvyq` after local
launcher installation. No activated shell environment or visible terminal is needed.

## Desktop setup

Keep the existing `.venv`. Qt Widgets requires **PySide6-Essentials 6.10+**, which
supports this checkout’s Python 3.14. Installation is a separate owner-approved
large dependency operation:

```bash
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python scripts/install_zorvyq_desktop.py
.venv/bin/python scripts/verify_zorvyq_launcher.py --desktop ~/.local/share/applications/com.zorvyq.ZORVYQ.desktop
```

Then select **ZORVYQ** in Ubuntu Applications. The installer writes only local
launcher/icon metadata; it does not install dependencies, start models, or move data.
Use `--prefix /tmp/zorvyq-install` for an isolated launcher installation check.

The Dashboard, AI Chat, Cybersecurity, Knowledge, Desktop Tools, Voice, AI Models,
Activity, Settings and About pages expose actual subsystem metadata. Missing Ollama
or RAG dependencies leave the window usable. No inference starts at launch.

Qwen3:4b remains the default. Foundation-Sec supports **experimental manual chat**;
specialist RAG and automatic routing remain blocked pending owner acceptance. Conflicting resident
models block generation; no unrelated model is automatically evicted. Unloading
requires explicit warning approval because Ollama cannot identify external clients.

Chat widgets are bounded session-only views; questions and answers are not persisted
or automatically reused as model history. Knowledge uses the original exact-scope,
allow-once authorization path and citation validation. The explorer reads approved
metadata, never document text or live embeddings. SQLite index counts do not assert
current Chroma integrity; authorized retrieval performs the existing full checks.

Voice output is explicit and device dependent. Microphone activation and transcript
review are separate confirmations. Audio is temporary. No answer is automatically
spoken. Protected desktop operations retain the existing owner verifier and cooldown through
a hidden passphrase dialog, followed by exact-operation approval. Startup and inventory
checks never read credentials. All tool actions still use the existing gateway.

Answer length (Short by default), installed voice settings and hidden-project choice
persist locally. The dashboard offers real recent work, and “open VS Code” presents
a numbered chooser under `/home/vigneshwar/Projects`. Accepted launches use the
existing persistent recent-work store. Theme settings remain session only.
Startup performs bounded local metadata checks; no model
inference, microphone, browser session, network scan or document retrieval starts.
The product is local-first; the name does not prove every dependency or tool offline.
Browser and other approved network tools can connect externally when invoked.

## Compatibility and verification

The developer CLI remains available as `.venv/bin/python -m zorvyq.cli` and via the
legacy `.venv/bin/python -m friday.main`. Existing diagnostic scripts are preserved.
The detailed historical [CLI guide](docs/LEGACY_CLI_GUIDE.md) describes legacy commands
and phase results; its names and test counts are historical evidence.

```bash
.venv/bin/python -B -m unittest discover -s tests
```

See the [migration inventory](docs/ZORVYQ_PHASE2A_MIGRATION.md) and
[checkpoint report](docs/ZORVYQ_PHASE2A_REPORT.md) for historical validation and limits.
The [additional requirements report](docs/ZORVYQ_PHASE2A_ADDITIONAL_REPORT.md)
covers the current extension, tests and owner acceptance steps.
Native `libfriday_sync.so`, `data/friday.db`, XDG voice settings, Chroma collection IDs
and provenance artifacts remain unchanged. Do not rename these identifiers manually.

The current repository remains [Project-FRIDAY](https://github.com/Vigneshwar4053/Project-FRIDAY).
The remote rename to `Vigneshwar4053/ZORVYQ` requires separate explicit approval.
This checkout is now at `/home/vigneshwar/Projects/zorvyq`; the historical FRIDAY
directory is absent. The installed launcher still needs an approved path repair;
use this checkout's `bin/zorvyq` in the meantime. Login startup replacement needs
separate approval; see [startup migration](docs/ZORVYQ_STARTUP_MIGRATION.md).
Models and databases must never be duplicated or deleted as part
of branding.

## Phase 2B operating assistant

AI Chat now exposes manual Qwen/Foundation-Sec selection and Short, Medium and Deep
Analysis controls above the composer. Cybersecurity separates experimental Specialist
Chat from authorized Qwen Approved Knowledge and exposes precise safe failures.
System Operations and Cybersecurity Operations provide reviewed plans, one-time scope
approval, an embedded console, cancellation and session-only reports. Initial bounded
adapters and Full System Diagnosis remain experimental until owner acceptance.
Optional AI interpretation receives numeric observations only and cannot execute tools.
Closing waits for owned work and unloads unchanged app-created model residencies;
the shared Ollama daemon and unconfirmed foreign workloads remain untouched.

See the [Phase 2B report](docs/ZORVYQ_PHASE2B_REPORT.md) for 1,819 passing tests,
exact manual launch/verification, the unresolved ChromaDB installation gate and
unchanged startup-approval requirements. No live inference or diagnostic operation
was used to certify this checkpoint.

## Phase 2B-R RAG runtime repair

The desktop now reuses ChromaDB 1.5.9 from the existing
`data/intelligence/rag-env` through a read-only, network-denied vector worker.
Qt, exact knowledge authorization, Nomic/Qwen synchronization and citation validation
remain in the desktop process. No dependencies were installed or data reindexed.
The previous environment-selection blocker is addressed; live desktop retrieval
still needs owner acceptance. See the [runtime repair report](docs/ZORVYQ_PHASE2BR_RUNTIME_REPAIR.md)
for 1,841 passing tests, unchanged-store evidence and the acceptance checklist.

## Local digital awareness

The existing awareness engine now supports the isolated ActivityWatch runtime and a reviewed GNOME Wayland watcher, current observed activity, persistent completed history, custom website categories, permission-gated factual answers, and optional local aggregate summaries. Collection, login monitoring and independent background operation require separate opt-ins. GNOME and Firefox extensions must be activated by the owner. The existing GUI autostart is unchanged. See the [LIVE report](docs/ZORVYQ_PHASE2D_LIVE_REPORT.md), [setup guide](docs/ZORVYQ_ACTIVITYWATCH_INTEGRATION.md), and [privacy boundaries](docs/ZORVYQ_ACTIVITY_PRIVACY.md).
