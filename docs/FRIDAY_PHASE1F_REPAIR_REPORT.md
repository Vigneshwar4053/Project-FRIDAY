# FRIDAY Phase 1F-R — retrieval and generation reliability repair

Date: 2026-10-13. Branch: `feature/voice-foundation`.

The repair is implemented and synthetically validated. **1,705 regression tests passed. No live Qwen generation was run.** The original BOLA request now returns insufficient approved evidence before generation. Successful live answer completion remains unverified; this phase does not claim live acceptance.

## 1. Confirmed causes and inspected contracts

The failed acceptance report and the actual retrieval, Chroma, embedding, RAG, provider, inference-profile and ModelManager implementations were inspected. Existing uncommitted Phase 1F work was preserved. `.env` was not opened or modified.

Before repair, retrieval requested eight cosine-distance candidates from all 20 approved sources. SQLite checked current revision, active consent, scope, chunk identity/hash and the exact acknowledged index generation. Selection retained whole chunks in vector order, at most three, with a 2048-byte **serialized** evidence limit. It did not check topical relevance. Full provenance was serialized into each model-facing item, including long pinned URLs, identifiers, hashes and timestamps.

The BOLA diagnostic reproduced the failure: ranks 1–7 each exceeded the serialized limit; rank 8, File Permissions, was 1885 bytes and fit. Its source and chunk IDs exactly match the failed acceptance report. Budget-based skipping promoted the first small enough candidate, irrespective of relevance. This was not a source-revision, consent, vector-mapping or embedding-prefix failure. Provenance was correct, but provenance alone did not establish support.

Generation used the existing `qwen3:4b` provider with `stream=false`, `think=false`, `num_predict=768`, `num_ctx=8192`, temperature 0.3 and a 300-second timeout. The recorded termination was `done_reason=length`, with exactly 768 generated tokens. Wall time was 120.454 seconds, below the timeout. The provider correctly rejected the partial response before citation validation. Zero released generated citations is consequently a failure result, not a citation-quality measurement.

**Confirmed generation cause:** output-token exhaustion. **Not confirmed:** why the model used all those tokens. The previous prompt specified concise statements but had no total answer-word target; validation allowed up to 12 claims of 4096 bytes each. This allowed considerably more output than the available budget, but is a plausible contributor rather than proof about the withheld response. No private reasoning or partial output was inspected or printed.

## 2. Changes made

| File | Repair |
| --- | --- |
| `friday/intelligence/models.py` | Added opt-in compact serialization containing citation handle, verified title and whole chunk text. Default full serialization and the full evidence/citation map remain available. |
| `friday/intelligence/retrieval.py` | Added explicit opt-in compact-budget accounting and an object-authorization topic guard. Object/BOLA/IDOR questions require an actual object term and authorization/access-control/permission context in the passage. Titles and underscore-separated link paths do not supply that support. Other topics keep existing vector ordering. Missing qualifying candidates receive `no_relevant_evidence`. |
| `friday/intelligence/rag.py` | Live explicit RAG enables those two selection options; a defensive topic check also runs before inference. Uses compact evidence in the delimited data message. Requests 120–200 words total, at most four claims, fewer words when support is limited. Rejects more than four claims or 200 claim-text words as a whole. Copies the supplied profile with thinking disabled and completion confirmation required. |
| `friday/models/profile.py` | Added validated `require_complete=False` response policy; existing profile defaults and runtime options remain unchanged. |
| `friday/providers/ollama.py` | Opt-in complete-response policy requires both `done=true` and `done_reason=stop`. Existing length-stop rejection stays authoritative. Ordinary chat retains its previous behavior for older responses lacking finish metadata. |
| `scripts/phase1fr_diagnose.py` | Retrieval-only, exact-scope diagnostic; prints candidate metadata, sizes and decisions. Can replay private query vectors to evaluate selection without more inference. Never calls generation, ingestion, document embedding, indexing, tools or personal memory. Its approval callback is restricted to the owner's requested RETRIEVE scope and is not installed in the application. |
| `tests/test_phase1fr_repair.py`, `tests/test_phase1f_rag.py` | Added 16 synthetic tests; retained prior privacy/security and chat regressions. |

No budgets were increased. Whole passages are not truncated. Full source authorization, source snapshots, revision/hash checks, pre-inference verification under the ModelManager gate, and post-generation citation/revocation checks remain in place. The compact payload changes what is sent to the model, not what is trusted by citation verification. No generated source claims influence selection.

## 3. Actual retrieval diagnostics and accuracy

Artifacts: [before](FRIDAY_PHASE1FR_RETRIEVAL_BEFORE.json), [after](FRIDAY_PHASE1FR_RETRIEVAL_AFTER.json). Each includes all eight ordered candidate **full source IDs, titles, chunk IDs, distances, serialized byte counts, acceptance/rejection decisions and final selected evidence** for each question. Neither contains passages.

Eight actual Nomic query embeddings were made: the seven prepared Phase 1E questions and the failed BOLA question. No Qwen calls were made. A sandboxed loopback attempt failed; the host-level retrieval-only run succeeded after approval. One diagnostic harness attempt incorrectly held the non-reentrant synchronization gate around provider execution; it failed before embedding, was corrected to own/close the gate without acquiring it, and was rerun. There were no hidden generation retries. Repair evaluations used the same private cached query vectors with zero additional embeddings.

The exact corpus, SQLite revisions/chunks/index acknowledgments and all 312 Chroma vectors were verified before and after diagnostics and replay. Corpus fingerprint remained `ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4`. Aggregate vector fingerprint remained `0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca`. All 20 documents and 312 vectors remain intact. Existing-store backend sidecar housekeeping can occur; no ingestion, reindexing or vector-content modification occurred.

### BOLA candidate decisions

Lower cosine distance is better. Full identifiers are in the two artifacts above.

| Original rank | Title | Distance | Original bytes / decision | Compact bytes / repaired decision |
| --- | --- | ---: | --- | --- |
| 1 | Authorization Cheat Sheet | 0.222990 | 2360 / byte budget | 1615 / topic mismatch |
| 2 | Bypassing Authorization Schema | 0.231582 | 2261 / byte budget | 1485 / topic mismatch |
| 3 | Authorization Cheat Sheet | 0.244878 | 2201 / byte budget | 1453 / topic mismatch |
| 4 | Authorization Cheat Sheet | 0.249153 | 2353 / byte budget | 1605 / topic mismatch |
| 5 | Logging Cheat Sheet | 0.258072 | 2347 / byte budget | 1604 / topic mismatch |
| 6 | Authorization Cheat Sheet | 0.263183 | 2053 / byte budget | 1303 / topic mismatch |
| 7 | Input Validation Cheat Sheet | 0.265234 | 2275 / byte budget | 1527 / topic mismatch |
| 8 | File Permissions | 0.273507 | 1885 / accepted as S1 | 1097 / topic mismatch |

The BOLA candidates contain authorization context but no qualifying substantive object-authorization anchors; apparent object hits in ranks 2–3 are underscore-separated link-path references. The repaired selected bundle is empty, with `no_relevant_evidence`; the application returns its explicit insufficient-evidence response and does not invoke Qwen.

The corpus is not entirely missing object authorization: Authorization Cheat Sheet has 29 chunks, seven with object and access-control anchors. Phase 1E's reviewed specific-object/every-request markers exist in the approved material. A case-insensitive scan of all 312 chunks found no `BOLA` token or `broken object` phrase. This establishes a terminology coverage limitation, **not** proof that every underlying concept is absent. The approved corpus supports general per-object permission checks; sufficient retrieved support for a dedicated BOLA explanation is not established. No source or answer was fabricated to bridge that gap.

### Seven prepared questions

| Question | First selected candidate rank before → after | Expected source selected after |
| --- | --- | --- |
| TLS versions | 4 → 1 | Yes |
| Container capabilities | 3 → 1 | Yes |
| Parameterized SQL | 4 → 1 | Yes |
| Object authorization | 8 → 8 | Yes |
| File permissions | 1 → 1 | Yes |
| Dependency disclosure | 2 → 1 | Yes |
| Network zones | 3 → 1 | Yes |

Document-level vector top-1: **6/7 (85.7%) before and after**. Document-level recall@5 over the first five vector chunks: **7/7 (100%) before and after**. These match Phase 1E. First selected evidence matches the expected document for **7/7**, and expected-source presence in the budgeted bundle remains **7/7**. The seven-question object-authorization wording differs from the failed BOLA wording: its top-1 vector source is still another document, while its qualifying Authorization Cheat Sheet chunk is at rank 8. Ranking was not changed or tuned against expected source IDs.

Some repaired bundles fit two whole chunks rather than one; every supplied source still undergoes verification. Seven curated questions authored against this same corpus are not independent accuracy evidence or an evaluation of generated factual support. The BOLA case is reported separately and is **not** counted as a successful answer.

## 4. Generation budget, thinking and finish findings

Qwen3 supports thinking controls; Ollama separates thinking and final-answer fields. The adapter already requested `think=false` in the failed request and the recorded structured response reported thinking absent. Switching from thinking mode is therefore **not** the confirmed repair for that failure. Explicit RAG now pins the supported non-thinking request even when a caller supplies a thinking-enabled profile. General chat settings are not changed. [Ollama thinking documentation](https://docs.ollama.com/capabilities/thinking).

The adapter sends only one `num_predict` output quota and provides no separate reasoning quota. If thinking is enabled, reasoning cannot be assumed free of that quota; shared-budget accounting is inferred from the single generation budget and the documented reasoning-before-answer token stream. Exact enabled-thinking token accounting for this installed runtime was not empirically tested, because that would require another live generation. It was not the observed structured-output cause here.

The runtime exposed a usable finish reason in the failed acceptance: `length`. The API exposes `done`, `done_reason`, generated-token counters and durations. RAG now requires a positive normal finish rather than interpreting missing metadata as completion. Length, incomplete, unknown or absent finish metadata, timeout, transport errors and invalid JSON/citations all withhold the whole answer. There is no partial-answer fallback or automatic retry. [Ollama chat API](https://docs.ollama.com/api/chat).

Proposed live explicit-RAG configuration: **768 output tokens, 8192 context tokens, temperature 0.3, 300-second timeout, `think=false`, `stream=false`, positive completion confirmation, 120–200 claim-text words and at most four claims**. Smaller configured budgets remain smaller; no output/timeout increase or global configuration edit was made. The bibliography is rendered by the application and is outside the model's word target. Word count is not a tokenizer measurement, so shorter instructions cannot guarantee completion within 768 tokens.

ModelManager synchronization, job queue/lifecycle, private `finally` scrubbing and source-change checks are preserved. Nomic continues using `keep_alive=0`; Qwen continues omitting `keep_alive`, preserving server residency policy. No workload was evicted. Mocked HTTP verifies mode/options/restoration and timeout behavior, but cannot prove live model compliance or measure RAM.

Resource estimate: the original observed additional peak was **3.85 GiB**, with 86.692 seconds for 768 output tokens (~8.86 tokens/second). A hypothetical 300–500-token completion at that same rate would take ~34–56 seconds of decoding, plus variable loading/prompt work; this is arithmetic extrapolation, not a new benchmark. Model weights/context settings are unchanged, so no lower peak-memory claim is justified. For the seven-question object-authorization request, evidence serialization decreases from 2030 to 1280 bytes; actual installed-model prompt tokens and latency still require measurement. The original BOLA wording currently performs no Qwen generation after retrieval.

## 5. Privacy and security verification

Synthetic tests cover authorized current-source selection, irrelevant/absent-topic rejection, exact UTF-8 budget boundaries, whole-chunk preservation, revoked-source exclusion, full citation provenance despite compact prompts, unknown/uncited citations, fail-whole word/claim limits, output exhaustion, positive/missing/invalid finish reasons, thinking configuration, timeout without retry, and no partial-answer leakage. Existing tests exercise revocation before/during generation, hostile untrusted evidence, mutex sharing, private job cleanup, context limits, exact CLI approval, source substitution and missing-store failure.

Both adaptive and ordinary explicit-RAG paths retain no personal-memory writes, no reusable conversation history, no automatic speech, no tool routing, no unauthorized command execution and no intent translation. General chat and deterministic tools retain their existing paths. No owner authorization, desktop/voice behavior, model residency policy or model selection was changed.

Diagnostics accessed only approved corpus content for integrity checks and emitted source metadata/scalar decisions. No document passages, model response text or private reasoning was logged. No personal memory was accessed by the diagnostic. Existing privacy tests use synthetic mocks; this repair performed no new live personal-memory metadata audit because no live assistant acceptance ran. Public upstream API documentation was consulted through browsing; it was not added to the knowledge corpus. No packages, models or documents were downloaded into the project, no knowledge sources were added, no active network scans ran, and no commit or push occurred.

## 6. Validation results

- Targeted command: `.venv/bin/python -B -m unittest tests.test_phase1fr_repair tests.test_phase1f_rag tests.test_ollama_final_answers tests.test_ollama tests.test_intelligence_foundation` — **105 passed in 0.893 seconds**.
- Full command: `.venv/bin/python -B -m unittest discover -s tests` — **1,705 passed in 17.941 seconds, zero skips**. Log: `data/intelligence/provisioning/phase1fr-regression.log`.
- The initial sandbox full run encountered the previously documented browser IPC PermissionError (four errors and four related cleanup failures). The owner-approved host-level rerun passed all tests; no tests were skipped or altered to hide this environment limitation.
- `git diff --check` passed.
- Metadata-only retrieval replay preserved exact corpus/vector fingerprints. All eight candidate traces are attached in JSON. No generation test contacted a real model.

## 7. Remaining limitations

Live Qwen completion with the tightened instructions is not yet demonstrated. The broad cause behind the prior output length is unknown beyond the confirmed token-limit termination. The narrow topic guard is a necessary lexical condition, not a semantic entailment proof; it can reject useful synonyms and cannot eliminate all unrelated passages containing the same terms. Other topics do not gain a calibrated relevance threshold. Citation verification proves evidence identity/eligibility and label membership, not factual entailment.

The original BOLA question currently fails safely for insufficient retrieved support. No hidden query rewrite, additional model, alternate vector database, expanded candidate limit, new source or reindexing was used. Improving recall for that exact wording or validating complete BOLA coverage is remaining work. The successful seven-question result does not resolve it.

Existing deployment constraints remain: Chroma is available in the isolated RAG environment, which lacks the normal environment's real Argon2 dependency. Process-local inference synchronization cannot exclude external Ollama clients; resident-workload checks detect observable conflicts and do not evict them. Sampling-based RAM estimates are not hard ceilings.

## 8. Exact next live acceptance procedure — separate approval required

**Do not repeat the failed BOLA request expecting generation.** Its current evidence gate deliberately withholds generation. The following is a distinct, explicitly proposed one-request generation acceptance using the previously prepared question with qualifying evidence; it does not count as acceptance of the BOLA explanation.

1. Obtain fresh owner approval for exactly one local Nomic-query-plus-Qwen-RAG request using the question below, the unchanged approved 20-source scope and the configuration in section 4. Do not infer this permission from the diagnostic authorization.
2. Revalidate corpus/index fingerprints, SQLite integrity/foreign keys, pinned installed model identities, zero unrelated resident workloads, and the existing resource admission thresholds (including at least 3 GiB available RAM). Do not evict models or change installation/authentication settings.
3. Run the existing assistant in the installed RAG environment: `data/intelligence/rag-env/bin/python -B -m friday.main`. Submit exactly:

   ```text
   answer using approved knowledge: When should the server check access permissions for a specific object or function?
   ```

4. Use the original `CLIKnowledgeApproval` terminal interaction to grant RETRIEVE **allow once** for that exact question and approved source scope. Leave the existing owner-authorization flow intact.
5. Retrieve at most eight candidates, select at most three whole topic-qualifying chunks within 2048 compact serialized bytes, and verify them before inference. If evidence or preflight fails, stop without Qwen. Do not substitute another question.
6. Run at most one Qwen request through the existing ModelManager. No retry, timeout increase, output increase or global setting change. Monitor resource scalar metrics with the existing acceptance monitoring approach; stop safely on an incident. Do not save question/passages/partial output or private reasoning in logs.
7. Require `done=true`, `done_reason=stop`, strict bounded claims JSON and verified current citations. Display only the validated answer and application-derived bibliography. Check factual support against the cited approved source during owner review. Inspect only scalar timings/token counts/finish status, peak observed RAM, verified source metadata and privacy/persistence metadata for the acceptance report.
8. Report completion, token/time/RAM measurements, citation/factual support, source continuity, no memory/history/speech/tool activity and whether the resource thresholds were respected. Any failure ends the one-request acceptance; another attempt requires new approval.

Request to the owner: approve this **distinct one-request object-authorization generation acceptance** separately if desired. This repair stops after reporting; no live Qwen request is authorized or started by this report.
