# FRIDAY Phase 1 — secure local intelligence proposal

Date: 2026-10-10. **DESIGN ONLY; steps 1–3 reviewed; awaiting owner approval.**

No RAG implementation, dependency installation, package/model download, personal import, conversation migration, permission change, commit, or push has been performed. The only added project file is this report. Existing uncommitted work is preserved. Public upstream documentation and release metadata were consulted for model and dependency selection; no project content was submitted to those services. Phase 2 remains pending.

## 1. Existing architecture reviewed

Read `docs/FRIDAY_INTELLIGENCE_ARCHITECTURE.md` and inspected the following integration boundaries and existing tests:

| Boundary | Current behavior | Phase 1 plan |
|---|---|---|
| `friday/providers/ollama.py` | Standard-library synchronous local HTTP chat, final-answer validation, bounded adaptive responses | Preserve chat provider; add a separate bounded embedding adapter using standard-library HTTP |
| `friday/memory/database.py`, `manager.py` | SQLite session/message pairs, explicit key/value memory, desktop metadata; schema initialization can write | Leave existing database and records untouched; use a separate authoritative knowledge SQLite database |
| `friday/core/context.py`, `models/profile.py` | Complete-turn history trimming and conservative serialized UTF-8 budgets | Add one bounded inert evidence block within the existing input budget |
| `friday/core/assistant.py` | Deterministic tools precede generation; explicit private turns avoid persistence and scrub the last model job | Retrieve only after tool/intent routing; apply private-turn behavior explicitly to RAG |
| `friday/core/workload.py` | Exact L0 greetings, L1 deterministic routes, L2 ordinary and explicit L3 deep requests | Preserve classifier and fast exits; L3 alone does not trigger retrieval |
| `friday/models/manager.py`, `friday/sync/` | Synchronous single-provider jobs, provider execution mutex; model registry cannot rebind the provider | Keep generation manager; embedding adapter shares the execution boundary without rebinding the chat provider |
| `friday/tools/manager.py`, `permissions.py`, `access.py`, `filesystem.py`, `sensitive.py` | Schema/risk checks, exact filesystem authorization, descriptor-relative operations, symlink and sensitive-path exclusions | Preserve every rule; read permission never implies retention/indexing/retrieval permission |
| Dependency configuration | No requirements, pyproject, or dependency lock found; virtual environment contains only pip 25.1.1 | Add an optional, fully pinned RAG dependency manifest after approval; lazy-load Chroma |

Important findings:

- Python is **3.14.4**, SQLite **3.46.1**, x86-64 Linux; CPU is Ryzen 5 5600H, six cores/twelve threads. The supplied memory baseline is approximately 14.5 GiB; current available memory is transient. Free project filesystem space was approximately 413 GiB.
- `Settings.adaptive_workloads` defaults to **False**. Preserve that compatibility default and test both context paths; fast L0 behavior is currently opt-in.
- Standard adaptive input budget is **6,912 bytes** and deep budget **5,632 bytes**, derived from `num_ctx - num_predict - 512`. A larger evidence block must not silently increase either budget.
- `ResponseCategory.PRIVATE` controls speech eligibility but does not itself prevent ordinary `save_turn`. Retrieval must also suppress persistence, reusable history and retained model-job text.
- Ollama defaults to loopback, but the current provider accepts arbitrary configured URLs and standard HTTP proxy/redirect behavior. The new embedding transport needs an explicit local-only boundary.
- No embedding interface, Chroma index, semantic retrieval or RAG tests currently exist.
- `ollama list` failed because this execution sandbox forbids the socket. The Phase 0 audit reported only `qwen3:4b`, approximately 2.5 GB. Current server version, model inventory, actual model memory and embedding API compatibility are **not freshly verified**. No inference was attempted.

## 2. Storage permissions and proposed private policy

Metadata-only SQLite inspection used `mode=ro`, never the application's schema-initializing `Database` constructor. Existing tables are `sessions`, `messages`, `memories`, `desktop_project_sessions`, `recent_work`, and `sqlite_sequence`; `user_version=0`, journal mode `delete`. Conversation text and personal memory values were not queried.

Observed modes: `data/friday.db` **0644**; `data/`, project and Projects parent **0775**; home directory **0750**, owned by the user. Parent traversal restricts some users, but these modes do not constitute an owner-only storage policy. ACLs, shared groups, encryption, backups and Ollama service-account storage were not fully audited. **Do not chmod, migrate or rewrite the existing database as part of this proposal.**

Proposed new storage, created only after approval:

```text
data/intelligence/                 0700, owner-only
  knowledge.sqlite3               0600, authoritative source content and metadata
  chroma/                         0700, rebuildable vector generations
  staging/                        0700, bounded synthetic import staging if needed
```

All child directories must be 0700 and files, journals, WAL/SHM sidecars and temporary artifacts 0600. Validate ownership, permissions, regular-file identity and no symlink/hardlink substitution at creation and reopen; reject unexpected insecure existing storage rather than silently repairing it. Use descriptor-based checks for FRIDAY-controlled files. SQLite and Chroma open paths themselves: a validated owner-only parent is necessary, and path checks cannot isolate hostile processes running under the same UID.

Use scoped umask 0077 during synchronous creation, restore it afterward, and verify actual permissions on reopen. If Chroma creates incompatible permissions, stop and report. Protect the entire intelligence directory through the existing sensitive-path boundary even if a parent folder has a read grant. Existing `.gitignore` already excludes `data/*`; no knowledge assets belong in Git.

This policy protects against ordinary cross-user reads; it is **not encryption**, root protection or protection from compromised same-user processes. SQLite content and embeddings remain sensitive; logical deletion does not guarantee forensic erasure from storage, WAL, backups or retired generations. Before Phase 2, separately review disk encryption, backup exclusions and retention/deletion policy. No encryption package is proposed for synthetic Phase 1.

This deliberately narrows Phase 0's proposal to add tables to the existing conversation database: a separate SQLite knowledge database avoids touching conversation records and permits private creation without silently changing legacy permissions. Reuse transaction patterns and validation conventions, not the conversation schema initializer.

## 3. Exact direct dependency proposal and compatibility gate

| Component | Exact proposed version | Purpose |
|---|---|---|
| Python | Keep existing 3.14.4 for initial compatibility assessment | No interpreter replacement approved or proposed automatically |
| `chromadb` | **1.5.9** | Embedded `PersistentClient`; no cloud/server client |
| SQLite | Existing Python stdlib, linked SQLite 3.46.1 | Authoritative knowledge storage; no pip SQLite package |
| Ollama Python SDK | **Not added** | Standard-library HTTP avoids another direct dependency |
| LangChain, LlamaIndex, sentence-transformers, Transformers, PyTorch | **Not added** | Small explicit RAG interfaces; inference stays in Ollama |
| Test runner | Existing stdlib `unittest` | No pytest dependency needed |

Chroma 1.5.9 has a Linux x86-64 `cp39-abi3` wheel of **23.3 MB**. Its Python requirement is >=3.9; this does **not prove the complete dependency graph works on 3.14**. [Exact release and wheel metadata](https://pypi.org/project/chromadb/1.5.9/).

The release declares broad dependencies including NumPy, ONNX Runtime, tokenizers, Pydantic, pydantic-settings, gRPC, OpenTelemetry, Uvicorn and Kubernetes. Even with explicit Ollama vectors, ONNX Runtime is a declared package dependency. Chroma is therefore a substantial addition to this currently stdlib-only application. [Release dependency declarations](https://raw.githubusercontent.com/chroma-core/chroma/1.5.9/pyproject.toml).

**Complete transitive versions and artifact hashes are not resolved.** No installer/resolver or package downloads were run. The exact direct dependency above is a proposal, not a complete installation lock. Do not approve an unrestricted `pip install chromadb` or assume unspecified transitive versions have been reviewed.

Requested staged approval: first authorize metadata-only dependency resolution for Chroma 1.5.9 on the existing Python/platform. Present every selected transitive version, wheel availability, hashes, exact download total and vulnerability/license findings **before installing any package**. Installation requires owner acceptance of that concrete lock. If compatible wheels cannot be obtained, report the blocker and propose a separate interpreter/environment for approval; do not compile arbitrary source packages, replace `.venv`, skip dependencies or use `--no-deps` to force a pass.

Use wheels and a hash-checked locked manifest in an isolated RAG environment; keep current `.venv` available for rollback and current functionality. No automatic package updates, model pulls or fallback downloads. Full import/startup compatibility and real Chroma persistence tests remain post-approval gates.

## 4. Embedding model evaluation and selection

The models below are alternatives for evaluation; **only Nomic is proposed for download**. No comparative local retrieval benchmark has been performed. CPU performance judgments are expectations based on model size/architecture, not measured rankings.

| Candidate | Published Ollama artifact | Resource/retrieval tradeoff |
|---|---|---|
| `all-minilm:22m` | 46 MB F16; 256-token context | Small CPU baseline, likely inexpensive; short context constrains chunking and technical passages. Expected runtime allowance 0.2–0.6 GiB for small inputs, unmeasured. [Artifact](https://ollama.com/library/all-minilm:22m) |
| **`nomic-embed-text:v1.5`** | **274 MB F16; 137M parameters; 8,192-token configured context** | Selected balance of resource cost, English retrieval and context headroom. Expected small-batch runtime allowance **0.5–1.5 GiB**, unmeasured; do not routinely embed full 8K inputs. Apache-2.0. [Artifact](https://ollama.com/library/nomic-embed-text:v1.5) |
| `embeddinggemma:300m` | 622 MB BF16; 2,048-token context | Relevant multilingual alternative; larger artifact and Gemma terms; requires Ollama >=0.11.10. Expected small-batch allowance 1–2 GiB, unmeasured. [Artifact](https://ollama.com/library/embeddinggemma:300m) |

Nomic produces 768-dimensional vectors; use `search_document: ` for documents and `search_query: ` for questions, full dimensions and cosine similarity initially. Record prefix policy and normalization in the generation manifest. Its publisher provides retrieval benchmark evidence, but that does not establish quality on FRIDAY's future corpus. [Publisher model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).

Proposed model identity: explicit tag `nomic-embed-text:v1.5`, registry short digest observed **0a109f422b47**. Tags can move; the full manifest/blob digest must be verified at the approved pull and pinned locally. A changed artifact requires review, not a silent replacement. Missing model means a safe unavailable result, never an automatic pull.

Use `/api/embed`, bounded batches, `truncate=false`, finite nonzero 768-value vectors and expected response count/model validation. Reject oversized inputs/responses, NaN/Infinity, malformed JSON and unexpected dimensions. Check installed server API support before use; the model page's historical minimum version is not sufficient evidence for the current batch endpoint. [Embedding API](https://docs.ollama.com/api/embed).

Sequential model lifecycle:

1. L0/L1 returns through the existing paths without touching Chroma or invoking embeddings.
2. For an explicitly authorized knowledge query, acquire the shared inference boundary; unload the configured generation model if resident and verify the unload before embedding. Do not unload unrelated owner models silently.
3. Embed query with the approved model, retrieve/validate evidence, unload the embedding model and verify release before generation. Use explicit keep-alive controls rather than default multi-minute residency.
4. Release the embedding execution section, then use the existing generation manager for `qwen3:4b`. Do not hold the same non-reentrant mutex while asking ModelManager to acquire it again. The current single-threaded scheduling prevents overlap inside FRIDAY; external Ollama clients remain outside that guarantee.
5. Explicit indexing may keep the embedder loaded for bounded batches, with unload in `finally`. No eager startup load, background indexer or watcher.

Model swaps introduce cold-load latency. Avoid query embedding calls for disabled retrieval, denied scopes, empty/unready indexes and ordinary conversation. Keep generation behavior outside RAG unchanged. Measure swaps and residency after approval; no assertion that two models fit simultaneously.

## 5. Download, RAM and storage budget

| Resource | Planning estimate, not an observed RAG benchmark |
|---|---|
| Approved candidate model download | Approximately **274 MB**, plus small manifest/license overhead |
| Chroma wheel | **23.3 MB** for Linux x86-64; excludes dependencies |
| Complete dependency downloads | Reserve **150–400 MB** provisionally; exact total awaits the full compatible lock |
| Installed dependency environment | Reserve **0.5–1.5 GiB**, plus retained wheel cache if approved |
| New Ollama model disk use | Approximately **0.3 GiB**; transient download overhead may add more; shared blob accounting varies |
| Embedder runtime | **0.5–1.5 GiB** for small batches as a planning allowance; server/scratch buffers and input length affect peak |
| Python/Chroma runtime | Budget **0.2–0.8 GiB** for a small index, unmeasured and not a hard upper limit |
| `qwen3:4b` runtime | Reserve roughly **3–6 GiB** depending on context and runtime; existing 2.5 GB artifact is not RAM usage |
| Initial working free-space reserve | **3 GiB** for dependencies/model/small synthetic corpus and rebuild headroom; increase for larger corpora |

At 768 dimensions, float32 vector payload is `chunks × 768 × 4` bytes: **29.3 MiB per 10,000 chunks** per vector copy. Chroma graph/log/database overhead and duplicate vector representations add storage. Budget approximately 100–300 MiB per 10,000 chunks provisionally for the index, plus SQLite source/chunk text; corpus content may dominate. Rebuild requires room for both old and new generations. Enforce initial corpus/chunk limits and measure actual usage before increasing them.

Expected CPU indexing speed, query latency and cold model swap time are **unknown**. Do not turn these resource allowances into performance promises. Preserve OS/application headroom; bound batch size and refuse/pause indexing when resources are insufficient.

## 6. Proposed Phase 1 RAG design — not implemented

Add a small optional `friday/intelligence/` package with source repository, embedding adapter, vector adapter, retrieval policy/service and evidence records. Avoid a framework or architectural rewrite.

- SQLite owns `sources`, `revisions`, `chunks`, explicit purpose/scope approvals, index generations and an outbox of indexing operations. Use parameterized SQL, foreign keys, checked states, ordered knowledge-only migrations and bounded metadata validation.
- Stable source ID: owner-assigned namespace/external key maps to a persistent UUID. Identical text does not merge unrelated provenance. Immutable content revisions use SHA-256 plus policy versions. Chunk IDs derive from source/revision/chunker/ordinal; repeated identical ingestion is a no-op, changed content creates a new revision.
- Start with synthetic text supplied explicitly to an ingestion interface. No recursive file scan, personal files, ChatGPT adapter, existing chats/memories or automatic memory promotion. Any later approved file adapter must go through existing filesystem authorization plus separate exact retention/indexing consent.
- Proposed initial caps: 1 MiB UTF-8 document, 10,000 active chunks, chunks <=1,536 UTF-8 bytes with <=192-byte overlap at valid character boundaries; deterministic paragraph-aware splitting. These are byte bounds, not tokenizer claims; `truncate=false` rejects oversize token inputs. Bound query size, batch bytes and batch count (initially at most four).
- Chroma `PersistentClient` stores only opaque chunk/revision/generation IDs, hashes and explicit vectors; omit document bodies, titles and original paths. Disable default embedding functions and pass `embeddings`/`query_embeddings` explicitly. SQLite rehydrates content and validates active source/revision/scope for every result.
- Configure local embedded operation, telemetry disabled and no OTLP exporter; isolate untrusted environment settings and verify no external sockets or telemetry/cache writes outside approved paths during initialization, indexing, query and reopen. The pinned config exposes telemetry defaults, but flags alone are not an offline proof. [Chroma configuration](https://raw.githubusercontent.com/chroma-core/chroma/1.5.9/chromadb/config.py).
- Commit approved source/chunks plus index jobs atomically in SQLite. Apply idempotent Chroma upserts, then mark jobs applied. Crash replay uses identical IDs/hashes. There is no cross-database transaction guarantee.
- Search only approved ready generations, with bounded candidates (initially eight) and at most three evidence chunks. Fit serialized evidence plus citation metadata into at most 2,048 bytes and the existing total input budget; reduce whole chunks/history or refuse if mandatory input cannot fit. Semantic distance is not confidence; calibrate relevance/abstention with labelled fixtures.
- Citations use runtime-generated labels mapped to validated SQLite source ID, revision, safe title and span. Reject unknown generated citations; missing/corrupt/stale records cannot be cited. A valid citation label does not prove that the answer faithfully represents its source.
- Retrieval evidence is inert escaped data, distinguished from live owner/system instructions. Never pass it or generated answers to routing, IntentTranslator, permission management or tool execution. Prompt-injection resistance depends on that execution boundary, not merely wording in the prompt.
- Make RAG turns private by default: no `save_turn`, reusable history, automatic speech or raw model-job retention; errors/logs contain codes/counts/timings, not text, queries, paths or embeddings. Tool authority always comes from the current owner request and existing gateway.
- Deletion first revokes source eligibility in SQLite, with durable vector-deletion jobs; stale vectors cannot restore access. Rebuild creates a separate generation, validates content/model/counts and switches the active generation transactionally. Corruption disables retrieval with a safe message. Retired index cleanup is a separate explicit action, not automatic destructive cleanup.
- Python deadlines cannot guarantee cancellation of native Chroma calls. Begin with corpus/resource bounds and explicit checkpoints; report actual timeout limitations and consider a bounded worker only if measurements justify it.

## 7. Validation completed during steps 1–3

These are existing targeted regressions, using existing mocks/temp fixtures; no new RAG tests or dependency installation:

| Existing test selection | Passed | Failed |
|---|---:|---:|
| `test_memory.py` | 22 | 0 |
| `test_workload.py` | 84 | 0 |
| `test_filesystem_permissions.py` | 94 | 0 |
| `test_ollama*.py` | 24 | 0 |
| `test_tools.py` | 29 | 0 |
| `test_core.py` | 8 | 0 |
| `test_model_runtime.py` | 25 | 0 |
| **Total** | **286** | **0** |

Existing benchmark: `PYTHONPATH=. .venv/bin/python -B tests/phase6d_benchmark.py --samples 5`; synthetic provider, native POSIX mutex, five samples per scenario, all ten compatibility/adaptive scenarios had zero errors.

| Adaptive route | Median response wall time | Model calls |
|---|---:|---:|
| L0 greeting | 0.035 ms | 0 |
| L1 synthetic folder listing | 1.605 ms | 0 |
| L1 synthetic known-file read | 1.749 ms | 0 |

Measured cumulative Python peak RSS was approximately 35.4 MiB; excludes Ollama and is not per-scenario memory. These numbers are a current unchanged-code baseline, not RAG improvements. Compatibility greeting used one mock-model call; compatibility L1 medians were 1.837/1.748 ms. Five samples are insufficient for reliable p95 claims.

The first benchmark invocation omitted `PYTHONPATH=.` and failed with `ModuleNotFoundError: friday`; rerunning with the script's documented command succeeded. No code/test change was used to fix it. The local Ollama inventory attempt was also blocked as noted above. Full regression suite, real embeddings, Chroma integration, RAG security, indexing/retrieval/rebuild benchmarks and live model memory were **not run** in this proposal stage.

## 8. Post-approval acceptance plan and remaining risks

After provisioning approval, test malformed metadata, bounds, duplicates/revisions, symlink/hardlink/out-of-root access, denied/revoked retrieval scopes, missing model, nonfinite/wrong-sized vectors, corrupted/stale/foreign-scope indexes, crash/outbox replay, deletion and rebuild consistency. Test injection documents containing forged approvals, tool calls, fake citations and role delimiters; assert no tool invocation, grant change, raw logging, history/job persistence or automatic speech.

Run the complete existing regression suite without weakening tests, new RAG units/security/integration tests, and real pinned Chroma reopen tests with external network denied. Use synthetic labelled queries, irrelevant distractors and no-answer cases for Recall@3/MRR and unsupported-answer checks. Measure cold/warm indexing throughput, retrieval latency, model-load time, Python and Ollama RSS separately, disk bytes, incremental no-op behavior and rebuild IDs/ranking consistency (allow justified ANN/tie tolerance). Repeat unchanged L0/L1 baseline before/after using the same benchmark conditions. Report retrieval quality separately from reasoning quality.

Outstanding risks: unresolved transitive dependency lock/3.14 wheels; unverified Ollama server/API and model residency controls; native index corruption/resource behavior; plaintext storage and same-user access; package telemetry/environment defaults; citation fidelity and prompt-injection susceptibility; CPU cold-load overhead; corpus relevance calibration. No successful retrieval will be presented as proof of improved reasoning.

Phase 2 prerequisites: Phase 1 implementation/security/regressions accepted; complete private-storage and retention policy; separately approved importer and source/retrieval consent contract; archive limits/branch/role handling; model and dependency manifests; owner-approved data selection. **No Phase 2 ingestion or implementation is authorized by this proposal.**

## 9. Approval status

Awaiting owner decision on the separate private SQLite/Chroma policy, Chroma 1.5.9 candidate, Nomic v1.5 candidate and sequential model lifecycle. The next dependency action should be metadata-only resolution and presentation of the complete lock; no package installation occurs before the owner accepts exact transitive versions. A model pull also requires explicit owner approval. No steps 4–9 implementation begins before the applicable approvals.
