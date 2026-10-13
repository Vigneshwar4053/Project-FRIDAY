# FRIDAY Phase 1E — corpus review and indexing preparation

Reviewed 2026-10-12. **20 documents are eligible, pending separate owner approval. No real-document retention into Knowledge SQLite, embedding or indexing was performed.** Two Phase 1B policy blockers and two deprecated/moved-page archives are excluded. The original corpus and manifest remain unchanged.

The exact approval artifact is [FRIDAY_PHASE1E_CORPUS.json](FRIDAY_PHASE1E_CORPUS.json). It contains each eligible document's immutable source URL, original/processed paths and SHA-256, upstream version, license path/hash/URL, attribution, topics, KnowledgeSource identifier, chunk count and pinned embedding/index manifest. Its approval scope fingerprint is:

`ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4`

## Eligible corpus

The corpus has nine WSTG documents, ten Cheat Sheet Series documents and one bounded MITRE ATT&CK ICS subset. Only the listed processed UTF-8 text is eligible. Original Markdown, the complete MITRE JSON bundle, subset JSON, licenses, metadata and archived stubs are evidence or archives, not separate indexing inputs.

| Document identifier | Source title | Chunks |
| --- | --- | ---: |
| wstg-fb9527bf77829831 | 2. Introduction | 15 |
| wstg-8a027d3c686807c0 | The Web Security Testing Framework | 11 |
| wstg-df053f7f6c267fad | Conduct Search Engine Reconnaissance for Information Leakage | 10 |
| wstg-5f1677ef5c39ff16 | Fingerprint Web Server | 8 |
| wstg-f492acfd3f7d60c0 | Network Infrastructure Configuration | 17 |
| wstg-ccbf608faeb758cf | Application Platform Configuration | 22 |
| wstg-0a67db8f808ffcfc | File Permissions | 10 |
| wstg-5166e28061164939 | Bypassing Authorization Schema | 9 |
| wstg-58a9c5b2c685a872 | Penetration Testing Methodologies | 6 |
| cheatsheets-fb8b6e5c60ed7830 | Authorization Cheat Sheet | 29 |
| cheatsheets-163390e3dcf5cc96 | Input Validation Cheat Sheet | 7 |
| cheatsheets-0c00c87970eceb40 | SQL Injection Prevention Cheat Sheet | 16 |
| cheatsheets-ab43825f2095a964 | Logging Cheat Sheet | 26 |
| cheatsheets-f9c79d45e84f972d | Transport Layer Security Cheat Sheet | 22 |
| cheatsheets-9dbfa41b1c298280 | Docker Security Cheat Sheet | 22 |
| cheatsheets-843f0de69d31b794 | Network segmentation Cheat Sheet | 9 |
| cheatsheets-83997daf32c01123 | OS Command Injection Defense Cheat Sheet | 10 |
| cheatsheets-77e7a460c4072442 | Vulnerable Dependency Management Cheat Sheet | 23 |
| cheatsheets-11c58e683e1cbeae | Vulnerability Disclosure Cheat Sheet | 22 |
| mitre-08b83d2cea6b6d67 | MITRE ATT&CK ICS — bounded defensive subset | 18 |

OWASP WSTG commit: `74a854b2635316b63b53f1e4e2e8d482a59d2f71`; Cheat Sheet Series commit: `cb9fe01e5ddf17b42513d2c53c4b86196c665c45`; MITRE commit: `6cda5ad8462c79e14fbb872f4e09059b18e0cfc4`. The WSTG snapshot is a development snapshot, not a claimed stable release. Publication dates remain unknown/null; commit dates are not publication dates. Coverage excludes Nmap documentation and complete networking/Linux/Enterprise ATT&CK curricula.

## Two policy blockers and safe disposition

| Identifier | Source name / publisher | Failure category | Disposition |
| --- | --- | --- | --- |
| `wstg-345317d8a05797f6` | Sensitive Information Sent via Unencrypted Channels — OWASP Foundation and WSTG contributors | Phase 1B credential-assignment pattern, one match | Exclude current processed revision |
| `cheatsheets-92f7483b28548679` | Authentication Cheat Sheet — OWASP Foundation and Cheat Sheet Series contributors | Phase 1B credential-assignment pattern, one match | Exclude current processed revision |

Both fail the conservative `reject_secrets` policy in `friday/intelligence/ingestion.py`. There were zero private-key marker matches, zero private JSON credential matches and zero unsupported controls in either document. Phase 1D's narrower collector scan passes; it does not supersede Phase 1B's ingestion policy. No matched values or potentially sensitive passages are printed or stored in this report.

Formatting normalization (BOM, newlines, NFC) cannot fix these exclusions. A non-retaining experiment replaced each complete matched span with a fixed removal notice; both candidate strings passed the unchanged Phase 1B policy. This establishes technical feasibility, not approval or proof that the source contains no real credentials. No derivative file was saved. If these sources are wanted later, review the complete affected example/prose, remove credential-like material without reconstructable remnants, preserve attribution/license and original bytes, record the transformation and new SHA-256, rerun document/chunk/metadata validation, and obtain separate approval for the derivative revisions. No detector weakening or publisher allowlist bypass is permitted.

The archived stubs `wstg-7a1e7d6157efc92b` and `cheatsheets-86ddfbe1de52c357` remain excluded for deprecated/moved-page status; they are distinct from the two policy blockers.

## Corpus verification

The existing Phase 1D validator passes, and `scripts/phase1e_review.py` adds read-only verification:

- All 22 active originals and processed texts, both archives, MITRE subset, license bytes, source commit/tree responses and transfer metadata match retained hashes, sizes and pinned identities. All active and archived Git blob identities match the retained upstream tree entries, rather than only a manifest-provided blob hash.
- Exact active upstream paths and topic choices match the saved source-review selection. Repository, publisher, immutable URL, commit/date, license, attribution and transformation binding are checked. The 24 originals and 24 processed texts have no duplicate content hashes; no unlisted file is accepted.
- Original-to-processed transformations are reproduced byte for byte. The bounded MITRE selection is regenerated and compared to its subset JSON; source objects, relationships, identity/marking support and license are preserved.
- Inventory, topic/chunk totals, transfer totals, SHA256SUMS and readiness inventory agree. File type, UTF-8, link/path identity, nonexecutability and size checks pass. Private filenames are refused before content validation. All eligible texts and chunks pass the unchanged Phase 1B text policy.
- Only retained local HTTPS collection evidence was examined. This is offline consistency validation, not independent remote reauthentication or cryptographic publisher signatures. Known-pattern detection is not exhaustive. No website or embedded link was fetched.

License metadata verified: OWASP `CC-BY-SA-4.0` and MITRE `LicenseRef-MITRE-ATTACK`, with the original license bytes and copyright/attribution evidence retained. The MITRE license is not the MIT software license. Preserve the corresponding notices and applicable adaptation/redistribution conditions with exports; no endorsement is implied.

## Prepared indexing procedure and workload

This is a reviewed runbook; real indexing remains disabled pending approval. Reuse `KnowledgeRepository`, `read_text_file`, `TextChunker`, `IndexingService`, `RetrievalService`, `ChromaVectorIndex`, `OllamaEmbeddingProvider`, `KnowledgeAuthorization`, `IndexManifest` and existing citation methods. No second repository, vector service, embedding implementation or runtime integration was introduced.

1. Recompute the review against the unchanged corpus and compare the exact approval fingerprint. Any source, metadata, license, processed text, revision, selection or embedding configuration change invalidates that approval. Verify input identities again through `read_text_file` at use time. Do not infer grants from document contents.
2. Use a trusted host authorization callback with separate READ_DOCUMENT, RETAIN and INDEX decisions tied to their exact existing request scopes. Owner approval must explicitly cover reading the listed files, retaining those revisions in the dedicated knowledge store and computing/indexing their local embeddings. Do not promote a read grant into a retention/index grant or install an unconditional allow callback for arbitrary input.
3. Map source metadata to `KnowledgeSource` using the immutable HTTPS source URL, publisher, title, verified-publisher classification, topics and unknown publication date. Retain one processed document at a time, recording its upstream commit as `document_revision`. Store license/transformation provenance beside the review; processed attribution remains part of authoritative text.
4. Use the pinned Nomic v1.5 manifest/digest, 768 dimensions, `search_document: ` and `search_query: ` prefixes, L2 normalization, cosine distance and the existing 1536-byte/192-byte-overlap chunker. Use the isolated Phase 1C environment. Qwen3:4b is unchanged and is not used for embeddings or answer generation.
5. Run `index_batch` serially: at most four chunks and 6144 text bytes per batch. SQLite determines pending chunks; successful vector upsert precedes acknowledgment. If a crash leaves vectors without acknowledgment, they remain nonauthoritative and deterministic upsert replay recovers them. An acknowledged unchanged chunk is not reembedded. Snapshot checks reject revision changes during approval/embedding.
6. Retrieve only within explicit approved source scopes. SQLite verifies every vector candidate's current revision, provenance, chunk hash and acknowledgment; citations come from verified evidence. A revoke immediately excludes stale vectors even before physical vector cleanup. Changed bytes under the same source create a new revision; replacing an immutable upstream URL is a new source requiring new approval, with the old source explicitly revoked when superseded. A revoked source cannot be reactivated through duplicate ingestion.

Expected workload: **312 chunks, 348,732 processed bytes (~340.6 KiB)**; **78 nonempty batches** when batching across the eligible source scope, or **87** when finishing one source at a time. Raw float32 vector payload is **958,464 bytes (~0.914 MiB)**; actual Chroma metadata/HNSW/SQLite disk use is larger. The earlier five-document synthetic throughput would suggest about 50 seconds, but real corpus timing, model reloads and indexing overhead are unmeasured; this is not a duration promise.

## Storage and memory plan

Use dedicated private directories such as `data/intelligence/phase1e/knowledge/knowledge.sqlite3` and `data/intelligence/phase1e/chroma/`, created only after approval; keep review/provenance alongside them. SQLite and its sidecars remain authoritative. Chroma stores only vectors and opaque source/revision/chunk hash metadata, with implicit embedding functions disabled. Store no personal-memory records and do not connect these services to desktop, voice, tools or generation.

Retain the existing ~5.39 MB corpus once; avoid copying the 4 MB MITRE archive into the repository. Reserve 100 MiB free disk for initial real knowledge/index/run artifacts; measure actual growth and stop before exhausting that budget. This is a proposed admission budget, not an already installed storage quota. Any expanded corpus requires fresh approval and revised accounting.

Run one embedding batch at a time under the shared execution gate. Ollama uses loopback-only direct HTTP, no proxy, redirect or pull, `keep_alive=0`, `truncate=False`, bounded context and four threads. If any model is already resident, defer rather than evict it. Chroma uses its isolated, telemetry-disabled worker with native outbound-network denial and bounded RPCs.

For the approved runner, reuse the existing `MemorySample` sampler/cancellation event: stop admission if additional sampled RSS exceeds **2 GiB** or host available RAM drops below **2 GiB**; sample every 50 ms and include Ollama descendants, parent and worker. Use 30-second adapter request/RPC deadlines and a five-minute session watchdog, pausing recoverably at the first bound or cancellation. A watchdog should stop only its owned index worker and defer further requests; do not unload or kill external models. These session/storage controls must be wired into the activation runner before real embedding begins. Sampled RSS is a practical gate, not a hard kernel memory limit, and can miss brief spikes. The prior **425.2 MiB** synthetic peak is the only measured simultaneous additional RSS; no real-corpus peak is claimed.

## Completed and deferred validation

**Final regression: 1,641 tests passed in 18.197 seconds**, including eight new Phase 1E tests. Log: `data/intelligence/provisioning/phase1e-regression.log`. The final run used the approved sandbox escalation for existing headless IPC tests. The first sandbox run hit the known four browser IPC errors/four cleanup failures and an incorrectly placed new test method; the test method was corrected before the passing rerun. `git diff --check` passed.

| Requirement | Completed evidence | Remaining after separate approval |
| --- | --- | --- |
| Correct cybersecurity retrieval | Existing synthetic topic retrieval/citation fixtures pass | Real Nomic/Chroma held-out query evaluation |
| Wrong-document citation rejection | Foreign source, stale/duplicate candidate, tampered provenance/hash and cross-source pointer tests pass | Repeat against the real index |
| Revoked-source exclusion | Immediate exclusion, persistent reopen and new revocation-between-batches test pass | Real Chroma stale-vector exercise |
| Changed-document handling | New revision, approval-time mutation, stale candidates and retry/replay tests pass | Real changed-revision index/retrieve exercise on isolated test copies |
| Prompt-injection isolation | Inert synthetic instructions pass under blocked network/process/memory/speech effects | Check real evidence remains inert in the approved retrieval harness |
| No personal-memory access | Existing memory database/save hooks forbidden in synthetic tests; reviewer denies repository construction | Repeat isolation with real adapters |
| No automatic tool execution | Existing synthetic subprocess/network/voice isolation checks pass; review imports no execution service | Keep tools and generation disconnected |
| Bounded RAM and processing | New four-chunk/6144-byte/incremental tests and high-RSS/low-available-memory cancellation simulation pass; existing timeout/response/candidate/evidence tests pass | Wire and test watchdog/storage admission, measure real RSS/time and disk growth |

Prepared real retrieval questions (no query embeddings have been computed): transport protection → TLS Cheat Sheet; container privilege reduction → Docker Security; parameterized SQL queries → SQL Injection Prevention; per-object authorization → Authorization Cheat Sheet; permission review → WSTG File Permissions; dependency remediation → Vulnerable Dependency Management; network segmentation → Network Segmentation. After approval, record expected source identifiers before running, require expected source in top-three evidence and validate every returned citation's source/revision/document/chunk hashes. Treat this as an acceptance sample, not comprehensive retrieval-quality certification. Add an isolated synthetic injection fixture without expanding the approved real corpus.

No existing uncommitted file was edited by this phase. Added only the review script, review tests, this report and exact corpus artifact (plus regression log in ignored local data). No model was downloaded or invoked; no project `.env` or personal memory was read; no website was collected; desktop/voice behavior was not modified; no commit or push was performed.

## Exact approval required

A separate instruction must approve **reading, retaining in dedicated Knowledge SQLite, and locally embedding/indexing only the 20 processed document revisions in `docs/FRIDAY_PHASE1E_CORPUS.json`, scope SHA-256 `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4`, using the pinned Nomic manifest and bounded existing Chroma pipeline**. The two policy blockers, two archives and complete MITRE archival bundle remain excluded. The instruction “continue the work” during this review is not treated as that separate corpus approval.

Suggested approval wording:

> Approve Phase 1E corpus `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4`: read and retain the listed 20 processed revisions in dedicated Knowledge SQLite and locally embed/index them with pinned Nomic and Chroma under the reported resource bounds. Keep both policy blockers and all archives excluded.

**Stopped at the approval boundary.**
