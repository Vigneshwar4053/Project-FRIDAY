# FRIDAY v0.4 Phase 6D — Adaptive Workload Management

## Baseline and delivery

Repository `/home/vigneshwar/Projects/FRIDAY`, branch `feature/safe-tool-system`,
HEAD **084c307fcd23151b70de9da37eab793046b31d70**. Preflight tree was clean and
**649 tests passed in 2.170s**, with no failures/errors/skips. No AGENTS.md was
found in the repository. Inspected actual CLI, assistant, routing/navigation/file
context, translator, registry/manager/permission boundaries, settings, Ollama
provider, model job/queue/runtime, native synchronization and baseline tests.
No reset, stash, merge, rebase, commit, push or tag occurred.

The new mode is **opt-in**, through Settings.adaptive_workloads or CLI --adaptive.
All 649 existing tests remain unchanged: several explicitly require greetings to
call the model and preserve their resulting history/errors. Enabling adaptation
by default would contradict those tests. An optional preference question was
raised; work proceeded with the stated compatibility-preserving rollout assumption.
This is a documented deviation in defaults, not a permission/security exception.
Use --adaptive for the requested L0–L3 behavior; compatibility mode retains Phase 6C.

## Final release summary

The final suite passes **770 tests: 649 original baseline tests plus 121 new
Phase 6D regressions**, with no failures/errors/skips. Public live L2 and L3 checks
succeeded; the owner independently confirmed successful L3 analysis. CPU-only
qwen3:4b remains slow and bounded output does not guarantee completion.

Final working-tree scope: **10 tracked modified files and 12 created untracked
files**. Recommend committing **21 files: 10 modified and 11 created**. The remaining
file, PHASE_6D_BENCHMARK.json, is historical generated data from before the final
inference profiles; leave it untracked, exclude it from the commit, and do not
delete it. Source/tests and this artifact are unchanged by release cleanup.

The current profiles and final verification below are authoritative. Sections
explicitly marked historical retain earlier checkpoint measurements; their counts,
profiles and service availability describe those checkpoints rather than release.

## Architecture

One assistant, one configured provider, one ModelManager and the existing native
POSIX mutex. Workload decisions are structured data: level, fixed reason, profile
name, inference-needed and optional conventional local response. They are neither
ToolRequests nor authorization flags. Exact L0 recognition cannot swallow mixed
actions. Existing deterministic routes/trusted references choose L1; normal and
hybrid requests use L2. Only explicit analysis patterns choose L3; no model call
is used to choose a workload.

```text
User → exact local greeting? → L0 reply, no model/tool/memory save
     → existing deterministic routing / trusted reference / safe refusal
        → L1 → existing ToolManager → unchanged Phase 6B permissions → tool
     → unmatched hybrid intent → L2 bounded JSON proposal → existing validator/tools
     → ordinary chat → L2 bounded conversation
     → explicit deep analysis → L3 bounded conversation, no autonomous tool use
```

Mixed deep/action requests require a supported command first. Verified one-use
file context can support a narrow deep follow-up without a reread. list this folder
is a small reuse of the existing NavigationManager current identity, not a new
navigation or execution subsystem; it still requires current permissions.

Per-request profile state enters/restores inside ModelManager's synchronization
boundary. ModelJob carries a keyword-only profile so older positional APIs remain
compatible. Existing queue semantics, native C implementation, model identity and
startup-only synchronization fallback are unchanged.

## Files

Created:

- friday/core/workload.py: conservative classifier and redacted immutable metrics.
- friday/core/context.py: whole-turn selection with mandatory-data overflow denial.
- friday/models/profile.py: frozen validated option/context/timeout budgets.
- tests/test_workload.py: 82 offline unit/integration/security/CLI regressions.
- tests/phase6d_benchmark.py: reproducible temporary-fixture fake/opt-in-live harness.
- PHASE_6D_BENCHMARK.json: historical aggregate-only offline results; untracked,
  unchanged and excluded from the recommended commit.
- tests/test_ollama_final_answers.py: 11 final-answer/privacy regressions.
- tests/test_l2_reliability.py: 14 completion/profile/metric regressions.
- tests/test_l3_reliability.py: 14 deep completion/privacy/benchmark regressions.
- tests/phase6d_l2_benchmark.py: opt-in public L2 comparison harness.
- tests/phase6d_l3_benchmark.py: opt-in public L3 alternatives/current harness.
- PHASE_6D_REPORT.md: this report.

Modified:

- friday/config/settings.py: adaptive/diagnostic flags and standard/deep profiles.
- friday/core/assistant.py: workload integration, bounded context, last-response
  measurements, legacy compatibility path.
- friday/core/file_context.py: narrow explicit just-read/deep snapshot references.
- friday/core/navigation.py: guarded list this folder/directory intent.
- friday/main.py: --adaptive/--diagnostics and opt-in aggregate stdout output.
- friday/models/job.py: validated keyword-only profile metadata.
- friday/models/manager.py: bounded profiled jobs and provider-call instrumentation.
- friday/providers/ollama.py: request-scoped options/timeouts and transport limits.
- friday/tools/intent_translator.py: reuse the standard profile without weakening
  the JSON/512-token/no-thinking contract or proposal validator.
- README.md: rollout, configuration, privacy, benchmarks and owner instructions.

Final Git scope: **10 tracked modified + 12 untracked files**. All 649 original
baseline tests remain unchanged. Added Phase 6D profile expectations were updated
during the deliberate L3 budget refinement; security assertions remain intact. No filesystem policy/grant/permission source or native C source
was modified, and no Phase 6E implementation was started.

## Profiles and context

| Setting | Standard L2 | Deep L3 |
|---|---:|---:|
| think | false | true |
| num_predict | 768 | 2048 |
| num_ctx | 8192 | 8192 |
| temperature | 0.3 | 0.4 |
| HTTP timeout seconds | 300 | 450 |
| max_context_bytes ceiling | 24576 | 32768 |
| max_history_messages | 6 | 16 |
| effective conservative input-byte cap | 6912 | 5632 |

The effective cap is min(max_context_bytes, num_ctx - num_predict - 512), using a
conservative byte-per-possible-token proxy and template/output reserve. It is not
an installed Qwen tokenizer. More output with the same context size reduces input
room. No claim that larger token budgets improve quality or reduce peak CPU/RAM.

Profiles validate finite values, positive bounded timeouts, token/context maxima,
complete history pairs and output/template room. Unknown options cannot be passed.
Only documented num_predict/num_ctx/temperature fields are forwarded to /api/chat;
timeout controls urllib. Model name and global server configuration are
not changed. The bug fix adds top-level request-scoped think=false for L2 and
think=true for L3; this boolean is validated in the profile. Intent mode remains JSON/think=false/temperature=0 and <=512 tokens.
Profiled HTTP responses are capped at 256 KiB (intent transport 64 KiB), and final
profiled answer bytes at 64 KiB. Failed calls are not retried or downgraded to
unbounded inference. Non-profile-capable providers fail before chat execution.

Recent complete turns are dropped oldest first. System/current/verified temporary
snapshot stay intact; no automatic summaries or silent data cuts. Oversized
mandatory context fails before the provider. Memory annotations reflect actually
selected turns. Ordinary SQLite records remain untouched, and the existing normal
in-session history retention policy is unchanged; only prompt selection is bounded.
Large existing 16-KiB snapshots can exceed the conservative default budget. This
limitation is intentional and user-visible, rather than inventing a shorter factual
source. Snapshot expiry/privacy/untrusted-data instructions and job scrubbing remain.

Official option references: [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)
and [parameter documentation](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx).
The installed Ollama service reported 0.40.0 and public live profile checks passed.
L2 and L3 timing/completion results appear below, with owner confirmation of L3.
Exact tokenizer budgets and broad answer quality remain unverified; the byte proxy
is intentionally conservative. Initial offline work had no reachable service.

## Instrumentation

Nanosecond classification, deterministic routing/reference planning, provider.chat
latency, total response, invocation attempts, Python process CPU and Linux lifetime
peak RSS. Most recent response only, in memory. Diagnostics are opt-in stdout JSON,
not stored to SQLite or files. No prompts, file bodies, paths, credentials, tool
outputs, authorization decisions or timestamps. The public benchmark JSON uses
only fixed public scenario labels and aggregate measurements.

Python CPU/RSS do not measure the separate Ollama process. Peak RSS is cumulative
for this Python process and cannot be attributed to a single request. Provider
latency includes client/network/parsing and excludes native-lock waiting; total
response includes waiting/approval. No approximate model memory/CPU number is
invented. Timeout is an HTTP timeout, not a guaranteed full-request or process CPU
limit. Measurement itself introduces small overhead; opt-in level/timing output
can reveal interaction patterns despite removing sensitive content.

## Historical offline benchmark methodology and results

Command: `PYTHONPATH=. .venv/bin/python -B tests/phase6d_benchmark.py --samples 3`.
Personal configured read roots/store/identity are explicitly replaced by fixture-only
configuration. Each scenario/sample starts with fresh temporary public fixtures, real ToolManager,
read/list authorization, memory and existing native C mutex. Known-file listing
setup is excluded from its timing/provider count. Fake provider has no synthetic
sleep or live inference. Three samples per case/mode; medians of wall/CPU/provider
latency/calls are recorded, and errors counted. All scenarios succeeded.

Baseline is the retained Phase 6C compatibility execution path **under the shared
new instrumentation**, not a pristine 084c307 process timing. This reproduces the
old behavior/call paths, but cannot establish a commit-to-commit live speedup.
Results are order/environment/cache sensitive; fake-provider comparisons measure
local plumbing only. This historical artifact predates final profiles and is not
release timing evidence. Later live results are separate below; no CPU/RAM savings
are inferred. Keep PHASE_6D_BENCHMARK.json untracked and outside the commit.

| Mode | Scenario | Level | Median wall ms | Median Python CPU ms | Python lifetime peak RSS KiB | Calls/request | Errors |
|---|---|---|---:|---:|---:|---:|---:|
| phase6c_compatibility | A_greeting | legacy | 0.3298 | 0.3328 | 33196 | 1 | 0 |
| phase6c_compatibility | B_folder | legacy | 1.4028 | 1.4003 | 33196 | 0 | 0 |
| phase6c_compatibility | C_known_file | legacy | 1.4821 | 1.4849 | 33196 | 0 | 0 |
| phase6c_compatibility | D_standard | legacy | 0.3285 | 0.3312 | 33324 | 1 | 0 |
| phase6c_compatibility | E_deep | legacy | 0.1452 | 0.1474 | 33324 | 1 | 0 |
| adaptive | A_greeting | L0 | 0.0247 | 0.0265 | 33324 | 0 | 0 |
| adaptive | B_folder | L1 | 1.4675 | 1.4696 | 33324 | 0 | 0 |
| adaptive | C_known_file | L1 | 1.5062 | 1.4803 | 33324 | 0 | 0 |
| adaptive | D_standard | L2 | 0.3438 | 0.3457 | 33452 | 1 | 0 |
| adaptive | E_deep | L3 | 0.3949 | 0.3970 | 33452 | 1 | 0 |

Adaptive call counts are 0/0/0/1/1 versus compatibility 1/0/0/1/1. Greeting eliminates
a provider call in this harness; deterministic tools were already model-free in
Phase 6C. Standard/deep still use one call; additional profile/context validation
can increase local overhead. Raw aggregate evidence is PHASE_6D_BENCHMARK.json.
Synchronization backend reported Native C (POSIX mutex). Python peak RSS increases
across the same process and does not describe Ollama or prove a mode's memory use.

Optional live command: same harness with --live --samples 1, at most two samples
allowed. Uses existing qwen3:4b, public synthetic prompts/files, no downloads,
process launches or shell commands. Cold/warm service effects remain uncontrolled;
errors are counted without dumping private prompts or exception text. Live calls
are explicitly opt-in and should not be compared as causal performance claims.

## Security and test coverage

121 new tests cover Phase 6D: 82 workload/context/profile tests, 11 final-answer
tests, 14 L2 reliability tests and 14 L3 reliability tests. They exercise
exact/mixed greeting selection, route priority, profiles and
option forwarding/restoration, intent contract preservation, context history/byte
limits, overflow denial, provider failures/unsupported profiles, classifier failure,
request-scoped synchronization, redacted metrics, CLI diagnostics and reproducible
benchmark scenarios/counts. Existing 649 tests are unchanged and remain passing.

Security regressions explicitly cover L0 no model/tool/permission/memory save,
L1 ToolManager/approval, L2/L3 output not executable, deep mode no read bypass,
Deny and exact-operation Allow once, persistent read/list versus writes,
sensitive/symlink/ZIP refusal, trusted known-file reads, navigation/back/home,
verified file-context reuse without reread, no SQLite/diagnostic body persistence,
and no model-created paths or trusted listings. Forbidden execution AST inspection
and existing native/permission/routing suites are included in final checks below.

## Remaining risks and next steps

- CRITICAL/HIGH: No new unresolved issue identified within offline review scope.
- MEDIUM: Public live profile acceptance/completion passed, but exact tokenizer
  validation and broad latency/quality characterization remain absent. Byte
  budgeting is conservative rather than exact tokenization. Large snapshots
  may fail cleanly even when English text would fit the model.
- MEDIUM: HTTP timeout/native-lock waiting are not OS CPU quotas or hard scheduling
  deadlines. No automatic CPU-load/RAM control, worker cancellation or thread-safe
  assistant scheduling was introduced. Existing single-threaded runtime remains.
- MEDIUM: Existing heuristic sensitive exclusions, filesystem concurrent mutation/
  inode reuse, OS memory trust and model explanation/prompt-injection limitations
  remain; workload choice provides no new authority.
- LOW: Opt-in rollout preserves old tests/defaults; a future reviewed default change
  must explicitly update greeting/history expectations rather than weaken tests.
- LOW: Normal history/storage retention, live whole-Ollama CPU/RSS measurement,
  tokenizer-aware budgets and repeated public warm/cold trials are future work.

Owner: start `.venv/bin/python -B -m friday.main --adaptive --diagnostics`.
Run hello friday / thank you (L0), open downloads / open portfolio / open data.js
(L1 with unchanged approvals), explain this code (L2 verified snapshot or safe
budget error), explain Python decorators (L2), think deeply about the security
architecture (L3), go back / go home (L1). Folder/file examples require returned
entries. Observe `[Workload]` level/profile/invocations without printing private
context. Instructions and expected behavior are also in README.md.

Ready for review after final validation. Changes remain uncommitted. No Phase 6E
feature, model installation, global Ollama change or Git mutation was performed.

## Final release verification

| Check | Result |
| --- | --- |
| Full unittest discovery | **770 passed; 0 failures, errors or skips** |
| New Phase 6D regression tests | 121 passed |
| Existing baseline tests | 649 preserved unchanged and passing |
| Focused filesystem permission tests | 94 passed |
| Focused file-reference tests | 67 passed |
| Focused navigation tests | 44 passed |
| Focused semantic-location tests | 87 passed |
| Focused intent-translation tests | 81 passed |
| Focused routing tests | 28 passed |
| Native synchronization tests | 31 passed |
| Model runtime tests | 25 passed |
| Memory tests | 22 passed |
| Phase 6C temporary-fixture production demo | A–P passed with fake model and real native synchronization |
| Historical offline benchmark | 10 aggregate rows, 3 samples per scenario/mode, zero errors; predates final profiles |
| Final public live verification | L2 identity/decorators and L3 analysis completed; detailed results below |
| `make -C native/sync` | Passed; build already current |
| In-memory syntax validation | 65 source/test files passed |
| Production import validation | 44 modules passed |
| Forbidden execution API inspection | Production AST checks passed |
| `git diff --check` | Passed |

Focused counts overlap the full suite and are not additional tests. Context tests
also cover invalid Unicode; unavailable Python RSS measurements are safely reported
as null without breaking responses. Live L2/L3 inference was subsequently verified
using public prompts, and the owner confirmed L3; no private data was benchmarked.

Final delivery: **10 tracked files modified and 12 files created**, all uncommitted.
Recommend 21 files for commit; exclude the historical benchmark JSON without deleting it.
Branch remains `feature/safe-tool-system`; HEAD remains `084c307`. Native source,
existing baseline tests, filesystem policy and permission enforcement files remain
unchanged. Review the opt-in rollout and conservative context limits before enabling
this mode as a future default.


## Historical checkpoint — reasoning-output bug fix

Owner observed an approximately 70-second L2 response consisting of deliberation
without a useful answer. Inspection found that the provider already sent
`think=false` by default and stripped tagged reasoning, but accepted arbitrary
untagged `message.content` and ignored `done`/`done_reason`. Thus a truncated,
untagged reasoning response could be treated as successful and saved. That backend
acceptance defect is confirmed; the precise live model/template behavior and token
exhaustion are hypotheses because the original response metadata is unavailable.
The local model metadata endpoint was unavailable during this fix; no live inference
or latency improvement is claimed.

Ollama documents separate thinking/content channels and a top-level thinking
control: [thinking documentation](https://github.com/ollama/ollama/blob/main/docs/capabilities/thinking.mdx),
[chat API](https://docs.ollama.com/api/chat). Qwen documents switchable thinking
behavior for the original model: [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B).
Installed model variants/templates may differ, so no model is replaced or downloaded.

Changes relative to the completed Phase 6D working tree:
- friday/providers/ollama.py: completion-status validation and conservative unmarked
  reasoning-prefix rejection; profile thinking control is forwarded explicitly.
- friday/models/profile.py: validated boolean think field, L2 false and L3 true.
  L3 retains 1024 tokens/450-second timeout; L2 retains 512 tokens/300 seconds.
- tests/test_ollama_final_answers.py: 11 new offline regressions.
- README.md and this report: updated behavior and limitations.

Only message.content after existing tag filtering can be returned; message.thinking
never becomes display/history data. A length stop, explicit incomplete response,
unknown stop reason, empty answer or recognizable unmarked deliberation raises a
fixed ProviderError before assistant history/SQLite persistence. No retry, fabricated
answer, alternate tool, authorization change or automatic output-budget increase.
Provider error/job diagnostics never include generated text. Tests exercise both
levels, JSON intent precedence, profile restoration, CLI output, SQLite exclusion,
failed job results, redacted diagnostics and legitimate final answers.

Validation: baseline **731 passed in 2.428s**; final **742 passed in 2.403s**,
zero failures/errors/skips. New focused regressions: **11 passed**. Native
synchronization: **31 passed**. `make -C native/sync` passed, already current.
Syntax/import validation and `git diff --check` passed. Existing permissions,
filesystem, navigation and native sources are unchanged by this bug fix.

Remaining limitations: prefix rejection is a conservative heuristic, with possible
false positives and unrecognized untagged reasoning. Completion metadata absent in
older adapters is accepted for compatibility, so their truncation cannot be proven.
A token-limit stop rejects even a partial useful answer. More output tokens do not
ensure quality or lower CPU usage. L3 thinking may consume its bounded budget;
it fails cleanly rather than weakening the limit. Existing historical SQLite rows
or backups may retain previously stored material; none are deleted or rewritten.
The earlier fake benchmark measurements precede this fix and do not verify live
thinking-mode performance. Owner should verify installed model support locally.

Live test: `.venv/bin/python -B -m friday.main --adaptive --diagnostics`, then
`hello friday`, `do you know who am i`, `explain Python decorators`,
`think deeply about the security architecture`, and ordinary folder/file/navigation
commands with unchanged approvals. L0 remains model-free, L2 returns a final answer
or safe error, and L3 returns only a final answer or explicit budget/completion error.
No reasoning text should appear in responses or diagnostics. Stop without any Git
mutation: branch feature/safe-tool-system and HEAD 084c307 remain unchanged.


## Historical checkpoint — L2 performance/reliability refinement

The owner reported a clean identity response taking approximately 65 seconds and a
47-second decorators response ending in a token-limit error. Prior provider logic
used L2 512 output tokens, temperature 0.4, context 8192, think=false and up to six
history turns, with no concise-answer instruction. A long answer (or unexpected
thinking) can consume that finite output budget. Timing alone does not identify
whether prompt evaluation, loading, thinking or final generation dominated.
The original raw metadata is unavailable, so exhaustion cannot be attributed to
thinking conclusively. A higher budget alone can increase latency.

Read-only local checks outside the network sandbox confirmed **Ollama 0.40.0** and
installed qwen3:4b capabilities completion/tools/thinking. Configured stops are
`<|im_start|>` and `<|im_end|>`; repeat_penalty=1, temperature=0.6, top_k=20 and
top_p=0.95. The model template contains a thinking prefix. Template text alone does
not show whether request-level think=false is honored: Ollama's parser/template
handling and returned thinking/content channels determine observable behavior.
Request-level profile temperature overrides the model default. No model/template,
server global settings or stop sequences are modified by this change.

Official [Ollama completion implementation](https://github.com/ollama/ollama/blob/main/llm/server.go)
distinguishes normal stop from length exhaustion. `done=true` indicates generation
ended, not that its text completed naturally. The old length rejection is correct;
we do not accept a length response just because it contains punctuation, a seemingly
complete paragraph or a small token count. Conversely a `stop` response is accepted
even at the configured token budget. Empty reason strings are now accepted along
with absent/null legacy reasons; malformed/unknown reasons and done=false still
fail. Legacy metadata cannot prove completeness. No reason is inferred from counts.

Defaults at the L2 checkpoint: **L2 num_predict=768, num_ctx=8192, temperature=0.3, think=false,
HTTP timeout=300 seconds, max_history_messages=6**. At that checkpoint L3 remained 1024 tokens,
think=true, 450 seconds, history16. L2 prompt guidance asks for a direct answer,
normally no more than150 words and one small example; it is added before bounded
context selection, including verified-file explanation prompts. It does not apply
to L3 or change JSON translator contracts. Mandatory verified data remains intact;
new standard effective input cap is6912 bytes. No private content is reread or saved.

Additional changes: standard_profile factory and concise instructions in
friday/models/profile.py; Settings selects that factory; assistant budgets the L2
instruction; provider handles empty completion reasons and exposes only validated
scalar latest-request metrics. The provider metrics reset before each call and
include tokens/durations, computed generation tokens/second and a thinking-present
boolean, never message text/prompts/paths or approval choices. Metrics remain in
memory and are not automatically logged or sent to SQLite. Official metric units:
[Ollama usage documentation](https://github.com/ollama/ollama/blob/main/docs/api/usage.mdx).

New tests/test_l2_reliability.py covers normal completions at/below budget, real
length stops, legacy completion variants, malformed metadata, invalid/missing
metric values, metrics reset/redaction, standard/deep prompt/option distinction,
and native gate lifecycle in the benchmark. New tests/phase6d_l2_benchmark.py is an
explicitly opt-in live harness using fixed public identity/decorators prompts,
existing ModelManager and native synchronization, no SQLite or filesystem tools,
no raw-output logging and no retries. The first harness attempt held the native gate
twice and failed before inference (zero model calls); corrected to close the gate
without holding it around ModelManager. Those failed attempts are not timing evidence.

Validation: starting suite **742 passed in2.541s**; updated suite **756 passed
in4.652s**, zero failures/errors/skips, **14 new regression tests**. Focused native
synchronization **31 passed**, native build passed, changed-source syntax/production
imports passed. All existing tests remain unchanged. Existing authorization,
file/navigation/semantic routing, privacy protections and native source are intact.

Owner live commands and the aggregate benchmark procedure are in README. Use one
sample first (four requests with --baseline); at most two samples. No whole-Ollama
CPU/RSS metrics are measured. Cold/warm loading, order and minimal fresh context
prevent claiming controlled end-user latency gains. The previous fake benchmark
artifact remains historical and predates these profile changes.

### Actual local qwen3:4b measurements

A real opt-in run of the corrected public-prompt harness completed four requests
through the existing ModelManager/native mutex. No prompts/answers/file bodies
were logged by the harness; it reported the following aggregate metrics:

| Profile / scenario | Wall seconds | Prompt tokens | Output tokens | Generation seconds | Generation tokens/s | Load seconds | Completion |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Previous L2 / identity | 43.3024 | 36 | 432 | 38.3536 | 11.2636 | 4.3080 | stop, success |
| Previous L2 / decorators | 44.0097 | 34 | 512 | 43.5940 | 11.7447 | 0.0027 | length, safely rejected |
| Revised L2 / identity | 23.9631 | 96 | 278 | 22.5115 | 12.3492 | 0.0021 | stop, success |
| Revised L2 / decorators | 24.9106 | 94 | 301 | 24.5414 | 12.2650 | 0.0021 | stop, success |

Each scenario used exactly one model call. All requested think=false and all had
an empty separate message.thinking channel. This is observable evidence consistent
with thinking disabled, not proof that every model/template suppresses internal
computation or unmarked deliberation. Existing final-answer filtering remains.
The public identity scenario deliberately supplies no real user identity or history.

The decorators exhaustion is reproduced locally: generated512 tokens with length,
not a normal stop misclassified by the provider. The main measured cost was output
generation, not hidden thinking in the separate channel. Concise guidance produced
shorter completed outputs in this trial despite raising the cap to768. The previous
identity response also generated432 tokens. This confirms verbose output under a
small hard cap as an actionable contributor; the owner's longer-context identity
latency may additionally include history evaluation/loading costs. No causal
attribution of the owner's entire65-second delay is possible without its counters.

These four results are one sample per scenario/profile, in previous-then-current
order, with a cold first request and warmed later requests, different prompt
instructions and stochastic decoding. They are not a controlled percentage speedup,
CPU/RAM saving or latency guarantee. The comparable warm decorators trial suggests
useful improvement worth owner retesting. Token throughput is eval_count /
(eval_duration /1e9), excluding loading and prompt processing, and is not overall
response tokens/second. No Ollama process CPU/RSS is measured. Model/server settings
and L3 are unchanged; no installation or global configuration change occurred.

Final checks: full suite **756 passed**, no failures/errors/skips; native tests31
passed; native make passed; syntax/import, forbidden execution API inspection and
`git diff --check` passed. Changes for this refinement are profile.py, settings.py,
assistant.py, ollama.py, README.md, PHASE_6D_REPORT.md, plus the two new L2 test/harness
files. No existing tests, filesystem permission/rules, navigation or native sources
were changed. All work remains uncommitted for owner review.


## L3 reliability investigation and final-answer policy

The owner observed L3 exhaustion after 107.8 seconds without a final answer or
reasoning leak. Preflight suite: **756 passed in 2.565 s**, branch
feature/safe-tool-system, HEAD 084c307. All prior uncommitted changes were preserved.

The old L3 profile requested think=true, num_predict 1024, num_ctx 8192, temp 0.4,
timeout 450 seconds and history 16 messages. The total-output cap can be consumed
before the separate thinking phase finishes. Length is truncation even with
done=true; completion handling correctly refused to display or save failed output.

### Public local alternatives benchmark

Measured with installed qwen3:4b through the existing ModelManager/native gate.
One fixed hypothetical security architecture, no private files/history, one attempt
per mode, no raw prompts, answers or reasoning logged:

| Mode | Cap / think | Wall seconds | Prompt tokens | Total output tokens | Generation tokens/s | Completion | Thinking / final present |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Previous L3 | 1024 / true | 90.9858 | 64 | 1024 | 11.4116 | length, rejected | true / false |
| Larger thinking + concise guidance | 2048 / true | 90.9800 | 146 | 993 | 11.1567 | stop, success | true / true |
| Direct deep + concise guidance | 1024 / false | 91.8551 | 134 | 1024 | 11.2153 | length, rejected | false / true (partial) |

Root cause reproduced: old L3 exhausted all 1024 generated tokens while thinking
was present and no final content existed. The API supplies total output counts,
not a verified reasoning/final token split; we do not invent separate token counts.
The larger thinking alternative succeeded, and direct mode still exhausted 1024.
The increase in cap and concise guidance were combined, so their separate causal
contributions cannot be determined. In the successful sample only 993 tokens were
needed, demonstrating that prompt/stochastic effects matter alongside headroom.

These are single samples in fixed order with loading/cache, prompt and stochastic
decoding differences. They establish observed completion outcomes, not guaranteed
latency/quality improvements or CPU/RAM savings. No whole-Ollama CPU/RSS measurement
was collected. Generation rate excludes prompt evaluation/loading. Final-presence
means filtered content exists, not that a length-stopped partial answer is complete.

### Implemented policy

Use **one bounded L3 call with think=true and num_predict 2048**, temperature 0.4,
num_ctx 8192, timeout 450 and history 16. Add concise internal-deliberation guidance
followed by a careful final analysis of assumptions, threats, trade-offs, limitations
and recommendations, normally under 350 words. L2 remains 768 tokens, temp 0.3,
timeout 300, history 6 and think=false with 150-word guidance. The temporary direct
L3 candidate was replaced after its live truncation; it is not the shipped default.

This preserves a meaningful deep-thinking distinction. It prioritizes a final
answer with bounded headroom and guidance, without promising a reserved final-token
quota. Context budgeting occurs after adding instructions; the deep conservative
input limit changes from 6656 to 5632 bytes. Verified mandatory snapshots are never
silently cut/reread: oversized input fails before inference. More output tokens can
increase latency; they do not imply better answers or lower peak CPU/RAM.

No automatic fallback or retry. A failed long-thinking call plus a second call
would repeat work/private prompts and increase latency while still risking failure.
No trace continuation, forced closing marker, unsafe response repair, model
replacement, shell command, permission change or stop-sequence override.

Ollama's documented [thinking control](https://docs.ollama.com/api/chat) supports a
boolean for this Qwen 3 integration. The separate budget examples for other engines
([Qwen budget documentation](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/thinking_budget.md))
do not establish an Ollama thinking_budget option. No undocumented per-reasoning
budget or model-defined low/medium setting is invented. Profiles remain validated
and request-scoped within the existing native mutex.

### Files and tests

Modified for this fix: friday/models/profile.py, friday/core/assistant.py,
friday/providers/ollama.py, README.md, PHASE_6D_REPORT.md. Created
 tests/test_l3_reliability.py and tests/phase6d_l3_benchmark.py. Updated explicit
budget expectations in the earlier Phase 6D regression tests: test_workload.py,
test_ollama_final_answers.py and test_l2_reliability.py. This matches the intended
1024-to 2048 default change; privacy/security assertions remain intact. All 649
original baseline tests are unchanged. Native source, filesystem permission rules
and navigation implementation were not changed by this fix.

New 14 regressions cover successful final answers, thinking-only exhaustion,
missing/partial/tagged/unmarked answers, scalar metrics privacy, failed turn/job
retention, single-attempt behavior, configurable thinking, real ToolManager
non-execution of model approval JSON, bounded benchmark/native gate lifecycle,
current-only benchmarking and distinct deep guidance/profile behavior.
Final full suite: **770 passed in 2.491 s**, zero failures/errors/skips. Focused deep 14,
prior final-answer 11 and L2 reliability 14 passed. Native synchronization/build,
syntax/import and forbidden execution API checks passed; final verification is
recorded below.

Reasoning stays solely in the transient HTTP response; only validated final content
returns to the assistant. The new final-answer-presence metric is a boolean and
contains no model text. Length, incomplete, empty or recognizable reasoning-only
results fail before SQLite/history. File explanations continue using bounded
session-only data and job scrubbing. No private content or approval decisions are
stored in logs or benchmark output. Historical SQLite rows are not rewritten.

Owner: `.venv/bin/python -B -m friday.main --adaptive --diagnostics`, then
`think deeply about the security architecture`; expect L3, one model call, a final
answer or safe error with no reasoning. Public current-only retest:
`PYTHONPATH=. .venv/bin/python -B tests/phase6d_l3_benchmark.py --live --current-only --samples 1`.
Omit --current-only to compare previous/current, or add --alternatives to include
1024-token direct deep. At most two samples, no retries or private prompts.

Remaining limits: guidance can be ignored and 2048 tokens can still be exhausted;
no hard reasoning/final token split, deterministic completion/quality guarantee,
hard end-to-end scheduler deadline or live CPU throttling is introduced. Native
mutex and all Phase 6B/6C security remain. Prefix-based unmarked reasoning detection
retains its documented heuristic limits. All changes remain uncommitted for review;
no Phase 6E or Git history operation was performed.

### Final configured-profile verification

A second public request using the exact final Settings profile and deep instruction
completed successfully: **86.1430 seconds**, **935 total output tokens**, **146
prompt tokens**, `done_reason=stop`, one model call. Generation took 85.1629 seconds
at 10.9790 tokens/second; prompt evaluation 0.8574 seconds and model loading 0.0019
seconds. Thinking and final-answer channels were both present; only validated final
content returned. No text from either channel was recorded in benchmark/report.

Both measured 2048-token thinking calls completed normally (993 and 935 total tokens).
This is useful local evidence of the chosen configuration, not a success-rate or
quality guarantee across prompts. The single 1024-token baseline failed before any
final content, and the direct alternative failed with partial final content.
The final budget/guidance combination improves observed completion reliability,
without claiming a faster CPU, lower RAM use or a hard reserved final-token budget.

Final native build passed; 31 synchronization tests passed in 0.197 seconds.
Final syntax/import and forbidden execution API inspection passed, as did
`git diff --check`. Full suite remains **770 passing tests** with no failures,
errors or skips. Final working tree contains 10 tracked modified and 12 untracked
created files across all Phase 6D work; all remain available for review. Branch
feature/safe-tool-system and HEAD 084c307 are unchanged. No commit, push, merge,
reset, rebase, stash or tag operation occurred.


## Release cleanup and recommended commit contents

Documentation-only cleanup updates final counts, corrects the Qwen reference and
separates historical offline/checkpoint results from final live evidence. The final
L2 defaults are 768 tokens/think=false; L3 uses 2048 tokens/think=true with brief
reasoning and final-analysis guidance. Owner live L2 Python explanation took 74.5
seconds; successful public L3 runs took 90.98 and 86.14 seconds. CPU-only inference
therefore remains slow, not a real-time response guarantee. A 2048-token cap can
still be exhausted; no uncontrolled retries, private trace persistence or security
downgrade was added. Other limitations: heuristic unmarked-reasoning detection,
conservative input limits, single-threaded scheduling/HTTP timeouts, unchanged old
SQLite rows/backups and no whole-Ollama CPU/RAM measurements.

Recommended **10 modified files**:

- README.md
- friday/config/settings.py
- friday/core/assistant.py
- friday/core/file_context.py
- friday/core/navigation.py
- friday/main.py
- friday/models/job.py
- friday/models/manager.py
- friday/providers/ollama.py
- friday/tools/intent_translator.py

Recommended **11 created files**:

- PHASE_6D_REPORT.md
- friday/core/context.py
- friday/core/workload.py
- friday/models/profile.py
- tests/phase6d_benchmark.py
- tests/phase6d_l2_benchmark.py
- tests/phase6d_l3_benchmark.py
- tests/test_workload.py
- tests/test_ollama_final_answers.py
- tests/test_l2_reliability.py
- tests/test_l3_reliability.py

Exclude PHASE_6D_BENCHMARK.json: historical generated fake-provider aggregates,
unchanged, left untracked and not deleted. No Git staging or history operation is
performed by this cleanup. All 21 recommended files remain available for review.

Release-cleanup validation: **770 tests passed in 2.405 seconds**, with zero
failures/errors/skips; `make -C native/sync` passed (already current) and
`git diff --check` passed. Preservation hashes verified that all 71 application
source/test/artifact files were unchanged during this documentation-only cleanup.
PHASE_6D_BENCHMARK.json still exists unchanged and remains untracked. Final status:
10 modified tracked files and 12 created untracked files, with 21 files recommended
for commit and the historical JSON excluded. No files were staged or committed.
