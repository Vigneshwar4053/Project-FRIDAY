# FRIDAY v0.5.0 / Phase 6E — Automatic speech and session toggle

> Historical implementation report. The approved dependency restoration,
> slash-command fixes and latest test results supersede the provisioning status
> below; see [PHASE_6E_RESTORATION_REPORT.md](PHASE_6E_RESTORATION_REPORT.md).
> Full v0.5.0 still awaits owner microphone/speaker validation.

**Milestone status: IN PROGRESS.** Available implementation is tested and ready
for owner review. Whisper provisioning, actual speaker/microphone validation and
review of conservative speech coverage remain incomplete. No release/tag/commit
was created. This report supersedes the earlier explicit-speech-only report;
historical observations remain historical.

## 1. Repository state before implementation

Verified branch: `feature/voice-foundation`. Starting tracked changes were
`.gitignore`, `README.md`, `friday/core/assistant.py`, `friday/main.py`. Untracked
artifacts were `PHASE_6D_BENCHMARK.json`, `PHASE_6E_REPORT.md`, `docs/`,
`friday/voice/`, `tests/test_voice.py`, `tests/test_voice_foundation.py`.
No applicable AGENTS.md was found in the repository or inspected ancestors.
Existing changes were extended, not discarded. Pre-edit preservation hashes
covered 93 files outside Git/venv/bytecode directories. The current baseline was
independently rerun: **852 tests passed in 5.100 seconds**.

Inspected assistant response generation, temporary file context, restored/current
memory, adaptive L0–L3 routing, main CLI composition, voice input/configuration,
TTS backend, relevant tests and setup documentation before implementation.

## 2. Root causes of owner-reported problems

Automatic speech was deliberately denied by the previous policy. `/speak TEXT`
was its only output entry point; returning ordinary answers never invoked TTS.
There was no session controller or `/q` command. eSpeak's presence did not change
that policy. The owner's 'Speech finished' observation is recorded as owner
feedback, not independent speaker validation by Codex.

`/voice` remains unavailable because neither saved voice.json nor the old
temporary Whisper dependencies exists in the inspected environment. The old
`/tmp/friday-voice-trial.81iQhN/` directory is absent, whisper-cli is not in PATH,
and the configured-XDG candidate bin/model paths are missing. This is a
configuration/dependency failure, not evidence that the microphone is broken.

Recognition problems are separate: the previous eight-second total recording
included readiness/settling. The existing timing fix is preserved. No new WER,
live recognition, gain or channel calibration result exists.

## 3. Existing versus new behavior

| Interaction | Previous | New |
| --- | --- | --- |
| Startup | Text banner; no output controller | Speech Output ON if TTS file checks pass; Microphone OFF; no startup playback |
| Trusted L0 greeting | Printed | Printed, flushed, spoken once when enabled |
| Eligible public model conversation | Printed | Printed, flushed, spoken once when enabled |
| Unknown/private model context | Printed | Printed, remains silent |
| Tool/file/permission/diagnostic/error output | Printed as before | Printed as before, no automatic speech |
| /q | Not implemented | Session-only automatic-output toggle; confirmation is silent |
| /speak TEXT | Explicit offline speech | Same backend, one manual playback regardless of /q |
| Confirmed /voice reply | Printed, session-only | Same persistence suppression and trusted speech policy as keyboard replies |
| Missing Whisper | Microphone OFF, actionable message | Same; no unauthorized restoration |

## 4. Architecture changes

No separate voice assistant was introduced. FridayAssistant still owns response
generation, routing and permissions. Its `respond()` API still returns a string.
It now publishes text-free, immutable `last_response_metadata` describing trusted
response category/provenance. CLI rendering receives that metadata immediately
after the corresponding successful response. Metadata resets at each request,
on failure and at session end, preventing stale eligibility.

`friday/core/response.py` defines categories, provenance, the positive public
request policy, context fingerprints and a secondary credential-structure guard.
`friday/voice/tts.py` retains the existing offline backend and adds SpeechController.
The main CLI owns one controller per session. No audio worker/thread/queue,
additional model request, global toggle, permission change or model-routing
replacement was added.

## 5. Speech controller

The controller owns `enabled`, `available` and `closed` state for this CLI session.
Initialization verifies the backend without playback; it defaults ON if available.
It exposes toggle, safe-response speech, explicit speech, stop and shutdown.
Playback is synchronous and bounded. Shutdown is idempotent and closes output
control on ordinary exit, errors and orderly SIGTERM unwinding.

There is no retained response text, background queue or overlapping speech.
The controller has no assistant, tool, memory or microphone reference. The
existing backend interface supports a future Piper adapter without redesigning
the CLI. Piper installation/models remain separate future approvals.

## 6. Response classification and privacy

Speech eligibility is determined by application code, not labels in generated
text and not L0–L3 level alone. Only these provenance/category combinations qualify:

- A deterministic trusted local greeting.
- A model conversation using a positively classified public request and actual
  model context whose included history has current-session public provenance.

All tool results are denied, including successful harmless-looking tool strings.
File snapshots and generated explanations are denied. Permission-management
messages, route/navigation refusals, translator outputs, errors and unknown
sources default to denied. There are no new completion-summary exceptions.
Diagnostics and prompts are printed through their existing separate paths and
never submitted to the speech controller as eligible answers.

The positive public policy uses full-request matching with a reviewed topic
catalog: Python/decorators, machine learning, computing/security concepts,
mathematics/science topics, public small talk and limited contextual follow-ups.
It does not infer that arbitrary pasted material or personal/security analysis
is public merely because it took a model branch. For example, 'what is a password?'
can qualify, while harmless-looking private prose cannot. This is not a keyword
blacklist. Unknown requests still receive their original text answers.

Public context assurance uses a bounded deque of 40 role/content fingerprints
for successful eligible current-session persisted turns. It stores no extra
conversation text and is cleared at session end. Fingerprints are compared to
the **actual selected model context**, so modified messages lose provenance.
Restored SQLite history has no speech permission and fails closed; metadata is
not persisted or reconstructed from user/model labels. A private/unknown turn
included in a later public question's model prompt also keeps that answer silent.
Private voice turns create no reusable history or fingerprints.

Common credential assignments, private-key blobs and token-bearing JSON are
also refused after provenance checks. This structural guard is defense in depth,
not a general privacy classifier or proof of semantic content safety. LLM text
cannot override metadata by writing `speech_eligible=true` or a category label.

**Coverage limitation:** this implementation does not automatically speak every
arbitrary free-form model answer. Public requests outside the reviewed grammar,
answers influenced by unclassified restored history, private findings, imported
documents and unknown provenance remain text-only. Expanding coverage requires
reviewed public request/context provenance. This is the conservative interpretation
of the owner's stronger privacy requirement, and must be accepted or refined in
release review rather than hidden as universal ordinary-answer support.

## 7. /q

The CLI recognizes exact `/q` after its established strip/casefold handling.
It disables automatic speech on the first toggle and re-enables it on the next
when the backend remains available. Confirmations are printed only. It is not
an exit alias; `exit`, `quit`, `/bye` and Ctrl+C retain their behavior.

The command never reaches Ollama, assistant tools, microphone capture, message
persistence, filesystem permissions or settings. New sessions default ON again
if TTS is available. Re-enabling rechecks availability without playback. If the
executable is still missing, speech stays OFF with a concise actionable warning.

## 8. Keyboard response integration

For a successful assistant answer: compute response and metadata, print the full
response with flush=True, then submit only eligible output to TTS. The text is
visible before playback begins and remains visible after a timeout/device error.
There is exactly one backend speak call per eligible answer. Newline/tab/carriage
return separators are changed to spaces for speech only; terminal text remains
unchanged. No speculative speech occurs while the answer is generated.

Startup banners, working notices, toggle confirmations, errors, permissions,
diagnostics and goodbye are not automatically spoken. `/speak` uses its own
explicit branch, so it does not also trigger automatic playback.

## 9. Confirmed /voice integration

The existing voice_turn still requires explicit Enter activation, preview and
typed y. It dispatches only confirmed text through `respond(..., persist=False)`.
Only a non-None successful reply is printed/flushed and evaluated with the same
metadata policy as keyboard responses. If /q is OFF, capture/confirmation/dispatch
still work; only automatic output is disabled. There is no transcript redispatch
as `/q`, `/speak` or raw shell syntax.

Permission prompts remain typed and silent. Incorrect/cancelled/empty/failed
transcripts produce no assistant action or automatic playback. Voice replies
are not spoken twice, stored in SQLite or retained as reusable chat history.
Existing raw-audio cleanup tests continue passing.

## 10. TTS backend behavior

eSpeak NG remains the only current backend. Text goes to UTF-8 stdin, not argv,
shell commands, files or SSML. The process uses safe argument arrays, a separate
process group, a 60-second timeout and bounded SIGINT/SIGKILL cleanup. The input
bound increases from 1000 to **8192 UTF-8 bytes** so typical multi-paragraph
conversational answers can use one playback. Other controls are still rejected.

Missing executables, nonzero status, audio diagnostics including zero-status
diagnostics, timeouts and unexpected backend errors preserve text and return
fixed diagnostics. Ctrl+C during playback cancels the process and returns to a
safe text prompt. Manual speech remains available with automatic output OFF.
Speech input is not stored in SQLite, history, diagnostics or application logs.
Physical output availability is not inferred from executable existence.

Long answers may exceed the 8192-byte bound or the 60-second playback window.
They can fail or be interrupted with text retained. No silent truncation,
background accumulation, repeated playback, TTS cloud service or Piper download
is introduced.

## 11. Whisper dependency status and version correction

The inspector currently returns `not_configured`, microphone OFF, and the actual
XDG configuration/data paths. In this editor environment XDG_DATA_HOME points
under snap/code; without it, the default durable data path is
`~/.local/share/friday/voice/`. Configuration remains
`~/.config/friday/voice.json` by default. Actual XDG candidate bin/tiny/base paths
are missing. Searches of accessible reasonable locations found no trusted
Whisper CLI or model. Unreadable service-private directories were not searched.

Configuration discovery, individual CLI overrides, complete-override recovery,
absolute paths, owner/file validation and the established tiny.en SHA-256 check
are unchanged. `--check-voice-config` performs file/hash inspection without any
assistant, model, microphone or speaker initialization. Wrong/missing files or
hashes fail before microphone activation and unverified model execution.

The owner reports the successful trial used **Whisper.cpp v1.9.5**. The preceding
v1.8.2 proposal was a different, older version and was never executed. The guide
now proposes **v1.9.5 at d1be6fde11ac6e0407606b4e42fe72d34add8037**, preserving the
reported version rather than silently downgrading. This is only a proposal.
[Upstream release/commit](https://github.com/ggml-org/whisper.cpp/commit/d1be6fde11ac6e0407606b4e42fe72d34add8037).

Inspected upstream sources confirm both versions expose the used decoding flags
and native miniaudio conversion. Their decoder lifetime/fallback implementations
and ggml revisions differ; a common model hash/flags cannot establish identical
timing/WER. Actual runtime compatibility remains unverified while files are
missing. [v1.9.5 CLI](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.9.5/examples/cli/cli.cpp),
[v1.9.5 decoder](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.9.5/examples/common-whisper.cpp),
[v1.8.2 CLI](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.8.2/examples/cli/cli.cpp).

The original tiny.en pin remains
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
The proposed immutable model revision supplies 77,704,715 bytes.
[Model metadata](https://huggingface.co/ggerganov/whisper.cpp/commit/80da2d8bfee42b0e836fc3a9890373e5defc00a6).
No base.en/Piper/Telugu substitution is included.

Exact proposed source/model download, CPU build, hash verification, synthetic
native-WAV compatibility check and owner configuration creation commands are
in [docs/PHASE_6E_SETUP.md](docs/PHASE_6E_SETUP.md). Source archive/binary sizes
and first-download source hash remain unverified; the guide distinguishes
estimates and locally recorded integrity hashes from upstream authenticated
model pins. The restoration stage is stopped pending explicit owner approval.
No download, Whisper build, installation, provisioning, sudo or venv edit ran.

## 12. Recording and privacy safeguards

No changes were made to capture/backend/configuration/voice-turn privacy code in
this increment. ALC256 native 48 kHz stereo capture remains explicit, verifies
owned RUNNING hw_ptr progress before/after settling, permits eight seconds after
the flushed cue, uses the 12-second native guard and bounded decoder/shutdown
timeouts. Preview and typed confirmation remain mandatory. There is no microphone
gain change, VAD, wake word, background listening or automatic startup activation.
No independent live STT accuracy improvement is claimed.

Audio remains in private temporary directories, removed before confirmation and
on ordinary errors/interruption. Voice persistence suppression remains per turn;
there is no global privacy toggle. Metadata retains no private response text.
Terminal echo/scrollback can retain input/output, SIGKILL/system crashes can
interrupt cleanup, and OS audio infrastructure can buffer independently. File
unlinking is not forensic erasure. Explicit `/speak` can speak owner-supplied text,
so it remains the owner's responsibility to choose material safe to hear aloud.

## 13. Exact changed files in this increment

Application:
- Added `friday/core/response.py`.
- Modified `friday/core/assistant.py`: trusted response metadata and bounded public
  history provenance; existing generation/routing/privacy behavior retained.
- Modified `friday/main.py`: controller lifecycle, startup state, /q, print/flush
  order and shared keyboard/voice automatic speech.
- Modified `friday/voice/tts.py`: controller, availability verification and expanded
  single-utterance bound; existing eSpeak process safeguards retained.

Tests:
- Added `tests/test_voice_automatic.py`: 48 new offline regressions.
- Modified `tests/test_voice_foundation.py`: update the superseded deny-all/size
  expectations and add one longer-answer regression.
- Modified `tests/test_voice.py`, `tests/test_cli.py`,
  `tests/test_filesystem_permissions.py`, `tests/test_ollama.py`,
  `tests/test_ollama_final_answers.py`, `tests/test_tool_routing.py`,
  `tests/test_workload.py`: inject fake TTS into CLI tests so automatic output
  cannot access real audio; existing security/routing assertions retained.

Documentation:
- Modified `README.md`: interaction, speech/privacy policy, limitations and roadmap.
- Modified `docs/PHASE_6E_SETUP.md`: explicit v1.9.5 correction, exact proposed
  commands and automatic-output owner validation.
- Modified `PHASE_6E_REPORT.md`: historical/superseded notice; prior results retained.
- Added this `PHASE_6E_AUTOMATIC_SPEECH_REPORT.md`.

`.gitignore` and prior uncommitted voice/configuration/backend work are preserved.
Production filesystem permissions, navigation, adaptive profiles, memory storage
and native C sources were not changed. PHASE_6D_BENCHMARK.json remains unchanged
and untracked; no dependency/runtime artifact was added to Git.

## 14. Exact automated results

| Command | Result |
| --- | --- |
| `.venv/bin/python -B -m unittest discover -s tests` | **901 passed, 5.378 s** |
| `.venv/bin/python -B -m unittest discover -s tests -p 'test_voice*.py'` | **131 passed, 0.444 s** |
| `.venv/bin/python -B -m unittest discover -s tests -p test_sync.py` | **31 passed, 0.207 s** |
| `git diff --check` | Passed |
| `git status --short --branch` | feature/voice-foundation; uncommitted prior/new changes |
| `--check-voice-config` | Accurate not_configured status, microphone OFF, exit status 1 |

901 consists of the independently verified 852 baseline plus **49 new tests**.
Focused/native tests are subsets of the full suite, not additional unique tests.
Final suites have no failures/errors/skips. All speech/microphone tests use
fakes/mocks; no microphone or real playback was used. Tests cover startup/toggle,
print-before-speech, exactly-once behavior, long/paragraph answers, missing TTS,
timeout/cancellation/shutdown, voice privacy/confirmation, actual filesystem typed
approval, tool/file/unknown-history blocking and label spoofing. Existing complete
security, adaptive L0–L3, navigation, memory, config and process-cleanup tests pass.

## 15. Native build

`make -C native/sync` succeeded; the existing library was already current.
31 synchronization tests passed. Native source/build configuration was preserved.

## 16. Known limitations

- Speech coverage is a reviewed public catalog and trusted provenance policy,
  not universal free-form conversational privacy classification.
- Restored history is intentionally not speech-authorized; even a public question
  may remain silent when that history is included. /q cannot override this.
- Structural credential guards are secondary and are not a semantic guarantee.
- eSpeak is temporary/synthetic; actual output-device behavior needs owner feedback.
- The 60-second/8192-byte bound can refuse/interrupt long speech. Text remains.
- No Whisper/runtime compatibility, live microphone/WER, gain/channel calibration
  or base.en comparison was performed.
- ALSA card/identity changes fail closed; explicit /voice is still required.
- No startup/unlock greeting, always-on listening, Piper, desktop control or future
  roadmap capability was introduced.

## 17. Owner manual validation

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --adaptive
```

At startup verify Speech Output ON and Microphone OFF (or the missing-TTS warning).
Then enter these one at a time:

```text
hello
/q
hello
/q
hello
/speak Hello, I am FRIDAY.
```

Expected: first/last greeting printed and spoken once; middle greeting printed
silently; toggle confirmations silent; manual speech exactly once. Ctrl+C during
playback cancels and returns safely. A public question such as 'what is Python?'
should print and speak when its actual model context qualifies; unclassified
restored history intentionally blocks its speech. Never use private findings or
files for the first speaker test. Codex has not performed these live tests.

```bash
.venv/bin/python -B -m friday.main --check-voice-config
```

Current expected result: not_configured, microphone OFF, no playback/capture.
After explicit approval, follow the setup guide to restore v1.9.5/tiny.en,
verify model hash and synthetic runtime compatibility, then save voice.json.
Restart normally without long --voice-* arguments. Enter `/voice`, press Enter,
wait for CAPTURE READY — SPEAK NOW, then say 'Hello Friday.' Inspect preview;
Enter/n discards, /voice retries, y confirms only an accurate greeting. Expect
text plus one eligible spoken reply when automatic output is ON. With /q OFF,
the same capture/confirmation/response works with silent output. Owner microphone
and speaker results remain pending.

## 18. Remaining work before v0.5.0 release

- Explicit owner approval for the pinned source/model downloads and local CPU
  build/provisioning; then actual file/hash/CLI compatibility verification.
- Owner speaker/toggle/manual-output validation on the changed implementation.
- Owner microphone capture, cancellation, confirmation and spoken-reply validation.
- Independent recordings to assess recognition, including the downloads phrase.
- Release review of conservative speech coverage and unclassified memory behavior;
  no silent relaxation of privacy to achieve broader output coverage.
- Review of all preserved uncommitted changes and any later Git authorization.

Code-level startup, rendering, toggle, manual output, sensitive-output suppression,
privacy, security regression and native checks pass offline. Durable Whisper and
hardware criteria remain unchecked. Therefore **Phase 6E is IN PROGRESS**, not
complete or tagged merely because 901 tests pass.

## 19. Next milestone

After reviewed/validated v0.5.0, v0.6.0 Phase 6F — Wake Word & Natural Conversation
will have its own explicitly approved input-mode design (listening mode,
push-to-talk, optional wake word/VAD). Current microphone activation remains
explicit. Later desktop control, vision, local RAG/memory, stable release and
Telugu milestones retain the README roadmap.

## 20. Git and authorization confirmation

No commit, push, merge, tag, reset, rebase or stash was performed. No package/model
download or installation, sudo, Piper provisioning, microphone gain change,
startup service or real hardware test occurred. Source documentation/metadata
was read from upstream for version comparison; no source archive was downloaded.
All implementation changes remain uncommitted for owner review.
