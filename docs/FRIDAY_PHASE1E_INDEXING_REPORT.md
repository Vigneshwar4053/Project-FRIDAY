# FRIDAY Phase 1E — completed real cybersecurity indexing

Completed 2026-10-12 under explicit owner approval for monitored soft admission limits. **20 approved real document revisions and 312 chunks are indexed in private local Knowledge SQLite and persistent ChromaDB.** No excluded source, personal document, new website or additional model was included. Live FRIDAY RAG remains disconnected.

The previous hard-limit stop report/results are preserved as `FRIDAY_PHASE1E_HARD_LIMIT_STOP_REPORT.md` and `FRIDAY_PHASE1E_HARD_LIMIT_STOP_RESULTS.json`. The owner's later approval explicitly authorized this monitored experiment; unavailable kernel quotas were not required or represented as active hard limits.

## 1. Exact indexed corpus and fingerprints

| Item | Result |
| --- | --- |
| Approved documents retained/indexed | **20 / 20** |
| Deterministic chunks acknowledged in SQLite | **312 / 312** |
| Explicit vectors persisted in ChromaDB | **312** |
| New chunks indexed in this session | **312** |
| Sequential embedding batches | **78**, exactly four chunks each |
| Corpus fingerprint | `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4` |
| Nomic v1.5 registry manifest | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` |
| Embedding/index configuration fingerprint | `idx_474dc19543813c52cb4d4575f99e24c97eac2fb4c28d7ce3666a378f6e02bfc7` |

Exact source paths, hashes, licenses and upstream commits remain in [the unchanged approved corpus](FRIDAY_PHASE1E_CORPUS.json). The collector manifest and approval artifact remain immutable historical review records; their old `indexed=false` fields are not live index state. SQLite acknowledgments and this execution report are authoritative for completed indexing.

The two policy blockers (`wstg-345317d8a05797f6`, `cheatsheets-92f7483b28548679`), two deprecated stubs (`wstg-7a1e7d6157efc92b`, `cheatsheets-86ddfbe1de52c357`) and the complete MITRE archival bundle were not ingested, embedded or indexed. Only the approved bounded processed MITRE text was indexed. No privacy detector or authorization boundary was weakened.

## 2. Current-state and artifact verification

The exact approved scope and all 20 original/processed content hashes, sizes, source records, upstream versions and license hashes passed before activation and after execution. The monitored runner's revalidation reads only approved document content; excluded file content remains outside that path. The unchanged manifest byte hash seals the source records against substitution. File identities are pinned again for the approved reads; the returned text hash must match before retention.

The existing isolated installation was verified against **84 pinned wheels and 6,467 installed wheel payload files**. Versions, size/SHA-256 and ZIP checks passed; ChromaDB remains **1.5.9**. Nomic dimensions/capability, registry manifest and config/weights/license/parameter layers match the approved fingerprints. Qwen3:4b's original registry digest remains `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`. No packages or models were installed, pulled or evicted.

The manifest verifier distinguishes Ollama's local wrapper from the original registry blob and verifies both fields/descriptor and the registry hash; no digest mismatch was bypassed.

## 3. Persistence, provenance and recoverability

- Storage: `data/intelligence/phase1e/knowledge/knowledge.sqlite3` and `data/intelligence/phase1e/chroma/`. Private owner-controlled directories are mode 0700 and regular files mode 0600; symlinks, hardlinks and unsafe existing modes are rejected rather than repaired. Final private-tree checks passed.
- Both stores were closed and reopened through the existing repository/adapter lifecycle. All **312 explicit stored vectors**, including values, source ID, revision ID, chunk ID and content hash, were inspected in batches of at most four and matched authoritative SQLite provenance. The aggregate vector fingerprint was identical before close and after reopen: `0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca`.
- SQLite holds exactly 20 approved current revisions, exact normalized text hashes, deterministic chunk IDs/offsets/text and 312 acknowledgments in the approved embedding generation. Full reconstructed chunk comparison passed. `PRAGMA integrity_check` returned `ok`; foreign-key checking found no violations.
- Stable source IDs derive from the immutable source URL; revision IDs bind source metadata, upstream revision, content hash and chunker version; chunk IDs bind revision, offsets, ordinal and text hash. Explicit vectors are upserted before acknowledgment. An interrupted upsert without acknowledgment is nonauthoritative and replayable; acknowledged chunks are skipped.
- On reopen, no pending chunks remained. The existing regression suite verifies failed-upsert/failed-acknowledgment replay and incremental idempotency. An actual forced interruption was not introduced into the successful corpus run.
- `progress.json` was atomically replaced and fsynced after every successful batch. It reports 20 documents, 312 chunks and 312 acknowledged chunks. Checkpoints are observational; SQLite is authoritative.
- The single standalone runner holds an owner-private session lock. Re-running it revalidates the exact owner approval, source hashes/file identities and installed artifacts, rejects foreign stored sources/revisions, and asks the existing authorization contract for only exact requests. Document text never grants authority. No unconditional allow callback is used.

## 4. Revocation, outdated-source and citation validation

The actual existing revocation/evidence contracts were exercised against production vectors inside deliberately rolled-back validation transactions in the **same** knowledge repository. A revoked source and an outdated current-revision pointer were excluded from evidence/retrieval. A genuine candidate from a different approved source was rejected in a restricted-source scope. Every test restored the original approved source state and acknowledgments; all 312 mappings were verified again afterward. No new text revision or duplicate test repository was created, and no production source remains revoked.

All **7 returned citations** on the seven prepared questions matched authoritative current source, revision, document SHA-256, chunk SHA-256/offsets and the evidence citation map. They also matched each question's single expected document. **Citation integrity failure rate: 0/7; wrong-document citation rate: 0/7.** These are evidence-map/document-label checks, not generated-answer factuality measurements. No answer generation occurred.

## 5. Real retrieval measurements

All seven [prepared source-checked questions](FRIDAY_PHASE1E_RETRIEVAL_QUESTIONS.json) were used without changing their wording or expected sources. Each search used the full 20-source scope and five explicit-vector chunk candidates, then the existing bounded retrieval/citation service.

| Question | Expected document top-1 | Expected document in top-5 chunks | Verified citations | Embedding + search ms |
| --- | --- | --- | ---: | ---: |
| tls_versions | yes | yes | 1 | 588.0 |
| container_capabilities | yes | yes | 1 | 578.8 |
| parameterized_sql | yes | yes | 1 | 586.0 |
| object_authorization | no | yes | 1 | 577.2 |
| file_permissions | yes | yes | 1 | 597.5 |
| dependency_disclosure | yes | yes | 1 | 597.3 |
| network_zones | yes | yes | 1 | 598.4 |

- **Top-1 document accuracy: 6/7 (85.7%).** The object-authorization question ranked Application Platform Configuration first, rather than the prepared Authorization Cheat Sheet label.
- **Recall@5: 7/7 (100%).** This is document-level expected-source recall among five chunk hits; multiple hits may belong to the same document. It is not passage-level recall or five distinct-document recall.
- **Budgeted evidence expected-document coverage: 7/7 (100%).** Each question returned one verified citation under the unchanged 2048-byte evidence budget. This budget may skip longer candidate chunks; source coverage does not establish sufficient answer content.
- **Wrong-document top-1 retrieval rate: 1/7 (14.3%).** This is separate from the 0/7 wrong-document citation rate of the final budgeted evidence.
- Retrieval median: **588.0 ms**; maximum: **598.4 ms**, measured as local query embedding plus vector search. These exclude answer generation and the subsequent independent citation-path validation call.
- First model-nonresident query: **588.0 ms**. Subsequent cache-warm reload median: **591.7 ms**. A repeated first question through the full retrieval service took **339.0 ms**.

Every request uses `keep_alive=0`. No model-resident warm benchmark or cold disk-cache benchmark was performed; no OS caches were evicted. The embedding provider defers resident/conflicting workloads rather than evicting them.

**Seven curated questions are only an acceptance sample.** The labels are one expected document per question, checked against source paragraphs, not independent exhaustive relevance judgments. These results do not establish strong general cybersecurity retrieval accuracy or generated-answer correctness.

## 6. CPU, RAM, disk and admission policy

| Measurement | Actual observation |
| --- | ---: |
| Real indexing time, 78 batches | **184.385 seconds** |
| Indexing throughput | **1.69 chunks/second** |
| Monitored session wall time, including validation/retrieval | **205.716 seconds** |
| Sampled relevant CPU consumption | **645.53 CPU-seconds** |
| Mean sampled CPU over session | **3.14 cores** |
| Peak observed additional RSS | **581,476,352 bytes (554.5 MiB)** |
| Peak total relevant-process RSS | **664,207,360 bytes (633.4 MiB)** |
| Minimum observed MemAvailable | **8.22 GiB** |
| Minimum observed free disk | **410.82 GiB** |
| New experiment storage, regular-file logical bytes | **3,476,893 bytes (3.32 MiB)** |
| New experiment storage, regular-file allocated bytes | **3,502,080 bytes (3.34 MiB)** |
| Resource-limit incidents | **None** |

The experiment began with no existing store at this location, so final regular-file storage is its additional storage growth. It includes knowledge/chunks, Chroma vectors/metadata, approved-scope provenance, progress and raw execution metrics; installed packages/models and the original corpus were already present and are not counted as new index storage. Filesystem directory/inode metadata is not included in regular-file totals.

The owner-authorized monitored admission checks run before and after every batch: **MemAvailable >=3 GiB**, **free disk >=10 GiB**, **measured experiment storage <=100 MiB**, **maximum 312 chunks**, **batch size <=4**, cancellation and Ollama resident-workload checks. Relevant RSS/CPU includes the controller, owned descendants/Chroma worker and Ollama descendants, with pre-session baselines for additional RSS. Initial available RAM was 9.39 GiB and free disk 410.84 GiB.

A background sampler with a 50 ms wait checks RAM/disk/cancellation and a five-minute session deadline. Actual sampling intervals also include process-enumeration time. Chroma RPC and embedding calls use 30-second timeouts. A threshold observation stops admission and cancels the owned session; acknowledged progress remains recoverable. Only owned index workers are closed/terminated by the existing adapter lifecycle. No unrelated process/model is killed or evicted, and no swap or host quota/cgroup setting is changed.

**These are monitored soft admission limits, not guaranteed hard ceilings.** Sampling may miss brief peaks and exited-runner CPU tails; RSS counts shared mappings, and Ollama CPU includes daemon work observed within the interval. The standalone execution gate is process-local; external clients are not locked, so resident checks before/after requests detect conflicts rather than prevent every race. No conflicting workload or threshold violation was observed. No FRIDAY model generation was launched during the experiment.

## 7. Safety boundaries and regressions

The existing KnowledgeRepository, IndexingService, RetrievalService, Nomic provider, Chroma adapter, authorization/revocation contracts and citation metadata were reused. The adapter gained only bounded explicit-vector count/inspection operations to verify persistence; no second storage or embedding implementation was introduced.

Targeted intelligence tests: **55 passed**. Targeted Phase 1 tests: **48 passed**, including **10 new monitored-runner/vector-inspection tests** for threshold/cancellation handling, excluded-file reads, exact retention/index grants, rolled-back exclusion and explicit-vector inspection. Existing foundation tests cover failed acknowledgment/replay, changed revisions, untrusted prompt-injection text, no memory access, no automatic execution and bounded retrieval.

**Full FRIDAY regression: 1,663 passed in 19.738 seconds.** Log: `data/intelligence/provisioning/phase1e-monitored-regression.log`. The full suite used the approved host execution for existing headless IPC tests. `git diff --check` passed. Final exact-corpus revalidation, all 312 provenance mappings, SQLite integrity/foreign-key checks and private storage checks passed.

No project `.env`, personal SQLite memory, owner authentication, desktop permissions, browser automation, offline voice or Qwen configuration was modified. No new package/model/website was collected. Cybersecurity document content was never executed. Existing unrelated uncommitted work was preserved. No commit or push occurred.

## 8. Remaining Phase 1F work

Phase 1E real indexing is complete; no unavoidable indexing blocker remains. Before live integration:

1. Explicitly authorize Phase 1F and wire retrieval to the real application execution gate/model lifecycle with bounded cancellation, source scope and existing owner authorization. Keep unrelated resident models protected.
2. Design citation/evidence presentation that preserves exact provenance while handling the 2048-byte budget and untrusted text. Validate answer-supporting excerpts, not only document identity. Do not let retrieved instructions grant tool, memory or system authority.
3. Expand independently reviewed retrieval questions and passage-level labels, study the authorization-query rank miss, and evaluate generated-answer/citation faithfulness and refusal behavior without silently changing approved documents/revisions.
4. Expose safe source revocation and separately authorized corpus updates; exercise interrupted-session resume operationally. Keep personal memory isolated and revalidate exact hashes before each retained revision/index resume.
5. Preserve the explicit monitored-policy wording and measure real runtime contention/latency before changing model residency or resource policy. No live FRIDAY RAG connection was made by this phase.

Raw measurements and per-batch progress: `data/intelligence/phase1e/execution.json`; compact results: [FRIDAY_PHASE1E_INDEXING_RESULTS.json](FRIDAY_PHASE1E_INDEXING_RESULTS.json). **Stopped after reporting.**
