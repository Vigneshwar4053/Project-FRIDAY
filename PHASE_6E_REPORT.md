# Phase 6E — Persistent voice configuration and explicit offline speech

> Latest restoration evidence: [PHASE_6E_RESTORATION_REPORT.md](PHASE_6E_RESTORATION_REPORT.md).
> Earlier missing-dependency observations below are historical; approved v1.9.5
> provisioning has now completed. Owner hardware validation remains pending.

> Historical report for the earlier explicit-speech increment. The current
> automatic-speech implementation and final results are documented in
> [PHASE_6E_AUTOMATIC_SPEECH_REPORT.md](PHASE_6E_AUTOMATIC_SPEECH_REPORT.md).
> Its earlier v1.8.2 restoration proposal is superseded by the owner-tested
> v1.9.5 proposal in docs/PHASE_6E_SETUP.md; no version was installed here.

Implementation date: 2026-10-09. Repository branch: feature/voice-foundation.
Safe available portions are implemented; Whisper restoration and owner hardware
validation remain pending. No commit or other Git mutation was performed.

## Verified starting state and diagnosis

Starting working tree already contained modified README.md,
friday/core/assistant.py and friday/main.py, plus untracked friday/voice/,
tests/test_voice.py and PHASE_6D_BENCHMARK.json. Those changes were preserved;
this increment extended only the relevant voice/CLI/documentation areas.
No applicable AGENTS.md was found in the repository or its inspected ancestors.
Inspected main.py, assistant.py, voice/backend.py, voice/cli.py, memory/manager.py,
settings.py, README, voice/CLI/privacy/permission/navigation/synchronization tests
and native build rules. Initial full suite: **810 passed in 3.023 seconds**.

Previously main's CLI composition built a voice backend only when all three
--voice-binary, --voice-model and --voice-model-sha256 flags were supplied.
Without them, /voice received backend=None and printed 'not configured'. This
message occurred before any capture attempt and did not diagnose hardware.

| Failure category | Confirmed state / handling |
| --- | --- |
| Missing command-line/saved configuration | Original root cause of the not-configured message; no saved discovery existed. Current inspection reports not_configured. |
| Missing executable | whisper-cli not in PATH or searched accessible reasonable local locations; old /tmp directory absent. /voice verifies it before activation. |
| Missing model | tiny.en and base.en not located; model restoration remains pending. |
| Incorrect paths | Separate dependency failure; absolute paths and saved configuration are inspectable. |
| Invalid hash | Supplied pin must be the established tiny.en SHA-256; actual file contents are hashed before activation. Invalid pins and mismatched files are separately rejected. |
| Capture errors | None measured live. ALSA /proc identity is ALC256; capture status/hw_params were closed. Runtime checks still refuse wrong identity, busy device, readiness/format/early-stop failures. |
| STT accuracy | Historical inconsistent transcripts and 8.33% WER are owner observations. No new live accuracy result, comparison or claim of improvement. |

Read-only /proc/asound showed card1 Generic_1, capture PCM0/sub0, ALC256 Analog.
The read-only amixer query could not access card1 in this execution environment
('Invalid card number'); gain/boost levels therefore remain unverified. No gain,
device selection or mixer controls were changed, and no microphone was opened.
capture_consistency.py and capture_calibration.py remain unavailable, so a direct
source-to-source standalone comparison cannot be made.

## Dependencies and approval

Installed: eSpeak NG **1.52.0**, arecord, CMake **4.2.3**, GCC/G++ **15.2.0**, curl,
tar and install. The eSpeak version query did not play audio. No TTS installation
approval is needed. Missing: whisper-cli, original tiny.en and optional base.en.
Local STT/model compatibility and local model hashes cannot be verified while
these files are absent. Searches covered accessible home/cache/project/local
locations and /tmp; inaccessible service-private directories are not evidence
of global absence.

Proposed durable layout uses XDG_DATA_HOME/friday/voice (default
~/.local/share/friday/voice): bin/whisper-cli and models/ggml-tiny.en.bin.
The current editor environment supplies an XDG data path under snap/code; the
configuration inspector exposes the selected path. Saved dependency paths are
explicit absolute paths, independent of later launcher changes to XDG_DATA_HOME.

Owner approval is required before downloading/building upstream whisper.cpp
v1.8.2 at commit 4979e04f5dcaccb36057e059bbaed8a2f5288315 and the original tiny.en
artifact (77,704,715 bytes) at maintainer model revision
80da2d8bfee42b0e836fc3a9890373e5defc00a6. The established tiny.en SHA-256 is
921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f.
Source archive size and final binary checksum are not verified; the guide
distinguishes estimates/local integrity records from independently authenticated
hashes. No base.en or language/model substitution is included in this proposal.
See [exact sources, sizes, proposed commands and verification](docs/PHASE_6E_SETUP.md).
No download, build of Whisper, installation, sudo or virtual-environment edit
was performed. No owner runtime configuration was written before provisioning.

## Persistent configuration

Added friday/voice/configuration.py. The CLI discovers
XDG_CONFIG_HOME/friday/voice.json (default ~/.config/friday/voice.json).
Version 1 requires binary, model and model_sha256. It rejects relative/control
paths, duplicate/unknown/missing fields, unsupported types/versions, files over
4096 bytes, symlink configs, nonregular files and configurations writable by
other users. The file must be owned by the current user. Prefer mode 0600.
~ is expanded; environment variables and shell syntax are not evaluated.
Relative XDG environment values fall back to standard home defaults.

Explicit CLI flags override saved fields individually. Complete overrides skip
a malformed saved file; incomplete overrides without saved fields fail safely.
No save or rewrite happens implicitly. Invalid configuration still allows the
normal text CLI, with an actionable reason on /voice. Missing executables/models
and mismatched hashes are detected before Enter activation. Nonregular model
files are refused before opening them, preventing FIFO reads from hanging.

--check-voice-config prints JSON configuration and file/checksum status, without
launching the configured executable, microphone, speaker, assistant, model,
memory or tool runtime. Status verified_files does not claim CLI/model or hardware
compatibility. The normal backend remains lazy; startup never records or speaks.
The guide supplies a separate owner-approved synthetic native-WAV load/flag
compatibility check for when the actual executable/model have been provisioned.

## Recording timing and reliability

The original arecord -d 8 capture consumed readiness and 0.8 s settling inside
the eight-second duration. That shortened the usable speech window. Now the
speech timer starts after the flushed CAPTURE READY — SPEAK NOW cue and allows
the full configured duration (eight seconds by default). arecord's independent
duration is configured duration + 4 seconds (12 by default) as a secondary guard.
After the speech interval, orderly SIGINT finalizes the original WAV; shutdown
waits at most two seconds before the existing bounded cancellation fallback.
Unexpected completion before the interval ends fails safely.

Owned RUNNING status, increasing hw_ptr, ALC256 identity and native S16_LE/two
channels/48000 Hz are still required. Pointer progress is now checked again
after settling. Readiness remains bounded to two seconds. STT WAV validation
allows the bounded quiet pre-roll plus speaking interval, retaining original
audio. Channel conversion is delegated to the CLI; no gain adjustment,
normalization, trimming, VAD or denoising was introduced. English/four CPU threads,
beam/best-of 5, temperature zero, no GPU/fallback and STT's 60 s timeout remain.

Fake tests establish timer ordering, bounds and failure behavior; actual ALSA
SIGINT/WAV finalization and recognition must still be validated by the owner.
This is a timing fix, not measured evidence of improved WER. Preview and typed
y confirmation remain mandatory. Enter/n discards recognition; /voice retries.

## Offline TTS and response policy

Added SpeechBackend protocol, EspeakNGBackend and speak_turn in voice/tts.py.
/speak TEXT is intercepted by the text CLI and speaks only explicit supplied
text. The backend uses /usr/bin/espeak-ng, stdin UTF-8, English voice, 175 wpm,
no shell/file input/SSML, a 1000-byte input bound and a 60-second subprocess
timeout. It rejects controls and empty input. Audio diagnostics, even with a
zero exit status, conservatively report unverified output failure without exposing
stderr or private input. Missing executables/OSError/timeouts have fixed messages.
Process groups permit bounded Ctrl+C cancellation and escalation to SIGKILL if
needed. The executable-entry SIGTERM handler unwinds cleanup and exits.

No assistant/provider/tool/memory/capture invocation occurs for /speak. No startup
speech or automatic response speech occurs, including after a confirmed voice
reply. Spoken '/speak ...' transcripts reach the assistant only after confirmation;
they never enter CLI speech dispatch. Automatic output is denied for every
response category in this increment. A later increment must introduce trusted
response provenance; model text or arbitrary category strings cannot authorize
speech. This avoids speaking file contents, listings, credentials, permissions,
tool/web output, diagnostics or errors through an automatic path. Explicit
/speak input is an owner instruction, not automatic response classification.

## Privacy/security review

The existing per-turn respond(persist=False) path is preserved. Voice transcripts
and responses do not enter SQLite or reusable chat history, and model-job
messages/results/errors are scrubbed per turn. Core assistant, memory, adaptive
profiles and filesystem permission code were not changed in this increment.
Permission confirmations remain typed; spoken tokens cannot approve them.
No new transcript-based execution, network speech, wake word, global mutable
privacy flag, always-on capture, startup service or desktop automation exists.

Audio remains in a private TemporaryDirectory and is deleted before transcript
confirmation, including ordinary errors, Ctrl+C and orderly SIGTERM unwinding.
/speak text is neither persisted nor copied to subprocess argv or application
diagnostics/logs. Terminal echo/scrollback can retain displayed/typed text;
SIGKILL/system crashes can interrupt cleanup; OS audio infrastructure may buffer
independently; file unlinking is not forensic erasure. No hardware/privacy claim
extends to external OS components. Existing permission/session-navigation
protections and explicitly approved persistent folder grants retain their normal
behavior.

## Changed files in this increment

- Modified .gitignore: exclude ggml model binaries, whisper-cli and optional
  voice-artifacts; actual dependencies belong outside the repository.
- Modified friday/main.py: saved configuration composition/inspection, explicit
  speech dispatch, flushed capture cues and orderly SIGTERM cleanup.
- Modified friday/voice/backend.py: post-ready speech interval, continued pointer
  progress, bounded pre-roll WAV limits, fixed dependency messages and process
  termination race handling.
- Modified friday/voice/cli.py: actionable unconfigured/invalid messages and retry
  instructions; existing privacy/confirmation flow retained.
- Modified tests/test_voice.py: adapt existing capture mocks to the corrected
  full-window/orderly-stop behavior while retaining the original assertions.
- Added friday/voice/configuration.py and friday/voice/tts.py.
- Added tests/test_voice_foundation.py: **42 new offline regressions**.
- Modified README.md Phase 6E section and preserved roadmap.
- Added docs/PHASE_6E_SETUP.md and this report.

Existing uncommitted friday/core/assistant.py edits belong to the earlier voice
increment and were not overwritten or extended here. PHASE_6D_BENCHMARK.json
was not modified or deleted. No runtime/model artifacts were added.

## Validation and owner commands

Final full command: `.venv/bin/python -B -m unittest discover -s tests`:
**852 tests passed in 5.095 seconds**, no failures/errors/skips. This includes the
810-test baseline plus 42 new configuration/TTS/capture/privacy regressions.
Existing L0–L3, filesystem permission/symlink/TOCTOU, text CLI, navigation and
memory tests pass. All new speech/capture tests use mocked/fake backends; no
arecord, Whisper or eSpeak playback ran. Native `make -C native/sync` succeeded
(already current); **31 synchronization tests passed in 0.210 seconds**.
`git diff --check` passed and ignore rules cover model/binary artifact names.

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive
```

Owner manual sequence: `/speak Hello, I am FRIDAY.`; Ctrl+C can cancel playback.
After approved STT restoration/configuration, `/voice`, press Enter, wait for
CAPTURE READY — SPEAK NOW, then say 'Hello Friday.' Type n/Enter if inaccurate
and /voice to retry. Type y only if accurate, and verify FRIDAY's text greeting.
Do not use private files or sensitive commands for first validation. Hardware
success is pending owner results. Exact restoration/configuration and synthetic
compatibility commands are in the setup guide; none was executed.

## Remaining limits and roadmap

Runtime restoration is stopped at the missing-dependency boundary pending owner
approval. No trusted binary compatibility, live capture/WER, model comparison or
audio playback success is claimed. STT remains tiny.en; confidence thresholds,
channel/gain calibration, noise handling and Telugu are not added. The fixed
ALC256/card1 identity can fail closed if enumeration changes. eSpeak's synthetic
voice and conservative stderr handling may need owner feedback. /tmp comparison
artifacts remain historical preparation; they are not required runtime assets.

v0.4.0 Phase 6D is complete. v0.5.0 Phase 6E is current, pending restoration and
owner validation. The next roadmap milestone is v0.6.0 Phase 6F — Wake Word &
Natural Conversation, with its own explicit scope/approval. Desktop control,
vision, advanced local memory/RAG, stable v1.0 and Telugu remain in later phases
as documented in README. None was implemented here.
