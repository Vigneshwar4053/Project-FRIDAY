# Phase 6E — Installed offline voice foundation

Latest capture lifecycle evidence: [PHASE_6E_CAPTURE_REPORT.md](../PHASE_6E_CAPTURE_REPORT.md).
Dependency restoration below remains valid; no reinstallation is needed.

The owner approved the specific Whisper v1.9.5 download, local CPU build,
tiny.en download/checksum, persistent installation, configuration and synthetic
compatibility checks. Those operations were completed on 2026-10-09. No system
packages, virtual-environment packages, other models or background services were
installed. No microphone or speaker hardware test was performed.

Yesterday's trial worked because its Whisper executable/model existed under a
private `/tmp` trial directory. That directory disappeared. Today's failure
was missing dependencies plus no saved voice configuration, not evidence of a
broken microphone. The existing subsystem was reused.

## Installed layout and integrity

Runtime uses the stable XDG default data location `~/.local/share/friday/voice/`:

```text
voice/
  bin/whisper-cli
  bin/whisper-cli.sha256
  models/ggml-tiny.en.bin
  build-source/whisper.cpp.tar.gz
  build-source/source-provenance.json
  build-source/whisper.cpp-d1be6fde11ac6e0407606b4e42fe72d34add8037/
  build-source/build/
```

The editor supplied a revision-specific Snap XDG_DATA_HOME. Downloads/build first
used that directory, then the entire installation was moved to the stable default
above. There is one model copy. Saved absolute paths make normal terminal startup
independent of a launcher's data-directory environment. `--check-voice-config`
may display that launcher's `dependency_directory` candidate; its `binary` and
`model` fields are the actual saved paths. No global environment was changed.
The moved build cache records the original build location: rebuild with a fresh
build directory, rather than reusing that cache. Installed runtime libraries do
not depend on that build directory.

| Artifact | Verified value |
| --- | --- |
| Release | Whisper.cpp v1.9.5 |
| Source commit | `d1be6fde11ac6e0407606b4e42fe72d34add8037` |
| Annotated tag object | `d2a764c648779feb36d44363f212a29b00aad1af` |
| Source archive size | 9,631,456 bytes |
| Source archive SHA-256 | `645445da884df6dbd52b30f82d7be7c01d1767c938714e477e786b88d529e9f4` |
| Installed executable size | 3,385,824 bytes |
| Installed executable SHA-256 | `c488e598e073312a7addb7b5964ca1ae060656e1637df511d4060a49bdb2472a` |
| Original tiny.en size | 77,704,715 bytes |
| tiny.en SHA-256 | `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f` |

Official [v1.9.5 release](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5),
[immutable source archive](https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/d1be6fde11ac6e0407606b4e42fe72d34add8037),
and [maintainer tiny.en source](https://huggingface.co/ggerganov/whisper.cpp/resolve/80da2d8bfee42b0e836fc3a9890373e5defc00a6/ggml-tiny.en.bin).
The tag was resolved through upstream GitHub API; its tag signature metadata says
unsigned. HTTPS source provenance and a locally recorded archive hash are not an
independent source-signature verification. The model matches the independently
specified owner pin. Downloads used HTTPS-only redirects, temporary `.partial`
files, and final rename after completion/checksum verification.

## Build and compatibility

Existing CMake/GNU 15.2.0 toolchain, Release, two build jobs, static Whisper/ggml,
CPU native optimizations and installed OpenMP. No GPU, BLAS, CURL downloads,
server, upstream tests, SDL audio or FFmpeg dependency. Target `whisper-cli` only.
The executed configuration was:

```bash
cmake -S "$friday_voice_source" -B "$friday_voice_build" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_BUILD_IS_DEV=OFF \
  -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_CURL=OFF \
  -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_OPENCL=OFF -DGGML_BLAS=OFF
cmake --build "$friday_voice_build" --target whisper-cli --parallel 2
```

This is a build record, not an instruction to rerun installation. Future downloads
or upgrades need owner approval. `--version` reports 1.9.5. `--help` and `ldd` work
outside the build directory. Only installed system libgomp, libstdc++, libm,
libgcc_s, libc and the dynamic loader are required; none is missing. Whisper/ggml
are linked statically. Native optimizations target this laptop; rebuild for a
different CPU instead of assuming portability.

FRIDAY's unchanged decoder uses English, four threads, CPU/no GPU, beam size 5,
best-of 5, temperature 0, no fallback, no timestamps, results-only stdout, and a
60-second bound. The built CLI supports all these flags. No v1.8.2 substitution
occurred. The previous v1.8.2 proposal was superseded, not executed.

Synthetic speech generated with already-installed eSpeak NG `--stdout` (no
playback), converted locally to native 48 kHz stereo PCM16, successfully passed
through `LocalVoiceBackend.transcribe()`. Phrase: “Hello Friday. What is a Python
decorator?” Output: “Hello Friday, what is a python decorator?” Latest decoder
latency 0.883 seconds, peak RSS 179,744 KiB. Audio duration 3.507 seconds. Temporary
audio/measurement files were removed. This proves format/model/decoder/parser
compatibility, not live microphone accuracy or audible TTS.

## Owner configuration

Owner-local `${XDG_CONFIG_HOME:-~/.config}/friday/voice.json` uses the existing exact
schema; the installed file is `~/.config/friday/voice.json`, permission 0600:

```json
{
  "version": 1,
  "binary": "/absolute/owner/data/friday/voice/bin/whisper-cli",
  "model": "/absolute/owner/data/friday/voice/models/ggml-tiny.en.bin",
  "model_sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"
}
```

The real file contains resolved absolute paths, not the example placeholders.
Executable mode is 0700, model mode 0600, voice directories 0700. CLI overrides
still take precedence; model validation and configuration owner/permission/schema
checks remain unchanged. Backend capture settings remain the verified ALC256
hardware device, 48 kHz stereo, eight seconds after readiness. They are defaults
in the existing backend, not extra JSON fields.

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive
```

Inspection returns exit 0, `status: verified_files`, microphone OFF. It hashes
files without launching a decoder, microphone, playback or assistant session.
Actual synthetic compatibility was verified separately. Startup discovers saved
configuration without long voice flags; microphone remains OFF.

## Owner live validation — pending

Capture uses the same ALC256 direct-hardware identity/ownership/advancing-pointer
checks and native 48 kHz stereo S16_LE format. The successful owner `default`
16 kHz mono recordings do not establish this direct path's signal or format
behavior; no fallback to a different device was added.

The old normal SIGINT stop was replaced by bounded natural `arecord -d 12`
completion. Eight speech seconds still start after the flushed readiness cue;
the cue must finish within three seconds of launch. Expect a short additional
recording tail and “Speech window complete; finalizing recording.” before OFF.
Finalization waits at most four more seconds. Natural exit 0, a reaped child,
valid RIFF/chunk lengths, native PCM metadata/alignment, and exactly 576,000
complete frames are required. No partial-WAV header repair or nonzero-exit
allowlist. Cancellation/timeouts use SIGINT, then SIGKILL and reap if needed;
all interrupted recordings are discarded. If cleanup cannot be confirmed, the
session ends with an uncertainty diagnostic, rather than claiming microphone OFF.

Type only the text below at the existing `You: ` prompt; do not type the prefix.
Source inspection found one prompt, not a duplicated prompt. No stripping of
literal `You:` input was added.

1. `hello`: terminal greeting and automatic speech.
2. `/q`: printed “Automatic speech disabled.”; confirmation silent.
3. `hello`: terminal greeting, no speech.
4. `/q`: printed “Automatic speech enabled.”; confirmation silent.
5. `/q hello`: `Usage: /q`; no toggle, model call or recording.
6. `/speak Hello, I am FRIDAY.`: exactly one explicit playback.
7. `/voice`: press Enter to activate, remain quiet until **CAPTURE READY — SPEAK NOW**,
   then say “Hello Friday”. Finish within eight seconds. Inspect preview; type `n`
   (or Enter) to discard, or `y` only if accurate. Eligible reply prints and speaks
   once when automatic speech is enabled.
8. Repeat `/voice` with “Open my downloads folder”. Preview and typed confirmation
   precede dispatch. Filesystem approval remains a separate typed permission.
   Permission prompts/listings remain silent. Confirm microphone returns OFF.

Ctrl+C cancels activation/capture/transcription/confirmation. Existing speech
cancellation returns safely to the prompt. `exit`, `quit`, `/bye` retain exit
behavior. `/voice extra`, `/bye extra`, empty `/speak`, and unknown slash commands
receive CLI feedback and never become model prompts. `/speak TEXT` accepts text
and works independently of `/q`.

Speech defaults ON if offline eSpeak passes file checks; startup itself is silent.
Only trusted provenance-approved public conversation/greetings may be spoken.
Unknown/private/restored context remains conservative text-only. No permissions,
private files, listings, tool output, diagnostics or untrusted content is spoken.
This public-topic policy does not cover every free-form ordinary answer.

Raw audio lives only in private temporary directories and is cleaned before
confirmation, including ordinary failure/cancellation. Voice transcripts/replies
remain session-only; no global privacy toggle, SQLite turn or reusable voice
history. Terminal scrollback, SIGKILL/crash cleanup interruptions and independent
OS audio buffers remain limitations. No gain change, always-on input, cloud
speech, wake word, Piper model or startup service is introduced.

## Safe dependency upgrade procedure

Obtain separate approval for the precise new version/model/source first. Resolve
the official tag to an immutable commit; inspect build and supported flags.
Use a new owner-private staging/build directory outside Git. Download over HTTPS
to partial files; verify the full approved model hash before final placement.
Build CPU-only without remote install scripts or new system packages. Record
source/binary hashes and build cache. Verify installed-location libraries, then
synthetic native-format decoding through FRIDAY before changing saved config.
Update only the existing JSON schema atomically after checks; preserve the old
working runtime for rollback. Run fake regression tests and obtain owner live
validation. Do not silently change versions/models or auto-download on startup.

The restoration is prepared for owner hardware testing. Full v0.5.0 remains
**IN PROGRESS** until actual microphone and speaker validation and release review.
