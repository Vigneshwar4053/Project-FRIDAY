# FRIDAY Phase 1F — explicit live cybersecurity RAG integration

Date: 2026-10-13. Branch: `feature/voice-foundation`.

Implementation and synthetic testing are complete. The owner approved exactly one live acceptance request, which ran on 2026-10-13 and failed safely at the existing Qwen output-token limit. Phase 1F is **not live-accepted**. No second request or retry was run. No commit, push, merge, package/model/document download, corpus rebuild, or new document embedding occurred. The project's `.env` was not opened, printed, or modified.

## Audited integration map

| Boundary | Actual implementation and finding |
| --- | --- |
| Terminal and confirmed voice input | `friday/main.py:main` calls `FridayAssistant.respond`; `friday/voice/cli.py:voice_turn` calls it with `persist=False`. |
| Deterministic tools | `ToolRouter.route`, followed by `ToolManager.execute`; `IntentTranslator.translate` handles eligible unmatched requests. |
| Adaptive L0–L3 | `FridayAssistant._respond_measured`, `_choose_workload`, and `friday/core/workload.py:classify`. |
| Qwen generation | `ModelManager.generate` → `execute_job` → `OllamaProvider.chat`; existing provider remains bound to `qwen3:4b`. |
| Owner/knowledge authorization | Desktop owner authentication remains separate. `KnowledgeAuthorization.require` accepts only typed exact requests and `KnowledgeDecision.ALLOW_ONCE`; retrieval approval is never inferred from indexing approval. Direct terminal allow-once interaction is used without accessing authentication secrets. |
| Persistence | `FridayAssistant._respond` invokes `MemoryManager.save_turn` and appends reusable history when `persist=True`. PRIVATE response metadata alone does **not** prevent those writes. |
| Speech | The main loop calls `SpeechController.speak_safe_response`; trusted PRIVATE metadata has `speech_eligible=False`. |
| Synchronization | The main loop injects its synchronization object into `ModelManager`. Nomic receives that same object. Existing gates are non-reentrant. |
| Logging/private behavior | Existing diagnostics expose scalar workload metrics. RAG clears prior workload diagnostics, does not log questions/passages, and keeps only scalar timings. Responses are displayed to the requesting terminal. |
| Knowledge adapters | Existing `RetrievalService`, `KnowledgeRepository`, `ChromaVectorIndex`, `OllamaEmbeddingProvider`, and exact Phase 1E integrity validators are reused. |

This map was shared before application edits. No additional assistant, router, generation model, or model manager was created for application operation.

## Index revalidation

The existing isolated `data/intelligence/rag-env` supplies ChromaDB; `.venv` does not. An initial open using `.venv` failed inside and outside the sandbox. Using the previously installed isolated environment resolved that environment-selection error without installation or index changes.

Successful offline verification before edits and after implementation:

- Approved corpus fingerprint: `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4`.
- Exact approved content, source metadata, original/processed hashes, license hashes and manifest matched the existing approval artifact.
- SQLite integrity: `ok`; foreign-key violations: zero.
- Exactly 20 active approved current source revisions, 312 deterministic chunks and 312 matching index acknowledgments.
- Persistent Chroma opened; exactly 312 vectors inspected in batches of four. Every vector's ID, revision, source and content hash mapped to eligible current SQLite evidence.
- Aggregate vector fingerprint: `0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca`, matching Phase 1E.
- Revoked, stale, foreign and excluded source records fail exact validation. Excluded document content is not opened by the reused revalidation path.

The live path repeats full corpus, SQLite and vector verification for every explicit request. It uses an existing-only Chroma open: a missing database or collection fails without creating a replacement collection. It never invokes ingestion, indexing, or document embedding. Existing Chroma/SQLite lifecycle housekeeping may touch store sidecars; this is not a filesystem snapshot or a corpus rebuild.

## Files changed

| File | Change |
| --- | --- |
| `friday/intelligence/rag.py` | Small private orchestrator, deterministic command parser, citation validator/renderer, exact allow-once CLI approval, lazy verified backend composition. |
| `friday/core/assistant.py` | Early explicit-command interception and serialized assistant turns. |
| `friday/main.py` | Attach the lazy orchestrator to the existing assistant and model manager. |
| `friday/models/manager.py` | Optional trusted pre-inference check under the existing mutex; private-job cleanup in `finally`. Existing defaults preserved. |
| `friday/intelligence/retrieval.py` | Scalar query embedding, vector search and evidence verification timing measurements. Existing retrieval limits preserved. |
| `friday/intelligence/chroma_index.py` | Optional existing-only open; normal indexing behavior retains its prior default. |
| `tests/test_phase1f_rag.py` | 26 new synthetic tests. |
| `docs/FRIDAY_PHASE1F_REPORT.md` | This report. |

## Command and request flow

```text
answer using approved knowledge: <question>
```

Matching is case-insensitive, anchored to the beginning after stripping surrounding whitespace, and accepts whitespace before the colon and before/after the question. Empty questions are rejected. Automatic cybersecurity classification is disabled. Normal chat, L0 greetings and L1 deterministic tools retain their existing paths. Both adaptive and non-adaptive modes intercept explicit RAG before classification, tool routing, or generic intent translation.

The request proceeds through bounded question validation → exact corpus/index verification → per-question RETRIEVE authorization → Nomic query embedding → existing Chroma search (at most 8 candidates) → exact SQLite evidence verification → whole-chunk budget selection (at most 3 chunks and 2048 UTF-8 serialized evidence bytes) → evidence-delimited Qwen request through the existing manager → source/citation validation → application-rendered answer and verified source list.

Whole evidence items that exceed the budget are skipped; passages are never truncated. Empty verified/budgeted evidence returns an explicit insufficient-evidence response without generation. Generation uses the existing standard inference profile in both modes: default 768 output tokens, 8192 context tokens, 300-second timeout, with the existing conservative input-byte limit. A smaller configured profile is honored and may reject the request. No conversation or personal memory is added to the RAG prompt.

## Citation verification and injection isolation

Qwen returns bounded JSON claims with a nonempty list of supplied citation IDs for every claim. Unknown IDs, malformed output, duplicate JSON keys, uncited claims, inline citation markers/URLs, and model-provided bibliography fields fail the whole answer. There is no uncited fallback, silent marker stripping, or automatic retry. An empty claim list is an insufficient-evidence response.

Source labels are generated by the existing verified retrieval service. Before generation, evidence eligibility is checked again under the inference mutex. After generation, source snapshots and every cited chunk are rechecked against current SQLite evidence and the exact approved document metadata. Stale/revoked/replaced evidence withholds the answer. The source list is built from verified title, URL, source ID, revision ID/upstream version, chunk ID, publisher, and license/provenance metadata. The model cannot supply that list.

Evidence is untrusted serialized JSON in a separate message between explicit delimiters. Application control flow never passes it or the answer to tools, intent translation, authorization, memory, configuration, or scanning. Synthetic hostile passages asking for shell execution, `.env` access, and memory writes reach only the model's data message; tool execution and routing mocks remain untouched.

Citation integrity verifies metadata and evidence membership. It does not prove that every generated factual claim follows from its cited passage. This remains a generated-answer quality limitation requiring live review and broader passage-level evaluation. The existing retriever also has no independently calibrated relevance threshold; verified candidate provenance alone does not establish relevance.

## Privacy and synchronization

RAG returns through an early private path regardless of the caller's `persist` argument. No RAG question, answer or passage enters ordinary personal memory, reusable session history, public speech fingerprints, or ordinary conversation context. PRIVATE response metadata prevents automatic speech. Model-job prompts, results and detailed errors are cleared in `finally`, including generation failure/interruption. Request-local evidence/backends are closed on exit; only scalar timing/citation metrics survive. The existing `/speak TEXT` remains an explicit user-directed operation.

An assistant-level reentrant lock serializes its requests, including existing recursive file explanations. Nomic embeddings and Qwen generation both acquire the existing inference gate; generation is never called while an outer copy of that non-reentrant gate is held. A trusted pre-inference callback runs under the actual manager gate, waits up to ten seconds for the owned Nomic model to disappear from `/api/ps`, and rejects unrelated resident workloads without eviction.

Nomic uses `keep_alive=0`. Existing Qwen chat omits `keep_alive`, so Ollama's configured server residency policy applies. Mutex release does not unload Qwen. A resident Qwen or another workload can therefore defer subsequent RAG embedding; wait for normal server expiry rather than terminating/unloading unrelated workloads. No second generation model starts. The gate is process-local and cannot prevent external Ollama clients from racing; resident checks detect observable conflicts rather than guaranteeing host-wide exclusion. Existing HTTP generation cancellation remains synchronous; owner Ctrl+C returns a private cancellation response and scrubs the job.

## Failures and tests

Authorization denial, backend/model absence, store incompatibility, index mismatch, invalid evidence, budget exhaustion, generation timeout/failure, invalid citation labels, source changes and owner cancellation return explicit safe failures. They never fall back to an uncited general-model answer. Existing adapter errors are fixed safe messages; unexpected exceptions are replaced with a fixed backend failure.

The 26 tests use original synthetic documents, mocked embeddings/generation/backends and existing adapters. They cover recognition/empty requests, normal chat and L0/L1, both modes, evidence selection and budgets, exact metadata, unknown/malformed/uncited citations, wrong-document candidates, revocation before/during generation, stale sources, metadata substitution, hostile-text isolation, no tool execution, no memory/history persistence, speech suppression, backend failure, cancellation, shared Nomic/generation mutex, concurrent turn serialization, context budgets, direct exact CLI authorization, index mismatch, missing stores and no replacement Chroma collection.

Final full regression in FRIDAY's normal `.venv`: **1,689 tests passed in 18.194 seconds, zero skips**, comprising the existing 1,663 tests and 26 new Phase 1F tests. Log: `data/intelligence/provisioning/phase1f-regression.log`. Targeted RAG tests: **26 passed**; combined RAG/adapter/Phase 1E monitored tests: **52 passed**. `git diff --check` passed. The earlier isolated-environment full run passed 1,684 of 1,685 discovered tests with its real Argon2 test skipped; the normal-environment final run covers that test successfully.

Sandbox-only runs hit the existing headless browser IPC PermissionError; host execution was used for full verification. One targeted multi-module invocation needed `PYTHONPATH=tests:.` because an existing Phase 1E test uses a top-level fixture import; the corrected invocation passed. No real Nomic or Qwen inference was used in routine regression tests.

## Live acceptance and remaining work

The owner-approved single live request ran through the existing assistant and original CLI knowledge approval prompt. Its result was a safe failure, detailed below. The output-token budget and evidence selection were not changed, and no retry was made. The approval is consumed; another live attempt requires fresh owner authorization.

Use the existing RAG environment to run the application locally: `data/intelligence/rag-env/bin/python -B -m friday.main` (optionally `--adaptive`). Launching from `.venv` continues to fail safely for explicit RAG because Chroma is absent there. The isolated RAG environment lacks Argon2, so any pre-existing desktop flow requiring real password verification still needs FRIDAY's normal owner-auth environment; no packages or owner-auth behavior were changed. Deployment environment consolidation requires separately authorized dependency work.

Before automatic RAG: review the one live generated answer; evaluate factual support and passage relevance over independent labels; calibrate retrieval relevance/no-evidence behavior; review model residency contention; then add an explicitly reviewed classification policy while preserving L0/L1 and exact retrieval authorization/privacy. No automatic classification is enabled in this phase.


## Owner-approved live acceptance — 2026-10-13

**Result: FAILED SAFELY; Phase 1F live acceptance remains blocked.** Exactly one query embedding and one Qwen generation request were made. No retry or substitute answer was attempted.

Preflight, before inference:

- Exact approved corpus fingerprint, SQLite integrity/foreign keys, 20 active current revisions and all 312 vector mappings passed again. The aggregate vector fingerprint remained `0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca`.
- Available RAM: **10,947,264,512 bytes (10.20 GiB)**, exceeding the existing 3 GiB admission threshold.
- Pinned `nomic-embed-text:v1.5` identity/capability/dimensions and `qwen3:4b` identity passed local metadata checks. `/api/ps` reported zero resident workloads. No models were loaded by preflight.
- The initial sandboxed metadata check failed on loopback transport; the permitted host-level metadata check passed. Both preflight attempts performed zero embeddings and zero generation requests.
- Retrieval authorization used the **original `CLIKnowledgeApproval` terminal prompt**, not the prepared mock callback. The prompt displayed the exact approved 20-source scope, titles, URLs and upstream revisions. The owner's explicit approval authorized submitting its `[1] Allow once` choice for this question only. `KnowledgeAuthorization.require` accepted the exact RETRIEVE request with scope fingerprint `de0d06d0515a4f772c91aefa8e1fea2f7b92d218e415635c0be7ccb04ae9ef61`. No persistent grant or indexing-approval promotion occurred.

| Measurement | Observation |
| --- | ---: |
| Query embedding, including provider identity checks | 0.879323 s |
| Chroma vector retrieval | 0.008627 s |
| Retrieved evidence verification and budget selection | 0.010040 s |
| Chroma retrieval + evidence verification | 0.018668 s |
| Retrieval pipeline, including human/terminal approval wait | 23.058420 s |
| Qwen HTTP generation wall time, including load/prompt evaluation | 120.453774 s |
| Ollama-reported output generation duration | 86.692051 s |
| Total assistant response wall time, including authorization and backend cleanup | 146.536812 s |
| Peak observed additional relevant-process RSS | 4,129,673,216 bytes (3.85 GiB) |
| Peak total relevant-process RSS | 4,198,199,296 bytes (3.91 GiB) |
| Minimum observed available RAM | 6,889,164,800 bytes (6.42 GiB) |
| Resource samples | 1271 |
| Serialized evidence | 1885 bytes, 1 whole chunk |
| Prompt/output tokens reported by Ollama | 1112 / 768 |
| Verified retrieved evidence labels | 1 |
| Verified citations in a released generated answer | **0** |

The existing monitor observed no resource incident. Its nominal 50 ms sampling includes process enumeration overhead, can miss brief peaks, and counts shared RSS mappings. These are observed soft-limit measurements, not hard RAM ceilings. Total response time includes the terminal allow-once approval delay, so it is not a pure machine-processing latency measurement. Evidence verification above measures retrieval selection; full index validation is included in total time. Final generated-answer citation verification was not reached.

### Exact generation failure and printed response

The existing Ollama provider rejected `done_reason=length` after exactly **768 output tokens**, the unchanged standard profile limit. It reported:

> Ollama reached the output-token limit without a complete final answer. Use a shorter request or review the inference profile budget.

The application printed only its safe response:

> Approved knowledge generation unavailable, timed out, or failed; no verified answer was returned.

No partial model text, uncited answer, or invented source bibliography was released. The provider reported thinking absent and final-content text present, but token-limit termination prevented treating that text as a complete answer. There is consequently no generated answer with verified citations to print. The ordinary 300-second timeout was not the failure cause.

### Citation correctness and evidence relevance

The single supplied evidence label `[S1]` mapped to:

- Title: **File Permissions**.
- Approved URL: `https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management/09-File_Permissions.md`.
- Source ID: `src_26921fde208fb75101da5ffcd55629e69fdce4697b0431d43cd0032193fc1aa3`.
- Exact SQLite revision: `rev_1aa52e3036a49fccac6c00b42a5ac37d2ab73482d3296b5dd5648bc4be064b97`.
- Upstream revision: `74a854b2635316b63b53f1e4e2e8d482a59d2f71`.
- Verified chunk: `chk_665903025991c80a73c3e66fc302f38acab17874d45bc00ad3a86a31251fbb64`.
- License: `CC-BY-SA-4.0`; approved license SHA-256: `9312b09a6848f26c6046652238ddd6b32ea2124847faed48854c375c5194238d`.

The application verified this chunk's provenance and current eligibility before generation. This is a genuine approved OWASP source, with correct metadata, but the selected document is **File Permissions**, not the expected object-authorization material. This is a retrieval/evidence-selection relevance limitation; correct provenance does not establish sufficient support for the requested BOLA explanation. The request retained the existing 8-candidate, 3-chunk, 2048-byte limits. No retrieved passages are included in this report. No generated citation labels reached validation, so generated-answer citation correctness and factual support remain **not evaluated**, rather than passed.

### Privacy and persistence observations

- The same `FridayAssistant.respond` explicit private path was used, with no ordinary personal memory component attached.
- Existing personal conversation database/sidecar file identity, size and modification-time metadata were unchanged before/after the request. Their contents were not opened for this check. This is a metadata observation, alongside the absence of a memory writer, not a content-hash audit.
- Reusable user/assistant history entries: **0**.
- Retained model-job messages: **0**; retained result: **False**. The failed job's detailed error was replaced with the existing fixed private error.
- Automatic speech eligibility: **False**; no speech controller was created and no speech ran.
- No tool manager was attached; no tools, desktop actions or network scans executed. Connections were limited to the existing local Ollama service. No cloud access occurred.
- No question, passage or generated answer was saved to personal memory/history. Only scalar measurements and source metadata were written to a temporary owner-private metrics file; this report contains no retrieved passage or partial generation text.
- `.env`, generation budgets, installed packages/models, approved documents and vector contents were not modified. No document embeddings, reindexing, commits or pushes occurred.

### Remaining blockers and smallest follow-up

The live attempt does not satisfy successful answer acceptance. The immediate blocker is incomplete generation at the unchanged 768-token limit. A separate follow-up should review whether a tighter final-answer/schema instruction can produce a complete response within the existing budget; this acceptance run did not alter that budget. Evidence selection also needs review because the whole-chunk 2048-byte budget supplied File Permissions for the BOLA question. Use offline/synthetic evaluation to improve topical evidence selection without falsifying or truncating provenance, then request fresh approval for any further real model test. Automatic RAG remains disabled. Stopped after recording this one attempt.
