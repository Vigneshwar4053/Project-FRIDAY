# Project ZORVYQ — Phase 2A checkpoint

## Delivered product

**ZORVYQ — Zero-cloud Orchestrated Reasoning, Your Qualified Intelligence.**

A native PySide6 Qt Widgets desktop now wraps the existing assistant services.
The normal entry point is `zorvyq` or Ubuntu Applications → **ZORVYQ**. Both use
this checkout's existing `.venv` automatically; the desktop entry has
`Terminal=false`. The window title is **ZORVYQ — Local AI Assistant**.

Installed user-local artifacts:

- `~/.local/bin/zorvyq`
- `~/.local/share/applications/com.zorvyq.ZORVYQ.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/com.zorvyq.ZORVYQ.svg`

The launcher targets `/home/vigneshwar/Projects/FRIDAY/bin/zorvyq`. Moving the
checkout requires reinstalling these artifacts. The old directory is retained.
Qt Widgets essentials 6.11.3 and Shiboken 6.11.3 were installed into the existing
venv through the approval mechanism. No Python environment was recreated.

## Architecture and security boundaries

```text
Qt Widgets (zorvyq.desktop.app)
  → serialized service worker (zorvyq.services.Controller)
    → FridayAssistant / ModelManager / native synchronization
    → original RAG orchestrator and exact KnowledgeAuthorization
    → original ToolManager and desktop/filesystem approval adapters
    → original voice capture, transcription and speech backends
```

The application never executes model-generated shell commands. Its public facade
is `zorvyq`; existing `friday.*` imports, developer CLI, native symbols, source
IDs, collection names, SQLite schemas and stored record formats remain compatible.
The original README is preserved byte-for-byte in `docs/LEGACY_CLI_GUIDE.md`.
Historical reports and provenance artifacts retain their original names.

A queued GUI-thread dialog bridges each exact RAG approval request. It displays
the actual eligible-source count, full detailed scope and original authorization
fingerprint, with Deny as the default. Allow Once has the same scope and lifetime
as the CLI decision. No persistent or broader knowledge grant is added. RAG still
performs its original backend, embedding, evidence, source-revision and citation
validation. Only verified RAG results receive expandable source cards; citation
text and source URLs are never rebranded or synthesized.

Protected desktop actions use the original OwnerAuthenticator, Argon2 provider,
request validation and failure cooldown. Only its hidden-input transport changes
to a masked Qt dialog. Credential configuration remains untouched. Construction,
startup, metadata inventory and the live general-question check did not read
`.env`. An explicit future protected operation invokes the existing verifier;
there is no cached success or authentication bypass. Generic controller clients
without a credential-dialog adapter fail closed.

All desktop chat calls are private turns: no conversation SQLite session is
created, no questions/evidence/answers are persisted, and model job bodies are
cleared. The UI keeps at most 40 message widgets per workspace for the current
session. These displayed turns are not automatically reused as model history.
No telemetry or analytics is added. Settings are session-only.

## Desktop surfaces and evidence

| Surface | Implemented behavior | Current verification boundary |
| --- | --- | --- |
| Dashboard | Dynamic model, knowledge, voice, tool and privacy cards; real page shortcuts | Real metadata and native window smoke check |
| AI Chat | Separate message viewport, multiline composer, Enter/Shift+Enter, Markdown/code formatting, copy, progress, elapsed time | Qt tests and one real Qwen controller inference |
| Cybersecurity | Explicit Approved Knowledge control, exact source approval, verified source cards, safe failure categories | Existing RAG regressions; no new live retrieval because ChromaDB is absent |
| Knowledge | Read-only approved titles/topics, URLs, revisions, source IDs and indexed-chunk counts; metadata filtering | Real SQLite metadata inspection; no document-body selection or embedding |
| Desktop Tools | All 29 actually registered tools, descriptions, risk/permission and unverified live-execution status | Real production registry; physical app/browser acceptance not repeated |
| Voice | Explicit speech enable/action, one-shot capture confirmation, original local backend, transcript review, separate Send | Original voice tests and new UI transport tests; physical audio remains experimental |
| AI Models | Actual installed/resident metadata, sizes/VRAM/context when supplied, details, refresh, warned exact unload | Real `/api/tags` and `/api/ps`; unload-control tests |
| Activity | Current request/elapsed/error, shared residency, GUI RSS, system RAM, sampled CPU and load | Bounded Linux metadata sampling; no content telemetry |
| Settings | Dark/light theme, larger text, polling/resource saving, existing adaptive profiles, documented fixed policies | Session-only; no credential/configuration rewrite |
| About | Central feature IDs, descriptions, implementation references, statuses, permissions, actions and evidence | Missing dependencies resolve to UNAVAILABLE; mocked tests never imply WORKING |

Cancellation is visibly disabled: the existing synchronous provider has no safe
request-cancellation API. Closing an active request asks the owner to wait for
bounded completion; workers are not forcibly terminated. Shutdown closes the
existing owned browser/computer adapters and synchronization resources.

Manual preload is visibly unavailable. Explicit questions load the existing
Qwen model; no specialist model is preloaded or routed. Speech is never automatic,
the microphone is never activated at startup, and no browser session, scan or
approved-document retrieval starts automatically. The dashboard remains usable
when Ollama is disconnected.

## Actual local inventory and residency policy

Read-only current inventory: **20 approved active sources, 312 indexed chunk
records**. The UI derives these from approved metadata plus current SQLite
revisions and index records. This is not a claim that all vector contents were
reverified at startup. Existing authorized retrieval retains that responsibility.

The actual local Ollama metadata returned Qwen3:4b, Nomic Embed Text v1.5,
Foundation-Sec and an additional llamacpp identity. It returned two Foundation-Sec
entries with the same visible name; the desktop displays service metadata rather
than assuming an expected three-row inventory. The initial resident list was empty.
Foundation-Sec remains **specialist candidate — integration pending**.

General desktop generation checks `/api/ps` while ModelManager holds the native
inference gate and refuses other resident model identities. It requests
`keep_alive=0` for its own generation. The existing Nomic embedding gate and
post-embedding residency checks are preserved. No foreign model is automatically
evicted. Manual unload is serialized, checks current residency, and requires an
explicit warning: Ollama cannot establish another client's ownership or busy state.
An external client can race any service snapshot; the native mutex coordinates this
application, not every Ollama client. No process or unrelated workload is killed.

## Verification results

- Initial protected working tree: 11 modified tracked files and 15 untracked files.
  All 26 were archived with SHA-256 hashes and a binary diff under the ignored,
  local `data/migration/phase2a/` directory before implementation.
- Only three pre-existing work files received additional edits: `friday/main.py`
  (optional authenticator injection and CLI identity), `friday/providers/ollama.py`
  (opt-in zero keep-alive), and `friday/intelligence/rag.py` (optional approval
  factory). Their original Phase 1F/1G changes remain present. The other 23 files
  match the initial recovery hashes.
- Sandbox baseline: 1,723 existing tests; four browser IPC fixtures produced
  PermissionErrors and paired failures. With approved local IPC access, all
  1,723 existing tests passed after identity compatibility fixes.
- New desktop/controller coverage: 22 tests cover worker responsiveness, busy
  exclusion, scope deny/allow-once, masked credential input, original authenticator
  composition without credential reads, private jobs, no persistent chat,
  legacy/new command aliases, residency refusal, warned exact unload and blocked
  Markdown resource loads. These are automated tests, not owner audio acceptance.
- Full final suite: **1,745 tests passed**. See the local `regression-tests.log`.
- Native GUI smoke: visible window, all ten pages, no startup inference, proper
  title, maximizing, restoring/resizing to 760×580 and clean shutdown all passed.
- Launcher: actual interpreter, executable wrapper, icon, public package, desktop
  metadata and `desktop-file-validate` checks passed.
- One real general question used Qwen3:4b through the native POSIX mutex. It returned
  a nonempty answer in 87 seconds with one model invocation, no persistent memory,
  no retained job messages/result, and an empty resident-model list afterward.
  No specialist inference, speech, microphone or live private-document request ran.
- `git diff --check` passed. No commit, push, force push, destructive Git operation,
  database deletion, model deletion or directory move was performed.

The default host GTK theme plugin crashed on this machine because its GNOME
GSettings schema lacked `antialiasing`. The normal entry point now selects Qt's
generic theme and Fusion style for this application only. Native Wayland startup
and resizing then passed. Host-portal registration warnings remain environmental;
they did not prevent the tested window from opening or functioning.

Qt documentation supporting the compatibility/framework choice:
[Python 3.14 support](https://doc.qt.io/qtforpython-6.10/release_notes/pyside6_release_notes.html),
[QGuiApplication theme options](https://doc.qt.io/qt-6/qguiapplication.html),
[Fusion style](https://doc.qt.io/qt-6/qapplication.html).

## Outstanding external checkpoints

1. **Live RAG dependency:** ChromaDB is absent from this Python 3.14 venv. No
   dependency installation or environment replacement was silently attempted.
   Existing pinned RAG requirements need a separately approved compatibility
   review before a new live RAG acceptance test. The GUI correctly reports this.
2. **Owner device acceptance:** audible offline speech, microphone recognition,
   native application handoffs and browser/compositor visibility need owner-operated
   checks. Their capabilities are not labeled fully working merely from mocks.
3. **GitHub rename:** origin remains
   `https://github.com/Vigneshwar4053/Project-FRIDAY.git`. Public API preflight
   confirmed that repository and returned 404 for `Vigneshwar4053/ZORVYQ` without
   authentication. A private repository cannot be excluded from that result.
   GitHub CLI/authenticated rename permission was unavailable. The exact proposed
   PATCH operation is documented in the migration inventory and requires separate
   explicit approval plus authenticated preflight. No remote operation was made.
4. **Directory move:** the active checkout remains `~/Projects/FRIDAY`.
   `~/Projects/ZORVYQ` is a separate reviewed checkpoint involving absolute paths,
   venv entry-point shebangs, persistence, native loading and installed launchers.

The remaining compatibility references are classified by file and line in
`docs/ZORVYQ_BRANDING_INVENTORY.json`. In particular, legacy recent-work summary
construction must remain byte-compatible: existing integrity validation reconstructs
those exact records. Only their trusted presentation is branded ZORVYQ. Source
citations, saved path names and historical evidence retain their actual names.

## Follow-on additional desktop requirements

This report's original validation and filesystem paths are historical. The current
extension, current lowercase checkout path, launcher repair finding, persistent
preferences/recent projects, manual specialist selection, Nmap adapter, 1,780-test
regression result and outstanding approvals are documented in
[ZORVYQ_PHASE2A_ADDITIONAL_REPORT.md](ZORVYQ_PHASE2A_ADDITIONAL_REPORT.md).
No new live inference/audio/network-scan acceptance is claimed by that extension.
