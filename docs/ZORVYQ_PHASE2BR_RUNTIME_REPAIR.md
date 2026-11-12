# Phase 2B-R — desktop RAG runtime repair and acceptance preparation

Date: 2026-10-31. Checkout: `/home/vigneshwar/Projects/zorvyq`.
Branch: `feature/voice-foundation`.

## Confirmed runtime issue and read-only findings

The desktop was opening the existing RAG pipeline from `.venv`, whose Python has no
ChromaDB distribution. The original isolated environment was present and reusable:

| Environment | Interpreter observed | ChromaDB | Qt |
| --- | --- | --- | --- |
| `.venv` | CPython 3.14.4 | Absent | Existing PySide6 desktop retained |
| `data/intelligence/rag-env` | CPython 3.14.4 | **1.5.9** | PySide6 absent; not required in the vector worker |

Both interpreters report their current checkout prefixes correctly. Historical
FRIDAY paths in venv creation metadata were not rewritten; executing the fixed
existing RAG interpreter works without shell activation.

The original live backend derives all paths from the current project root:

- Knowledge repository: `data/intelligence/phase1e/knowledge/knowledge.sqlite3`.
- Chroma persistence: `data/intelligence/phase1e/chroma/`.
- Approved corpus metadata: `docs/FRIDAY_PHASE1E_CORPUS.json`.
- Source scope/index manifest: the original fingerprint-pinned approval artifact.
- Embedding identity: `nomic-embed-text:v1.5`, original pinned revision, 768 dimensions,
  original query/document prefixes.

Read-only SQLite connections (`mode=ro&immutable=1`) observed **20 active knowledge
sources, 312 chunks and 312 indexed acknowledgements**. Chroma's existing SQLite
metadata contains the expected approved collection
`friday_474dc19543813c52cb4d4575f99e24c97eac2fb4c28d7ce3` and **312 embedding metadata
records**. These are metadata checks, not a vector search or semantic retrieval test.

The existing RAG interpreter passed an actual **import-only** probe with networking
denied and 1.5.9 asserted. Chroma imports and accepts `migrations='validate'`:

```json
{"version":"1.5.9","import_compatible":true,"index_opened":false,"network":"denied"}
```

No PersistentClient, collection or HNSW index was opened during this inspection.
No embedding, Qwen or Foundation-Sec inference ran. SHA-256 checks before/after the
repair and tests match for all six existing knowledge/Chroma store files, with no
added store files. No existing knowledge records were modified.

## Selected architecture

**Reuse only the original Chroma worker in the existing RAG environment.** A whole
RAG process bridge or installation of Chroma's dependency tree into Qt's environment
is unnecessary. The existing Chroma adapter already isolated its client in a worker;
the desktop now selects a narrowly constrained alternate transport for that worker.

```text
Qt one-time knowledge approval and serialized controller (.venv)
  → original RagOrchestrator / RetrievalService / KnowledgeRepository
  → original Nomic provider + parent native POSIX gate
  → CompatibleChromaIndex
      → private inherited pipes, bounded JSON, per-worker nonce and sequence
      → fixed rag-env Python and fixed vector worker script
      → original pinned Chroma worker, existing-only/read-only commands
  → original parent Qwen ModelManager + same native POSIX gate
  → original source-revision, structured claims and citation verification
  → verified answer / expandable source metadata / safe GUI status
```

The exact worker executable and entrypoint are:

```text
/home/vigneshwar/Projects/zorvyq/data/intelligence/rag-env/bin/python
-I -B /home/vigneshwar/Projects/zorvyq/scripts/zorvyq_chroma_worker.py
--reader <inherited-fd> --writer <inherited-fd> --nonce <per-worker-identity>
```

They are fixed application paths, not model/user command input. Execution uses an
argument array, `shell=False`, closed unrelated descriptors, no stdin, discarded
stdout/stderr and a minimal environment. Isolated Python ignores PYTHONPATH/user-site
injection. The script inserts only its own checkout for trusted application imports.
There is no listener, network API, shell bridge, arbitrary module selector or generic
command operation.

Only `count`, bounded `inspect`, explicit-vector `query` and `close` are allowed.
Both the parent and child reject mutation and unknown operations. The child accepts
only the approved corpus manifest/collection and approved source IDs. It cannot
create a collection, reset, upsert, delete, ingest, reindex or authorize retrieval.
Read-only mode also requests migration **validation**, not automatic migration.
The original indexing adapter's default behavior remains unchanged for its separate
explicit indexing workflows; the desktop bridge cannot access those commands.

The original worker's native network-denial filter and disabled implicit embedding
function remain in place. Networking is denied before Chroma import, including its
native threads. The vector worker never imports/constructs a model provider for
execution and never contacts Ollama. The RPC carries vectors and provenance IDs, not
questions, passages, answers, credentials or authorization decisions. Vectors remain
sensitive ephemeral data and are not logged or persisted by the bridge.

## Permission, synchronization and citation boundaries

The original parent-side KnowledgeAuthorization callback remains unchanged. It asks
through the existing GUI dialog for the exact source/query/snapshot fingerprint,
permits Allow Once or Deny, and asks afresh for each question. The child cannot return
an approval. Original backend/source/vector integrity verification still occurs
before per-question retrieval approval, as it did before this repair. A failure in
those checks can therefore precede the dialog; it is not an implicit permission grant.

Nomic and Qwen both remain in the same desktop process and use the original shared
native synchronization object. The process-local POSIX mutex is **not** presented as
a cross-process memory scheduler: no inference is delegated to the Chroma process.
Existing empty-residency checks, Nomic unload wait, zero keep-alive, generation
completion checks and conservative shutdown cleanup remain intact. The controller
still serializes requests and warned manual unloads. No foreign Ollama client is
stopped or evicted automatically.

The original Qwen-only generation guard, exact source scope, revocation/snapshot
checks, evidence limits, claim schema and `render_answer` citation validator remain
in the parent. Citation text is never trusted merely because it crossed IPC; only
vectors/candidates cross IPC, and parent SQLite provenance remains authoritative.
Unknown/malformed citations are rejected by the existing renderer. Private model jobs
are cleared; no conversation or report persistence was added.

**Foundation-Sec RAG remains disabled.** Manual specialist chat continues separately;
this repair does not enable automatic routing or certify live specialist compatibility.

## Bounds, cancellation and safe failures

- JSON envelopes reject unknown fields, duplicate keys, invalid versions/nonces /
  sequences, nonfinite numbers and oversized frames. Maximum frame: 512 KiB.
- One vector RPC at a time; existing parent vector/candidate/provenance validators
  are reused. Queries have at most eight candidates; integrity inspection has at
  most four vectors; dimensional/normalization checks remain unchanged.
- Startup/RPC deadline: 30 seconds by default (configuration limited to 1–60).
  Requests/writes are bounded; worker lifetime is capped at ten minutes, including
  owner permission wait. An expired worker fails closed; retry requires a new request.
- Worker budgets: 120 CPU seconds, 3 GiB virtual address space, 128 descriptors,
  disabled core dumps; existing low BLAS/OMP/Rayon thread limits remain.
- Parent cleanup sends a bounded close, then terminates/kills only its owned worker
  if necessary and reaps it. No discovered PID or unrelated system process is targeted.
- **Cancel knowledge retrieval** sets the shared cancellation event for vector and
  embedding waits. Close also requests cancellation. A currently blocked embedding
  read may wait for its existing I/O deadline. Already-running synchronous Qwen
  generation finishes within its provider timeout; cancellation does not kill Ollama.
- Vector deadlines now use a distinct safe `vector_timeout` category, avoiding a
  false claim that Qwen generation timed out. Worker startup/protocol/index failures
  use safe backend categories; denial, no evidence, schema/citation failure, model
  mismatch and residency remain distinct. Raw IPC/backend exception text is discarded.

GUI/feature availability now checks the compatible RAG runtime rather than treating
absence of Chroma in `.venv` as the whole system being unavailable. It states that
live retrieval acceptance is pending. Features remain experimental, not WORKING based
on code or mocked tests alone.

## Exact dependency/environment changes

**None.** No package was installed, removed, upgraded, downloaded or copied. No venv,
interpreter config, model or data directory was recreated or merged. Existing
`requirements-rag-phase1c.lock` remains unchanged. No source was reindexed, no index
was duplicated and no Chroma client was opened through another version. No startup,
launcher, firewall, service, permission grant or Git remote was changed.

A bounded import-only probe can be repeated without index/model access:

```sh
/home/vigneshwar/Projects/zorvyq/data/intelligence/rag-env/bin/python -I -B /home/vigneshwar/Projects/zorvyq/scripts/zorvyq_chroma_worker.py --probe
```

If the compatible environment later disappears or changes version, the desktop fails
closed. Restore/review that existing runtime first; any dependency installation still
requires explicit owner approval. No installation approval is currently necessary.

## Files added or extended

New:

- `zorvyq/rag_runtime.py` — bounded runtime metadata and approved manifest selection.
- `zorvyq/chroma_protocol.py` — strict bounded JSON on private pipes.
- `zorvyq/chroma_bridge.py` — existing-only read-only worker transport and lifecycle.
- `scripts/zorvyq_chroma_worker.py` — fixed restricted entrypoint and import-only probe.
- `tests/test_zorvyq_rag_runtime.py` — transport, worker policy and parent RAG fixtures.
- This report.

Extended:

- `friday/intelligence/chroma_index.py` — opt-in read-only/migration-validation mode;
  original default indexing behavior retained.
- `friday/intelligence/rag.py` — optional index factory and shared cancellation event.
- `friday/diagnostics.py` — content-free vector-timeout vocabulary.
- `zorvyq/services.py` — lazy compatible index selection and cancellation transport.
- `zorvyq/features.py` — correct compatible-runtime availability/evidence labels.
- `zorvyq/diagnostics.py` — accurate runtime/deadline explanations.
- `zorvyq/desktop/app.py` — runtime status, retrieval cancellation and shutdown signal.
- `tests/test_zorvyq_services.py`, `tests/test_zorvyq_desktop.py` — wiring/UI checks.
- `README.md` — current runtime repair pointer.

All 97 starting modified/untracked work files were protected in the ignored
`data/migration/phase2br/starting-work.tar.gz` with hashes and a binary Git diff before
edits. No starting file is missing. Store hashes are in `store-before.json` and
`store-after.json` alongside that checkpoint. Owner `.env` was not accessed.

## Tests and read-only verification

- Targeted final acceptance: **167 tests passed**, 3.342 seconds.
  `/tmp/zorvyq-2br-final-targeted.log`.
- Final full regression: **1,841 tests passed**, 16.933 seconds.
  `/tmp/zorvyq-2br-complete-regression.log`.
- Initial sandbox full run hit the existing four browser IPC PermissionErrors and
  four paired failures. The successful full rerun used the approval mechanism for
  local Unix-socket fixtures. It did not run inference, scans or diagnostics.
- `git diff --check` passed.
- Actual existing-environment import-only probe passed with network denial and
  `index_opened=false`. Actual metadata-only runtime detection returns available.
- All six existing knowledge/vector store file hashes match before and after tests.

New tests cover fixed interpreter/entrypoint and inherited pipes, strict framing,
nonce/version/sequence rejection, size/nonfinite/duplicate-field rejection, timeout,
EOF/cancellation/owned-child cleanup, unsupported mutations/commands, foreign scopes,
concurrent RPC refusal, exact runtime metadata, original parent authorization per
question, denial before embeddings/query/generation, revocation during approval,
verified citations, invalid citation rejection and private-job cleanup. Factory-wiring
fixtures run the original live orchestrator with synthetic repositories and a mocked
vector worker; no owner documents/store are opened by those tests. Offscreen GUI
checks cover the existing dialog and the new cancellation button.

The targeted set also exercises Qwen/Foundation-Sec selection, all three response
depths, persistence, model switching, unavailable provider/model, safe residency /
unloading, busy exclusion, no unsupported thinking option for Foundation-Sec, worker
responsiveness and orderly shutdown. The operation tests use synthetic counters,
fixtures, pipes and mocked commands for all eight categories and Full System Diagnosis,
including denial of arbitrary/privileged commands. No real model/embedding, diagnostic
operation, scan, VS Code, speech or microphone action was used for acceptance.

## Remaining issues and owner desktop acceptance

The runtime mismatch is repaired in code without installation. **Live Chroma client /
HNSW access, vector search and an authorized end-to-end desktop answer remain
owner-operated acceptance**, as do actual model accuracy and physical Wayland input.
Read-only metadata/import checks and mocks cannot certify those behaviors. The
migration-validation setting intentionally refuses an incompatible/migration-needing
store instead of repairing it. Do not respond to that failure by reindexing or replacing
existing records without separate review.

1. Launch via Ubuntu Run Application:
   `/home/vigneshwar/Projects/zorvyq/bin/zorvyq`.
   The installed Applications launcher repair/login migration remains a separate
   previously documented approval gate; it was not changed here.
2. Open Knowledge or Dashboard. Confirm runtime status mentions the existing RAG
   environment/ChromaDB 1.5.9 and derives the source/chunk counts from metadata. This
   status must not claim that a live answer was already accepted.
3. Open Cybersecurity → **Approved Knowledge**. Confirm Qwen3:4b is selected. Submit
   a small approved-topic question, such as an explanation of object authorization.
   Backend integrity checks run before the exact one-time permission dialog.
4. First choose **Deny**. Confirm no answer/embedding/generation is requested after
   denial, no model fallback occurs and the technical status says authorization denied.
5. Ask again. Review source scope and fingerprint, choose **Allow Once**, and permit
   the first owner-operated Nomic/Qwen run. Confirm a verified answer and expandable
   source cards with real URLs, revisions and chunk provenance. Keep the technical
   panel open to distinguish backend/vector, residency, generation and citation errors.
6. Repeat another question; a fresh permission decision is required. Check that Short,
   Medium and Deep preferences preserve citations and the original compact RAG limits.
   Invalid generated schemas/citations must withhold the answer, not invent a source.
7. During retrieval, try Cancel; retry afterward. Once generation has begun, expect
   bounded completion rather than an unsafe forced stop. Close/reopen and verify no
   private question/answer history was written and no vector worker remains.
8. Switch to Specialist Chat to test Foundation-Sec separately. Verify it is labeled
   experimental/model knowledge and never silently enters approved RAG. Check model
   and depth persistence plus normal app-owned unload behavior.
9. If a failure occurs before the dialog, capture only the safe technical category /
   stage for review. Do not paste private evidence into diagnostics, bypass checks,
   reinstall dependencies, migrate the index or run new indexing as a workaround.

No commit or push was performed. Work stops after this implementation/test report.
