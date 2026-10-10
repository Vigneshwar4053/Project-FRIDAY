# Phase 6E — Approved Whisper restoration and CLI repair

> Follow-up: [PHASE_6E_CAPTURE_REPORT.md](PHASE_6E_CAPTURE_REPORT.md) documents the
> owner-reported post-readiness failure, targeted capture lifecycle/WAV checks
> and latest tests. Installation/hash evidence below is unchanged; its capture
> implementation/test counts describe the earlier restoration increment.

Date: 2026-10-09. Branch: `feature/voice-foundation`. Approved restoration and safe
CLI implementation are complete and ready for owner hardware testing. **Full
v0.5.0 / Phase 6E remains IN PROGRESS** until owner speaker/microphone validation
and release review. No release/tag/commit was created.

## 1. Initial repository state

Verified repository `~/Projects/FRIDAY`, expected branch, and dirty worktree.
Tracked changes already present: `.gitignore`, `README.md`,
`friday/core/assistant.py`, `friday/main.py`, `tests/test_cli.py`,
`tests/test_filesystem_permissions.py`, `tests/test_ollama.py`,
`tests/test_ollama_final_answers.py`, `tests/test_tool_routing.py`,
`tests/test_workload.py`. Untracked: `PHASE_6D_BENCHMARK.json`,
`PHASE_6E_AUTOMATIC_SPEECH_REPORT.md`, `PHASE_6E_REPORT.md`, `docs/`,
`friday/core/response.py`, `friday/voice/`, `tests/test_voice.py`,
`tests/test_voice_automatic.py`, `tests/test_voice_foundation.py`.

No applicable AGENTS.md was found in the repository or inspected ancestors.
Inspected the requested voice/core/CLI modules, relevant tests, existing setup
and both Phase 6E reports before changing code. Baseline: **901 tests passed in
5.309 s**. Existing uncommitted work and untracked benchmark were preserved.

## 2. Root cause of missing voice input

The previous trial dependencies lived in a temporary directory that no longer
exists. No saved owner voice configuration was present. Thus CLI composition
passed backend=None to `/voice`, and it declined capture before accessing a
microphone. This was configuration/dependency failure, not a capture diagnosis.
The existing backend/configuration/controller architecture was reused unchanged.
No second voice subsystem was created.

## 3. Exact upstream version

Restored **Whisper.cpp v1.9.5**, not v1.8.2. Installed `--version` reports 1.9.5.
The earlier v1.8.2 proposal was not executed. Official [release](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5)
and pinned [build instructions](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/README.md)
were inspected. Upstream CMake and CLI sources were reviewed before building;
no downloaded install script was executed.

## 4. Resolved source commit and integrity

GitHub API resolved release ref v1.9.5 to annotated tag object
`d2a764c648779feb36d44363f212a29b00aad1af`, then source commit
`d1be6fde11ac6e0407606b4e42fe72d34add8037`. Upstream tag metadata reports unsigned;
no independent source-signature verification is claimed.

Downloaded [immutable official archive](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/d1be6fde11ac6e0407606b4e42fe72d34add8037):
9,631,456 bytes. Local SHA-256:
`645445da884df6dbd52b30f82d7be7c01d1767c938714e477e786b88d529e9f4`.
Archive extraction rejected absolute/parent-traversal paths, links and non-file/
non-directory entries. Source provenance/tag metadata is retained in the local
build-source directory. The locally computed archive hash records integrity,
not independent authentication of the first HTTPS download.

## 5. Downloaded model source

Original unquantized English tiny.en from the upstream maintainer's
[immutable Hugging Face revision](https://huggingface.co/ggerganov/whisper.cpp/resolve/80da2d8bfee42b0e836fc3a9890373e5defc00a6/ggml-tiny.en.bin),
revision `80da2d8bfee42b0e836fc3a9890373e5defc00a6`. No base.en, larger model,
Telugu model, dataset or Piper voice was downloaded.

## 6. Model checksum verification

Actual size: **77,704,715 bytes**. Full locally calculated SHA-256 matches the
explicit owner pin:
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
HTTPS-only download/redirects wrote a private `.partial` file; it was promoted
only after full hash verification. Model validation was repeated before writing
configuration and during application inspection. No unverified model was used.

## 7. Final persistent installation paths

Final runtime root: **`~/.local/share/friday/voice/`**, owner-owned, mode 0700.

- Executable: `bin/whisper-cli`, mode 0700.
- Model: `models/ggml-tiny.en.bin`, mode 0600.
- Source archive/provenance: `build-source/whisper.cpp.tar.gz`,
  `build-source/source-provenance.json`.
- Extracted source: `build-source/whisper.cpp-d1be6fde11ac6e0407606b4e42fe72d34add8037/`.
- Completed build: `build-source/build/`.
- Binary integrity record: `bin/whisper-cli.sha256`.
- Installed help/libraries records: `build-source/installed-cli-help.txt`,
  `build-source/runtime-libraries.txt`.

The editor supplied a Snap revision-specific XDG_DATA_HOME. Initial downloads/
build used it; the installation was then moved to the stable XDG default above,
without a duplicate model. Saved absolute runtime paths work regardless of a
subsequent launcher's XDG_DATA_HOME. The displayed dependency-directory candidate
may still reflect the editor environment; it is not the actual saved binary path.
No environment/global settings were changed. The moved CMake cache contains
original build paths; use a fresh build directory for future rebuilds.

## 8. Executable SHA-256

Installed binary: **3,385,824 bytes**, SHA-256
`c488e598e073312a7addb7b5964ca1ae060656e1637df511d4060a49bdb2472a`.
Private partial write and rename installed the executable. Binary/model/source
remain outside Git and the virtual environment.

## 9. Build configuration

Existing GNU C/C++ 15.2.0 and CMake, Release, CPU native optimizations,
`BUILD_SHARED_LIBS=OFF`, installed OpenMP enabled, two parallel build jobs.
Whisper tests/server/dev build disabled; examples enabled only to expose the
`whisper-cli` target. CUDA/Vulkan/OpenCL/BLAS/CURL disabled; SDL/FFmpeg defaults
remain OFF. No system GGML or new package dependency. Exact command/options are
recorded in `docs/PHASE_6E_SETUP.md` and the retained CMake cache.

Target `whisper-cli` reached 100% and build exited 0. Upstream emitted a CMake
minimum-version deprecation warning, missing optional ccache warning, and Git
metadata warnings because the source came from an archive, not a Git checkout.
These did not fail the build. No ccache/package was installed to silence them.
The immutable source commit is recorded separately from archive build metadata.

## 10. Shared-library compatibility

Installed executable launched with `--help` and `--version` outside its build
directory, including after moving to the stable runtime root. `ldd` resolves all
runtime libraries: libgomp, libstdc++, libm, libgcc_s, libc and the loader.
Whisper/ggml/common code is static; there are no libwhisper/libggml runtime paths
into the build tree and no missing library. This is a native CPU build for this
laptop, not a guaranteed portable binary for other CPUs.

## 11. Persistent configuration details

Created **`~/.config/friday/voice.json`**, owner-only mode 0600, atomically from a
private temporary file after successful hash and compatibility checks. Used only
the existing schema: integer `version: 1`, actual absolute `binary` and `model`
paths, full `model_sha256` pin. Updated the file created by this restoration when
moving the installation; no pre-existing configuration was overwritten.

No new config format or backend settings fields. Existing ALC256/native capture/
eight-second defaults and decoder flags remain unchanged. XDG discovery, CLI
field override precedence, complete-override recovery, checksum validation,
owner/permissions/symlink/schema checks all remain intact. Startup constructs a
lazy backend without recording, model load or speech playback.

## 12. Configuration inspection result

`.venv/bin/python -B -m friday.main --check-voice-config` exits **0** and reports:
`status: verified_files`, `microphone: OFF`, saved binary/model under the stable
root, and the correct full tiny.en pin. Its existing message accurately limits
that check to files/checksum. Actual decoder compatibility was verified separately.
Normal CLI composition can now discover the installed backend without voice
flags; the missing-config condition is resolved. No live capture is claimed.

## 13. Synthetic-audio transcription

Already-installed eSpeak NG 1.52.0 generated WAV bytes with `--stdout`, never
speaker playback. Local standard-library linear resampling/dual-channel packing
created 48 kHz stereo PCM16 matching FRIDAY capture input. This conversion was
only for the synthetic fixture; capture preprocessing was not changed.

Expected: **“Hello Friday. What is a Python decorator?”**

Actual: **“Hello Friday, what is a python decorator?”**

Fixture duration: **3.506833 s**. Passed installed binary/model through the actual
`LocalVoiceBackend.transcribe()` WAV checks and stdout parser. Production English,
four-thread CPU, beam/best-of 5, temperature 0, no fallback/timestamps/diagnostic
printing flags were used. GNU time measured only decoder execution, while the
backend retained its 60-second timeout. Successful nonempty transcript and exit0;
no decoder error was surfaced. Results-only mode suppresses decoder diagnostics,
so this is not a claim that every internal warning was observed.

Initial installed-location check: **0.919 s**, **179,600 KiB peak RSS**. After stable
relocation: **0.883 s**, **179,744 KiB peak RSS**. Both produced the same transcript.
Temporary directories/WAV/RSS files were verified removed. No microphone, cloud
call or speaker output. Public synthetic phrase/results were recorded for this
report; no private transcript was involved. Synthetic success is not independent
live recognition accuracy, a multi-phrase benchmark or audible playback proof.

## 14. `/q hello` bug fix and input prefix

Main now splits the command token and arguments before dispatch. `/q` toggles;
`/q hello` prints exactly `Usage: /q`, preserves state and never reaches model,
tools, capture, speech playback or memory writes. Surrounding whitespace,
casefolding and whitespace separators follow existing parsing conventions.
`/voice extra` and `/bye extra` print usage; empty `/speak` prints
`Usage: /speak TEXT`. Unknown slash commands receive fixed feedback without
reflecting supplied private input. `/speak TEXT` still accepts text; `exit`,
`quit`, `/bye` retain behavior. Normal non-slash requests remain unchanged.

Inspection found exactly one `input("You: ")` prompt. A manually typed prefix can
produce “You: You: hello”. Owner should type `hello`, not `You: hello`. No prompt
stripping or unsupported assumption of a duplicate-prompt code defect was added.

## 15. Automatic speech regression results

Existing session SpeechController and eSpeak backend were preserved byte-for-byte.
Fake backend tests confirm default ON, print/flush before single playback,
OFF/ON toggles, session reset, manual playback independent of automatic state,
missing executable/timeout/audio failure/cancellation handling, and no startup
playback. Confirmed voice requests still use the same provenance policy once.
Permissions, files, listings, untrusted outputs and diagnostics remain silent.
No model-generated label can grant eligibility. Model text is not logged or
queued by the controller; no shell invocation or overlapping subprocess queue.

Available non-hardware TTS diagnostic: `espeak-ng --version` reports 1.52.0.
Its presence/success messages do not prove audible hardware playback. No actual
speaker test was run.

## 16. Repository files changed in this restoration increment

- `friday/main.py`: reserved/unknown slash-command validation before dispatch.
- `tests/test_voice_automatic.py`: five CLI parsing/state/exit regression tests.
- `tests/test_voice.py`: two decoder launch/nonzero/shared-library failure tests.
- `tests/test_voice_foundation.py`: non-executable dependency rejection test.
- `README.md`: installed status, slash usage and prompt-prefix guidance.
- `docs/PHASE_6E_SETUP.md`: actual approved install/build/integrity/config results,
  owner instructions, upgrade procedure and limitations.
- `PHASE_6E_REPORT.md`, `PHASE_6E_AUTOMATIC_SPEECH_REPORT.md`: historical-status
  pointers to this report; earlier evidence preserved.
- `PHASE_6E_RESTORATION_REPORT.md`: this report (new).

Previously dirty files remain dirty/untracked; `git diff` includes earlier
increments as well. Owner runtime/config/provenance files were created outside
Git. No downloaded artifact was added to Git.

## 17. Full Python results

Final `.venv/bin/python -B -m unittest discover -s tests`:
**909 passed in 5.407 s**, zero failures/errors/skips. Eight new tests above the
independently measured 901 baseline. A first new test incorrectly expected SQLite
persistence for adaptive L0 greetings; inspection confirmed existing greetings
are intentionally not persisted. Its expected value was corrected; no production
routing/persistence behavior was changed and no existing assertion weakened.
Final suite was rerun after real saved configuration and stable installation.

## 18. Focused voice results

`.venv/bin/python -B -m unittest discover -s tests -p 'test_voice*.py'`:
**139 passed in 0.524 s**. This is a subset of 909, not additional tests.
Existing cases cover valid/invalid saved config, missing files, checksum mismatch/
match, CLI precedence, confirmation/cancellation/privacy, readiness/full speech
window, capture and decoder timeouts, cleanup/interruption, and speech safety.
New launch/nonzero tests cover missing runtime library errors with no private
backend output exposure. All automated capture/playback remains fake.

## 19. Native/build/check results

`make -C native/sync`: exit **0**, already current (“Nothing to be done for all”).
`.venv/bin/python -B -m unittest discover -s tests -p test_sync.py`:
**31 passed in 0.207 s**, also a subset of the full suite. Native source/build
configuration was not changed. `git diff --check` passes. Final branch remains
`feature/voice-foundation` with uncommitted modifications/untracked files.

## 20. Performance observations

Tiny.en remains lightweight baseline; final synthetic run peak ~175.53 MiB and
0.883 s decoder latency on 3.507 s synthetic audio. These are individual warm/cold
context-dependent subprocess measurements, not guaranteed production bounds or
live accuracy. Model loads only on explicit processing; no resident Whisper
server or extra heavy model was added. Four decoder threads and CPU-only options
are unchanged; no base.en comparison was run. If live accuracy remains poor,
collect independent owner recordings and compare matched offline inputs later.

## 21. Security/privacy preservation

Preservation hashes confirm `PHASE_6D_BENCHMARK.json`, voice backend/CLI/config/
TTS, core assistant and response metadata unchanged in this increment. No
permission, navigation, adaptive routing or memory-policy code was changed.
Transcript typing/confirmation remains mandatory; voice cannot approve filesystem
permissions. Voice dispatch uses `respond(..., persist=False)` and stays out of
SQLite/reusable history. Private audio cleanup precedes confirmation/tools.

No sudo, system packages, virtual-environment modifications, gain changes,
cloud speech, always-on recording, wake word, startup service, Piper or extra
model. Approved source/model download operations used HTTPS; synthetic decode
itself was offline. No remote script was piped/executed. Microphone startup OFF
and no speaker/microphone hardware use during development.

## 22. Known limitations

Actual audio devices/readiness/recognition/playback remain owner validation.
The backend still targets the historically verified ALC256 device/card; this
hardware has not been re-proven live here. Quiet readiness/pre-roll remains;
full eight-second speech starts after the ready cue. No normalization/trimming/
gain change or unsupported accuracy improvement claim.

Positive public-topic/context policy is conservative: not every free-form normal
answer is eligible; restored/private/unknown context stays silent. Manual `/speak`
is explicit owner-supplied playback and not an automatic policy override.
TTS remains eSpeak, bounded synchronous 60 s/8192 bytes; Piper is future work.
Long responses may exceed playback bounds while terminal text stays visible.
Terminal scrollback may retain displayed text; SIGKILL/crashes can interrupt
audio cleanup; independent OS audio infrastructure may buffer. Executable file
checks do not authenticate arbitrary replacements; retain owner-only runtime
permissions and use explicit reviewed upgrades. Initial source authenticity is
HTTPS/pinned tag provenance, not an independently verified signature.

## 23. Owner live validation commands — pending

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive
```

At the prompt, type only:

```text
hello
/q
hello
/q
/q hello
/speak Hello, I am FRIDAY.
/voice
```

Expect first greeting audible, disabled greeting silent, re-enable confirmation
silent, malformed `/q hello` usage with state preserved, manual speech once.
For voice, press Enter for explicit activation, wait for **CAPTURE READY — SPEAK
NOW**, say **Hello Friday**, inspect preview. Type `n`/Enter to cancel or `y` only
if accurate. Eligible reply should print and speak once if enabled. Repeat with
**Open my downloads folder**, confirming transcript before separate typed
filesystem permission. Prompts/listings should not speak. Confirm OFF after each
capture. Ctrl+C cancels safely. Report actual audible output/transcript/capture
results; no owner test is marked passed in this report.

## 24. Remaining release blockers

Approved restoration criteria verified: v1.9.5 persistent executable, matching
model checksum, installed launch/library resolution, valid saved config,
synthetic decoder/format/parser, malformed command rejection, automatic speech
fake regressions, startup OFF, mandatory transcript confirmation, full Python/
native checks, no unauthorized install/Git mutation.

**Still pending:** owner speaker playback and microphone capture/recognition,
owner review of transcript cancellation and typed permissions in real operation,
review of conservative automatic speech coverage, and release review. No further
installation approval is needed for the completed restoration; additional models,
packages or listening modes would require separate approval. Full v0.5.0 remains
IN PROGRESS. Next roadmap milestone after approved v0.5.0: **v0.6.0 Phase 6F —
Wake Word & Natural Conversation**, with listening modes separately designed and
approved, not implemented now.

## 25. Git history safety

No commit, push, merge, tag, reset, rebase, stash or clean was executed. Existing
changes remain uncommitted. No branch switch or release tag. Benchmark is
unchanged. Final status/check evidence is available through the same read-only
commands; owner authorization is still required for any history mutation.
