# Phase 1F-D — manual RAG failure diagnosis and repair

Date: 2026-10-16. Branch: `feature/voice-foundation`.

## Confirmed findings

The owner's TLS request returned a shared `ProviderError` fallback. Its precise historical cause **cannot be recovered from that response**. No new live query embedding or Qwen generation was performed. Live answer completion remains unverified.

The initial `git status --short`, `git diff --stat`, and `git diff --check` were inspected. The initial whitespace check passed. Existing modified files were assistant.py, chroma_index.py, intelligence/models.py, retrieval.py, main.py, manager.py, profile.py and ollama.py. Existing untracked work included rag.py, both Phase 1F reports, the manual testing guide, retrieval before/after JSON reports, phase1fr_diagnose.py and both Phase 1F test modules. All were preserved; edits extend that work. No reset, clean, restore, commit or push occurred.

Reviewed all requested source files, the two reports, the retrieval diagnostic script, existing RAG/repair tests and adjacent provider, job, permission and embedding boundaries. The diagnostic script was inspected, not executed: it can perform real embeddings and is inappropriate for this phase.

The precise fallback path is:

`FridayAssistant._respond_locked` → `RagOrchestrator.answer/_answer` → `ModelManager.generate` → `execute_job` → shared synchronization/pre-inference callback → `OllamaProvider.chat`.

`execute_job` previously retained only an error string; `generate` recreated `ProviderError(job.error)`. RAG then hid every ProviderError behind:

> Approved knowledge generation unavailable, timed out, or failed; no verified answer was returned.

This message alone does not distinguish HTTP/service failure, timeout, output exhaustion, completion-policy rejection, context limits, failed synchronization or pre-inference residency/source checks.

The older Phase 1F acceptance report confirms `done_reason=length` at 768 tokens for a **different** request. That observation must not be attributed to the owner's later TLS attempt. The current supplied state of no resident models also does not establish residency during the failed request.

## Failure boundaries and unconfirmed causes

| Boundary | Hidden failures before this repair | Current diagnosis |
| --- | --- | --- |
| Ollama HTTP generation | HTTP errors including missing model/endpoint; unreachable service; socket/read failures; direct or URL-wrapped timeout | `connection_failure`, `model_unavailable`, `generation_timeout`, or `provider_failure` |
| HTTP response decoding | Oversized transport response; invalid UTF-8/JSON; non-object envelope; backend error field | `malformed_json`, `invalid_response`, or bounded `provider_failure` |
| Completion checks | `length`; missing/false `done`; missing/unknown finish reason | `output_length` or `incomplete_output` |
| Final-content checks | Missing/non-string/empty final content, reasoning-only output, oversized result | `invalid_response` or `provider_failure`; no partial answer released |
| ModelManager | Unregistered/mismatched model, input budget, unsupported bounded profiles, empty result, unexpected provider exception | Typed `context_budget` where applicable; other unknown provider errors stay `provider_failure` |
| Synchronization | Gate acquisition/release or closed manager | `synchronization_failure`; embedding has the same category at retrieval stage |
| Pre-inference eligibility | Source snapshot changed or evidence ceased to be eligible | `source_changed` at `pre_inference` |
| Residency checks | Existing workload before embedding; external workload during embedding; conflicting generation preflight workload; owned Nomic unload wait exhausted | `residency_conflict` or `residency_timeout`; no eviction or retry |
| Retrieval/index initialization | Approved corpus/index validation, SQLite/Chroma failures, missing backend/store, query embedding or candidate validation failures | `backend_failure` during opening, `retrieval_failure` during retrieval, or typed embedding transport/residency/synchronization category |
| Retrieval permission | Denial, approval callback failure, invalid exact authorization | `authorization_denied` at `authorization` |
| Structured model answer | Invalid JSON, duplicate keys, wrong fields/types, excessive claims/text, invalid embedded markers | `malformed_json` or `invalid_structure` at `validation` |
| Citation verification | Missing/empty citations; unknown/duplicate/mistyped IDs; stale/revoked/substituted provenance | `missing_citation` or `citation_rejected`; changed post-generation snapshot is `source_changed` |
| No usable support | Empty eligible/topic/budgeted evidence, or model explicitly returns empty claims | `no_evidence`, status `insufficient_evidence` |

Malformed answer JSON and citation rejection originally used the separate fixed `KnowledgeError` grounding response. Retrieval, authorization and unexpected backend failures also had separate responses. They do not ordinarily explain the **exact** reported ProviderError fallback. A pre-inference source/residency failure or synchronization error can explain that fallback without generation ever starting. These distinctions narrow the failure boundary, but do not prove which event occurred historically.

No retained content-free record of the TLS attempt was supplied. Connection failure, output exhaustion, timeout, incomplete output and pre-inference/model-manager failure remain possible. The current repair does not infer a specific past cause or inspect withheld model content.

## Exact changes in this phase

- `friday/diagnostics.py`: fixed allowlist of safe category names; unknown categories normalize to a fixed fallback.
- `friday/providers/base.py`, `friday/intelligence/models.py`: optional typed error categories. Existing message-only callers remain valid.
- `friday/models/job.py`, `friday/models/manager.py`: carry the category through failed jobs and reconstructed ProviderError; preserve private-job message/result/error scrubbing. Categorize synchronization and input-context failures.
- `friday/providers/ollama.py`: classify connection, timeout, response decoding, missing endpoint/model, output-limit and completion failures. RAG's profile can request `format="json"`; ordinary chat keeps its existing payload behavior.
- `friday/models/profile.py`: validated `json_output=False` option. Existing budgets and defaults are unchanged.
- `friday/intelligence/ollama_embeddings.py`: preserve connection, timeout, synchronization and resident-workload categories without including exception text.
- `friday/intelligence/retrieval.py`: tag its existing source-snapshot rejection with `source_changed`; existing Phase 1F-R selection policy stays in place.
- `friday/intelligence/rag.py`: retain one bounded `last_status` per request, classify validation failures, enable JSON mode for explicit RAG and request 60–100 words rather than 120–200. Safe user failures no longer echo arbitrary KnowledgeError text. Optional scalar-only display is separate from answer text. Generation counters are copied only when this request actually invoked the provider, preventing stale metrics after a preflight failure. A backend cleanup failure overrides any provisional success and withholds the answer.
- `friday/main.py`: add independent `--rag-diagnostics` flag and pass it to the lazy orchestrator. It does not enable adaptive mode or change desktop/voice logic.
- `tests/test_phase1fd_diagnostics.py`: 12 synthetic diagnostic/reliability tests with mocked HTTP and synthetic SQLite evidence. Existing Phase 1F tests remain; one backend-error assertion now checks the generic response plus typed stage/category rather than requiring exception text in user output.

## Structured answer contract and budgets

The structure remains:

```json
{"claims":[{"text":"One concise supported statement.","citations":["S1"]}]}
```

The only top-level field is `claims`; each claim has exactly `text` and `citations`. Supplied IDs are `S1` through at most `S3`; membership is checked against the actual retrieved bundle, not merely a label pattern. At most four claims, one to three unique citations per claim, 4096 UTF-8 bytes per nonempty claim text and 200 words across claim text are accepted. Duplicate keys, unknown fields, embedded URLs/markers/bibliography, missing support and malformed structure reject the entire answer. An empty claims list reports insufficient evidence.

JSON mode constrains syntax; application validation remains authoritative for structure and evidence. Source eligibility, current revisions/hashes, approved document metadata, pre-inference and post-generation snapshots and citation verification remain required. No fabricated citations, output repair, partial JSON recovery, uncited fallback or retry was added.

Unchanged standard budget: **768 output tokens, 8192 context tokens, 300-second timeout**, existing input limit, temperature 0.3, `think=false`, `stream=false`, and mandatory `done=true` with `done_reason=stop`. Custom smaller budgets remain honored. The shorter word target provides headroom for JSON overhead within the same quota; word count is not a tokenizer measurement and does not guarantee completion. No budget or timeout increase was made or proposed for automatic application.

## Safe diagnostic status

`last_status` retains only the following fields in memory, replacing the previous request's status:

| Field | Allowed shape |
| --- | --- |
| `status` | `success`, `failed`, `insufficient_evidence`, `cancelled` |
| `failure_stage` | null, `request`, `backend`, `retrieval`, `authorization`, `pre_inference`, `generation`, `validation` |
| `failure_category` | null or allowlisted fixed category |
| `done_reason` | null, normalized `stop`, `length`, `unspecified` |
| `output_token_count` | null or nonnegative integer bounded by 2^63−1 |
| `retrieved_evidence_count` | bounded integer 0–8; valid generation bundles remain limited to three |
| `citation_validation_status` | `not_run`, `rejected`, `verified`, `no_claims` |
| `elapsed_seconds` | nonnegative rounded seconds, capped at 86400, including approval and backend lifecycle |

`rejected` covers failure of the structured-answer/citation validation boundary; use `failure_category` to distinguish JSON syntax from actual citation rejection. A source change detected before entering that boundary leaves it `not_run`. A cleanup exception after successful citation checks can yield `failed` with `verified` citations: no answer is released in that case. Null counters mean no trustworthy metric was available; they are not zero-token measurements. `unspecified` deliberately does not echo an arbitrary backend finish string.

Full category vocabulary: `model_unavailable`, `provider_failure`, `connection_failure`, `generation_timeout`, `output_length`, `malformed_json`, `invalid_structure`, `citation_rejected`, `missing_citation`, `retrieval_failure`, `authorization_denied`, `synchronization_failure`, `residency_conflict`, `residency_timeout`, `source_changed`, `context_budget`, `incomplete_output`, `invalid_response`, `backend_failure`, `invalid_request`, `evidence_budget`, `no_evidence`, `cancelled`, `model_mismatch`.

Ordinary users keep safe generic failure responses. CLI diagnostic display requires explicit `--rag-diagnostics` **and** interactive stdin/stdout. This assumes the existing trusted local owner terminal; it is not new identity authentication or a permission grant. Knowledge access still requires the original exact-scope allow-once approval. Display is separate from answer text and bypasses neither evidence checks nor PRIVATE speech metadata.

No raw questions, retrieved passages, model output/thinking, exception messages, credentials, authentication values or personal memory records enter diagnostic status. No diagnostic logger or database write was added. Terminal output can still be captured externally by the owner; do not redirect a manual interactive assistant session into a transcript containing private content.

## Validation

Targeted command:

```text
.venv/bin/python -B -m unittest tests.test_phase1fd_diagnostics tests.test_phase1f_rag tests.test_phase1fr_repair tests.test_ollama tests.test_ollama_final_answers tests.test_model_runtime tests.test_cli
```

**110 passed in 0.496 seconds.** Coverage includes successful structured answers and verified citations; invalid/missing citations; length exhaustion despite apparently valid JSON; generation timeout, including URL-wrapped timeout; malformed JSON/duplicate keys; unavailable Ollama; source revocation before/during generation; no evidence; authorization; synchronization; embedding transport/residency; stale-metric isolation; failure during backend cleanup; opt-in/TTY display gating; unchanged non-RAG payloads; hostile evidence; private memory/history isolation; no automatic speech; and no unauthorized routing/tool execution.

Full command: `.venv/bin/python -B -m unittest discover -s tests`.

**1,717 passed in 14.001 seconds, zero skips**, including the final diagnostic cleanup correction.

The initial sandbox run discovered 1714 tests and encountered four existing headless-browser IPC errors plus four related cleanup assertion failures (`PermissionError`). The permitted host run passed 1714 tests, and an intermediate run passed 1716. Final verification includes the additional cleanup-failure test. No browser tests were skipped or modified. Logs contain test results, not private request/response data:

- `data/intelligence/provisioning/phase1fd-regression.log` — initial sandbox limitation.
- `data/intelligence/provisioning/phase1fd-regression-host.log` — final complete host run.

Final `git diff --check`: passed.

## Remaining limitations and owner's manual procedure

Live Qwen syntax compliance, completion within 768 tokens, elapsed time, factual support and installed-runtime behavior are unverified by mocks. Citation identity does not prove factual entailment. The existing narrow object-authorization topic guard does not calibrate TLS relevance. No retrieval ranking or corpus change was made. Process-local synchronization cannot exclude external Ollama clients; existing resident checks detect observable conflicts without eviction. HTTP generation remains synchronous. Unknown provider/backend failures intentionally remain bounded fallback categories.

For the owner to perform the next live test manually:

1. Use the existing installed models, approved corpus and index. Ensure no other client is using Ollama and no models are resident; do not evict another workload or change budgets for this test.
2. From the project root, launch:

   ```text
   ./data/intelligence/rag-env/bin/python -B -m friday.main --rag-diagnostics
   ```

3. Enter the same explicit TLS request in the interactive owner terminal. Review the original knowledge scope prompt and choose allow once if appropriate. No approval is inferred from this report or diagnostic flag.
4. Observe the `Approved knowledge diagnostic:` JSON line and the ordinary result. Record only its safe status fields. If generation fails, use `failure_stage`, `failure_category`, normalized `done_reason` and token count to identify the next repair. Do not save passages, model content, private reasoning or the interactive session transcript to logs.
5. A completed answer must include application-rendered verified sources, status `success`, normalized `stop` and `citation_validation_status=verified`. Review each claim against its cited approved source. Insufficient evidence is a safe refusal, not live answer acceptance.
6. Stop after that attempt. Do not automatically retry, increase tokens/timeouts, install dependencies, change models, edit the corpus or reindex. A budget change, if later justified by observed scalar diagnostics, requires owner approval.

No live inference, model/dependency downloads, indexing, approved-corpus changes, private-user-file inspection, active scans, desktop/voice feature modifications, commit or push occurred in this phase. The project `.env` was not inspected or edited. Work stops after reporting; the owner conducts live testing.
