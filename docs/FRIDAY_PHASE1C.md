# Phase 1C: optional real local adapters and provisioning review

Execution update (2026-10-12): the owner subsequently approved provisioning.
All 84 pinned wheels and the exact Nomic artifact are verified and installed;
synthetic retrieval/persistence and resource gates passed. Phase 1D collection
then completed without real indexing. See [execution results](FRIDAY_PHASE1CD_REPORT.md).
The preparation status and proposal below remain as the historical review record.

Status: adapters, mocked tests and artifact review prepared. **Explicit owner
approval of package/model provisioning is pending.** No package wheels or model
weights have been downloaded or installed. Real Chroma persistence, embedding
quality, RAM and latency benchmarks have not run. This is not a completed real
RAG validation report.

Existing 3L/3M browser, voice, generation, router, memory, authentication and
permission code is unchanged. No real documents, website data, conversation
records or browser content were ingested. No commit or push occurred. Qwen3:4b
remains the only generation model; Foundation-Sec-8B is not proposed or pulled.

## Foundation and dependency evidence

The existing Phase 1B modules/report were reviewed and all 39 foundation tests
passed before changes. The current interpreter is CPython 3.14.4 on Linux x86-64.
Ollama 0.40.0 reports only `qwen3:4b`, manifest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`;
the initial resident-model list was empty. These were metadata-only requests.

PyPI release JSON was used to resolve a platform-compatible wheel set without
fetching package artifacts. Actual installation/import compatibility remains a
post-approval gate. Initial resolver attempts were inefficient and rejected
OpenTelemetry's explicitly pinned beta dependencies; lazy candidate evaluation
and accepting only explicitly required prereleases produced the final lock.
That review error was not treated as evidence of package incompatibility.

| Reviewed package | Version | This checkpoint |
| --- | --- | --- |
| chromadb | 1.5.9 | Proposed installation |
| langchain-core | 1.6.9 | Deferred |
| langchain-text-splitters | 1.1.3 | Deferred; retain deterministic Phase 1B chunker |
| langchain-chroma | 1.1.0 | Deferred; use existing VectorIndex directly |
| langchain-ollama | 1.1.0 | Deferred; use bounded direct local HTTP |

Chroma and its 83 required transitive distributions are listed in
`FRIDAY_PHASE1C_ARTIFACTS.json`: exact versions, compatible wheel filenames,
official PyPI-hosted URLs, SHA-256 fingerprints, byte counts, Python constraints,
dependency declarations and license metadata/classifiers.
`requirements-rag-phase1c.lock` pins those 84 artifacts by hash. Python 3.14 native
wheels include NumPy 2.5.4, ONNX Runtime 1.31.0, grpcio 1.84.0 and pydantic-core
2.50.1. ONNX and network SDKs are declared Chroma dependencies even though this
adapter never invokes their downloading/default embedding paths.

Chroma's license is Apache-2.0. The selected dependencies declare MIT, BSD,
Apache, PSF, ISC, MPL and other recorded permissive/composite licenses; bundled
distribution notices have not yet been inspected because wheels have not been
downloaded. Missing SPDX strings retain publisher classifiers rather than
inventing a license. The lock is not a vulnerability or supply-chain certification.

## Model review and exact approval proposal

Nomic `nomic-embed-text:v1.5` is selected for the initial experiment: an official
Ollama-library F16 artifact, 137M parameters, 768 dimensions, Apache-2.0.
The GGUF declares a 2,048-token native context while the packaged parameters
request 8,192; this adapter conservatively uses 2,048 with `truncate=false`.
Document/query prefixes are `search_document: ` and `search_query: `.

Manifest SHA-256:
`0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`

Weight layer SHA-256:
`970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6`

The complete manifest, config/license/parameter hashes and exact sizes are in the
artifact review. Total planned model transfer is 274,303,158 bytes (261.6 MiB),
including small registry metadata. The model itself is 274,290,656 bytes.

BGE-small-en-v1.5 is a smaller English retrieval candidate: 384 dimensions,
512-token input, approximately 68 MB F16 in the reviewed community Ollama
conversion. The BAAI upstream and that conversion are distinct artifacts; no
conversion provenance or local latency/quality benchmark was established here.
It is deferred rather than substituted silently for an official pinned artifact.

The approval request covers:

- 105,993,182 bytes (101.1 MiB) of 84 exact wheels from `files.pythonhosted.org`.
- An isolated `data/intelligence/rag-env`, leaving the existing `.venv` untouched.
- A hash-checked wheel cache at `data/intelligence/provisioning/wheels`.
- Only the selected Nomic artifact in the existing Ollama model store.
- Synthetic-only embedding/index/retrieval benchmarks, without Qwen generation.

Approximately 442,191,839,232 bytes (411.8 GiB) were free on the project filesystem.
Reserve 2 GiB for the environment, cached artifacts, model and small benchmark
data. Estimated additional RAM is 0.7–2 GiB, not a measurement. The <=2 GiB and
warm p95 <=1 second targets remain unverified.

## Adapter security contracts

`ollama_embeddings.py` implements EmbeddingProvider without an SDK or pull API:

- Literal loopback HTTP endpoints only; no DNS hostname, credentials, proxy,
  redirect, remote server, cloud model or implicit download.
- Exact installed tag/digest, embedding capability and 768 dimensions checked
  before and after requests. No generation endpoint is used.
- Four-input batches, per-input/batch/request/response byte bounds, finite nonzero
  vectors, explicit request/deadline limits and cancellation checks.
- Shared FRIDAY Synchronization injection serializes this provider against
  generation using that same gate. Existing generation composition is untouched.
- Conservative refusal when any model is already resident; no existing workload
  is unloaded. Our embedding request uses `keep_alive=0` so it is ephemeral.
- Only scalar response timing/token counters are retained, never prompts.

The shared gate cannot atomically lock unrelated external Ollama clients. The
adapter checks resident state and refuses detected overlap, but there is no
server-wide exclusive-client guarantee. This limitation must remain visible.

`chroma_index.py` implements VectorIndex through an owned multiprocessing worker:

- Pinned Chroma version, local PersistentClient, generation metadata and cosine
  configuration checked on create/reopen; no cloud/server client.
- Explicit vectors and opaque source/revision/chunk/hash metadata only; no
  document bodies, `query_texts`, data loaders or embedding function.
- Source filters, four-record upserts, eight-candidate queries and bounded deletes.
  SQLite still independently verifies authorization, revisions and provenance.
- Private 0700 directories/0600 files and no symlink/hardlink substitution in the
  exact vector tree; inherited cloud/telemetry environment is cleared.
- The worker changes into its private directory before importing Chroma. Chroma
  defaults to `.env` settings: explicit `_env_file=None` and rejection of `.env`
  storage entries prevent access to the project's real environment file.
- Telemetry disabled; Linux x86-64 seccomp denies network socket creation,
  connect/bind/datagram sends and io_uring bypasses in Python and native threads.
  Failure to install the filter prevents Chroma import. Pipes remain available.
- Hard response deadlines and cancellation terminate/reap only the owned worker.
  Uncertain operations require reopen; they do not become successful acknowledgements.

The platform-specific isolation intentionally fails closed elsewhere. Owned
private storage does not protect against malicious same-UID processes. No
retrieved evidence is connected to tools, ordinary memory, speech or generation.

## Prepared synthetic benchmark

`tests/phase1c_rag_benchmark.py` uses only original TCP/IP, TCP versus UDP, Nmap
concepts, Linux hardening and defensive-assessment text. It creates a fresh
private benchmark directory under `data/intelligence/phase1c-benchmarks/` and
never opens `data/friday.db` or any real corpus. Existing data ignore rules cover
the environment, cache, SQLite, Chroma and report artifacts.

After approval and successful isolated installation, it will test actual
embeddings, stable SQLite-verified IDs/citations, stale/revoked exclusion, empty
scope handling and persistent reopen. Fifty samples measure top-1 accuracy on
five labelled questions, embedding/search latency, indexing throughput, disk
growth and sampled parent/worker/Ollama RSS. This is a small smoke benchmark,
not a broad cybersecurity retrieval-quality evaluation.

The default ephemeral-model policy measures cache-warm reloads, not a deliberately
resident warm embedder. A resident-session policy and a true warm-model benchmark
require a reviewed ownership/lifecycle contract before future generation use.
An RSS sampling interval can miss short-lived peaks; reported results must state
that limitation. Core module-import peak RSS was measured separately at
25,919,488 bytes (24.7 MiB), without a CLI session or model inference; it is not
the full running FRIDAY-plus-Ollama baseline.

## Validation and pending work

Mocked adapters test manifest/model changes, endpoints/proxies/redirects, prefixes,
bounds, malformed JSON, finite dimensions, refusal of resident Qwen, shared-gate
serialization, private settings, explicit embeddings/scopes, cancellation,
deadlines and kernel-enforced native-network denial in a disposable child.
Foundation regressions remain intact. No real Chroma collection or real model
embedding has been claimed successful.

Final pre-provisioning verification: **55 targeted adapter/foundation tests
passed; 1,615 full regression tests passed outside the sandbox; `git diff --check`
passed.** The initial sandbox full suite encountered the same four synthetic
headless IPC errors and their cleanup failures; those passed outside it. No
browser or voice implementation changed during this checkpoint.

Primary references: [Chroma 1.5.9 release](https://pypi.org/project/chromadb/1.5.9/),
[pinned Chroma settings](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/config.py),
[Nomic artifact](https://ollama.com/library/nomic-embed-text:v1.5),
[Nomic publisher instructions](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5),
[BGE publisher card](https://huggingface.co/BAAI/bge-small-en-v1.5).

Pending: explicit provisioning approval, hash-checked wheel download/offline
installation, `pip check`, real adapter import/persistence checks, model pull and
digest verification, synthetic benchmark, measured resource/accuracy report,
and final regressions in the approved isolated environment. Any actual package,
model or adapter incompatibility must be reported rather than bypassed.

Qwen3:4b integration is a later checkpoint: explicit retrieval opt-in, total-context
budgeting, inert evidence, citation validation, private job/history lifecycle and
automatic-speech suppression. No LangChain agents or router replacement are planned.
