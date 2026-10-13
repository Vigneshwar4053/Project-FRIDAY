# FRIDAY Phase 1E — owner-approved indexing execution report

2026-10-12. **Stopped before indexing because the mandatory aggregate resource bounds have not been established for the persistent indexing setup.** This is a blocked execution, not a completed index. No real document was retained in Knowledge SQLite, embedded, or indexed. The owner's exact-corpus authorization was revalidated and remains applicable to those same revisions.

## 1. Exact document and chunk counts

- Indexed documents: **0**.
- Indexed chunks: **0**.
- Retained real documents: **0**; real embedding calls: **0**.
- Revalidated eligible scope: **20 documents / 312 deterministic chunks**, unchanged from [the approved corpus](FRIDAY_PHASE1E_CORPUS.json).
- Both privacy blockers and both deprecated stubs remain excluded. The complete MITRE archival bundle remains outside indexing scope. Only the previously approved processed text could be activated.
- `data/intelligence/phase1e/` does not exist; no real knowledge database or Chroma collection was created.

## 2. Corpus and embedding fingerprints

| Identity | Fingerprint |
| --- | --- |
| Exact owner-approved corpus scope | `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4` |
| Nomic v1.5 registry manifest | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` |
| Full embedding/index configuration | `idx_474dc19543813c52cb4d4575f99e24c97eac2fb4c28d7ce3666a378f6e02bfc7` |
| Qwen3:4b registry manifest, unchanged | `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7` |

All source/processed hashes and provenance checks passed again, including the final post-test revalidation. All 20 revisions remain eligible and no corpus metadata was modified. Nomic's 768 dimensions, document/query prefixes, L2 normalization, cosine distance and chunker configuration match the approved manifest.

Verified **84 pinned wheels and 6,467 installed wheel payload files**, with matching versions, sizes, SHA-256 and ZIP integrity; ChromaDB remains 1.5.9 in the existing isolated environment. Verified Nomic config, weights, license and parameters against approved SHA-256 and sizes. No package/model installation or download occurred.

The first local-manifest check incorrectly assumed the on-disk wrapper must hash to the registry digest. Ollama stores a wrapper with a final descriptor referencing the original registry-manifest blob. The corrected verifier checks the original blob hash, exact registry JSON, every wrapper field and appended descriptor. Both Nomic and Qwen registry blobs match their expected digests; the wrapper difference is not a changed model. A synthetic regression test rejects altered wrapper descriptors and registry blobs.

## 3. Retrieval-quality measurements

Real retrieval accuracy and wrong-document citation rate: **not measured**. No query embeddings or retrieval calls were made. Reporting a zero error rate without an index would be misleading.

Prepared [seven real retrieval questions](FRIDAY_PHASE1E_RETRIEVAL_QUESTIONS.json), authored and checked against approved local source paragraphs: TLS versions, container capabilities, parameterized SQL, per-object authorization, file permissions, dependency disclosures, and inbound/outgoing DMZ zones. Each includes the expected exact source identifier, source URL, processed hash and answer concepts. This is a curated acceptance sample, not an independently owner-labeled benchmark.

The evaluation protocol separates expected-document top-1/top-3 retrieval accuracy from citation provenance errors. After successful bounded activation, every citation must resolve to authoritative current SQLite source/revision/chunk/document hashes; all 20 sources must be searched under their exact approved scope. No answer generation or tool execution is included.

## 4. Latency, memory and disk measurements

| Measurement | Result |
| --- | --- |
| Real indexing time | Not measured; indexing never admitted |
| Real cold/warm retrieval latency | Not measured |
| Peak additional real-indexing RSS | Not measured |
| Available RAM at host preflight | 10,337,042,432 bytes (~9.63 GiB) |
| New corpus/index/knowledge disk growth | **0 bytes** |
| Associated preflight evidence and regression log | **5,258 logical bytes / 8,192 allocated bytes** |

Source-only review and artifact hashing are not included as indexing benchmarks. Previous Phase 1C synthetic RAM/latency numbers were not substituted for real-corpus measurements.

## 5. Persistence, revocation and recovery results

Real-corpus persisted vector reopen, real source revocation and outdated-source exercises: **not performed**, because no real store was created. Existing SQLite/mock-vector contract tests pass for stale revisions, changed-document approval, revocation across reopen, upsert-before-acknowledgment replay, incremental indexing and wrong-source citation filtering. No actual approved source was revoked or revised as a test side effect.

The existing storage/adapters remain the intended implementation; no duplicate repository, vector backend or embedding provider was built. Activation requires the existing separate READ_DOCUMENT/RETAIN/INDEX authorization contracts, exact snapshot/revision validation and citation validation. Future testing must use isolated test state while preserving the production approved revisions and revocation state.

## 6. Resource enforcement and safety stop

Implemented `scripts/phase1e_admission.py` with:

- Admission checks for **100 MiB aggregate storage**, **2 GiB additional RSS**, **2 GiB minimum available RAM**, and conservative reservations before admitting work. Missing, malformed or negative resource measurements deny admission.
- Private-storage identity checking and accounting for the larger of logical and allocated bytes, with symlink/hardlink/unsafe-mode rejection and no permission repair.
- A five-minute-maximum owned-session watchdog. Tests demonstrate expiry cancels the session and terminates only a live direct child created by the runner; an unrelated child remains alive. The watchdog does not claim that terminating an HTTP client cancels inference in an external Ollama daemon.
- A separate enforcement prerequisite: polling and per-file `RLIMIT_FSIZE` cannot substitute for a verified aggregate storage quota or an isolated memory domain including the embedding process.

`scripts/phase1e_index_preflight.py` revalidates exact owner approval, source hashes/eligibility, cached and installed package artifacts, local Ollama metadata and Nomic layers, model manifests, the private storage parent, RAM admission and platform controls. It exposes no indexing, embedding or corpus-retention operation. Its exit code **2** is the expected safety denial, recorded in `data/intelligence/phase1e-owner-preflight.json`.

Concrete host findings after the approved read-only escalation:

- Project storage is on ext4 mounted `rw,relatime`, with no quota mount options. A dedicated, verified 100 MiB aggregate quota for the combined durable SQLite/Chroma storage has not been established.
- The current application cgroup has `memory.max=max`. Its controls are writable on the host, although read-only in the sandbox. No dedicated memory domain covering an owned embedding process, controller and Chroma worker has been configured or verified. Moving/capping the existing shared Ollama daemon could interfere with unrelated workloads, so it was not attempted.
- A minimal owned `bwrap` probe with a 100 MiB tmpfs succeeded outside the sandbox. It proves that a temporary bounded filesystem is possible. It does not provide a verified durable quota for the requested persistent repository, and no transient filesystem was used to silently replace durable storage. The probe ran only `/bin/true`, created no persistent host configuration, and ended immediately.
- Ollama `/api/ps` was empty during metadata preflight. No model was evicted, loaded or used for inference. A newly created process-local semaphore is not represented as a lock shared with a running FRIDAY process.
- `data/intelligence` is owner-controlled and mode 0700. The new preflight artifact is mode 0600. Regression output is protected by its existing private parent directory; existing authentication, grants and permissions were not modified.

The exact resource stop reason is: **“No verified aggregate 100 MiB storage quota; indexing must not start.”** Establishing additional infrastructure is a prerequisite for resumption. This report does not claim that the machine can never enforce the bounds; it reports that the current persistent indexing setup has not met the required enforcement checks. No requested maximum was relaxed to permit indexing.

No cybersecurity commands, scans, websites, personal files, project `.env`, personal SQLite memory, browser/voice changes, Qwen changes, live RAG routing, commit or push occurred. Existing uncommitted work was preserved.

## 7. Tests and regressions

**12 new admission/watchdog/manifest tests passed** (0.111 seconds in the targeted run). They cover exact thresholds/reservations, missing measurements, fail-closed enforcement, RAM parsing, private storage accounting, changed approval rejection, registry/wrapper tampering, watchdog expiry/ownership/disarming/duration, and no storage/embedding effects on denial.

**Full regression: 1,653 tests passed in 18.323 seconds**, including the existing dataset, foundation, adapter and Phase 1E review tests. These cover cybersecurity retrieval fixtures, wrong-source citations, revoked/stale source exclusion, prompt-injection isolation, no personal-memory access, no tool execution, batch/candidate/evidence bounds and adapter timeouts. The full suite used the approved host execution so the existing headless browser IPC tests could run. Log: `data/intelligence/provisioning/phase1e-owner-regression.log`.

`git diff --check` passed. Model-manifest verifier changes were included in both the passing targeted and full runs. Final exact-corpus revalidation passed after testing. The previous review report and approved corpus artifact remain unchanged.

## 8. Remaining work before Phase 1F

Phase 1E indexing is **blocked**, so Phase 1F live integration must not begin yet.

1. Establish and verify a durable bounded storage area covering SQLite, Chroma, sidecars and temporary/checkpoint files within 100 MiB. A quota filesystem or a thoroughly tested bounded durable arrangement is needed; changing host filesystem configuration was not attempted.
2. Establish an owned memory domain for every indexing/embedding process, and verify the additional-RSS and host-RAM monitoring policy. Reuse existing model files and adapters; protect the unrelated Ollama service and active generation. Wire the tested watchdog into that owned worker lifecycle.
3. Revalidate the still-approved exact fingerprint, then activate only its 20 current processed revisions with existing bounded authorization/indexing contracts.
4. Measure actual 20-document/312-chunk indexing, reopen persistence, isolated revocation/outdated-source rejection, the seven source-checked retrieval questions, cold/warm latency, peak additional RSS and disk growth. Repeat targeted/full regressions and whitespace checks after activation changes.
5. Only then design Phase 1F live routing and evidence presentation, with citations, revocation, memory isolation and resource controls preserved. Live FRIDAY integration remains disconnected.

No renewed corpus approval is required for the unchanged exact approved scope; additional documents or future revisions require separate owner authorization. **Stopped after reporting.**
