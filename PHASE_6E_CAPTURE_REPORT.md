# Phase 6E — Capture reliability and process lifecycle

**Status: ready for owner-controlled live validation; v0.5.0 IN PROGRESS.**
Branch `feature/voice-foundation`. Dependencies were preserved, not reinstalled.
No microphone/speaker hardware use, dependency downloads/installations, gain or
Ubuntu audio changes, or Git history mutation occurred in this increment.

## A. Diagnosis and evidence

The owner reached the ready cue, then saw generic “Audio capture failed.”
Configuration is valid; Whisper/model presence does not diagnose capture.
Baseline full suite: **909 passed in 5.314 s**. Initial worktree retained the
previous tracked modifications and untracked voice/tests/reports/benchmark.
No applicable AGENTS.md was found in the repository or inspected ancestors.

Installed `arecord --version`: **1.2.15.2**. Read-only `/proc/asound` still reports
card1 PCM0 CAPTURE, ALC256 Analog, initially closed. No device was opened.
The owner reports two successful `default`/16 kHz/mono recordings; that establishes
that recording commands can complete on that path, not that this backend's
48 kHz stereo direct path or signal finalization succeeds.

Confirmed code defect: normal completion intentionally sent SIGINT but accepted
only exit 0. Matching [upstream arecord source](https://github.com/alsa-project/alsa-utils/blob/v1.2.15.2/aplay/aplay.c)
shows the SIGINT handler marks abort; the capture loop can finalize the WAV and
then exit failure (1). Thus a finalized file can accompany a rejected abort
status. A controlled synthetic subprocess reproduced a finalized WAV/exit1.
Other fixtures reproduced -SIGINT and -SIGKILL and verified reap.

**The owner's exact return code/stderr was not recorded.** This proves a lifecycle
mismatch and a plausible explanation, not a confirmed live-device root cause.
A device/xrun/finalization problem may still exist. No live accuracy claim.

## B. Files changed in this targeted increment

- `friday/voice/backend.py`: natural-duration capture lifecycle, strict shared
  WAV validator, bounded drain/reap/escalation and fixed diagnostic categories.
- `friday/voice/cli.py`: explicit bounded finalization wording; cleanup uncertainty
  propagates as fatal instead of returning to normal input.
- `friday/main.py`: fixed cleanup-uncertainty session shutdown, preserving existing
  context/session/controller cleanup.
- `tests/test_voice_capture.py` (new): **37** synthetic WAV/process/lifecycle tests.
- `tests/test_voice.py`, `tests/test_voice_foundation.py`: existing timing/capture
  fixtures now model elapsed time, natural finalization and complete WAV output;
  shared subprocess tests assert the additional pipe-drain/reap call.
- `tests/test_voice_automatic.py`: one fatal cleanup CLI regression.
- `README.md`, `docs/PHASE_6E_SETUP.md`: current capture behavior and owner steps.
- `PHASE_6E_RESTORATION_REPORT.md`: follow-up pointer; historical evidence retained.
- `PHASE_6E_CAPTURE_REPORT.md`: this report.

No response eligibility, permission, routing, configuration-schema, device policy
or dependency changes. All unrelated uncommitted/untracked files were preserved.

## C. Lifecycle before and after

Exact recording arguments remain:

```text
/usr/bin/arecord -D hw:CARD=Generic_1,DEV=0 --fatal-errors
-t wav -f S16_LE -r 48000 -c 2 -d 12 <private-temporary-WAV>
```

No shell; new process group; stdin disabled; stdout/stderr captured and never
printed. Twelve seconds is the existing eight-second duration plus four seconds
of readiness headroom, now used as the normal frame-limited completion request.

Before: identity/closed check → owned advancing RUNNING pointer → exact native
hardware format → 0.8 s stabilization/progression → ready cue → eight-second wait
→ SIGINT → two-second reap → reject every nonzero status. No finalized/full-length
WAV evidence was required at capture completion.

After: request bounded natural duration at process launch → retain all hardware
checks/readiness → reject cue delays beyond three seconds of launch → flushed
ready cue → verify eight post-cue seconds with monotonic time → announce speech
window complete → allow at most four seconds for natural completion → require
exit0/reap → validate full finalized WAV → report OFF. Normal SIGINT was removed,
not accepted via a numeric allowlist. FRIDAY requests normal stopping through the
explicit arecord duration; success must fulfill that request.

This preserves the complete post-cue speaking window. Capture intentionally
continues briefly through a bounded tail until its twelve-second frame limit;
stay quiet once the speech-window-complete message appears. Both pre-roll and
tail remain untrimmed. `arecord -d` is a frame limit; wall-clock stalls are still
bounded by Python waits and cleanup, not assumed to complete exactly at 12 s.
The outer capture waits are ≤2 s readiness, 0.8 s settling, eight-second speech,
four-second finalization, plus up to two+two seconds of cleanup. Scheduling and
small /proc/file/print operations are not a hard realtime guarantee; a delayed
cue is refused rather than reducing the speaking window.

## D. Exit codes, signals and cleanup

| Event | Handling |
| --- | --- |
| Natural exit0 after complete window/full file | Accept |
| Natural exit0 before full window | Reject, even with a synthetic full-length file |
| Any unexpected negative signal status | Reject |
| Any positive nonzero/device/process error | Reject; fixed diagnostic, no raw stderr |
| Intentional SIGINT during cancellation/failure | Drain/reap; recording discarded regardless of exit0, exit1 or -SIGINT |
| SIGINT ignored | SIGKILL after two seconds, then two-second reap; discard |
| Cleanup signal lookup race | Still attempt bounded drain/reap |
| Ctrl+C during cleanup | Kill/reap, then preserve cancellation |
| Cleanup still unconfirmed | Fixed uncertainty diagnostic; end CLI session, no model dispatch and no false OFF claim |

Signals are only in the explicit cleanup path. The normal path never accepts a
signal-related exit, so an unexpected signal cannot impersonate requested normal
completion. Already-ended children also have pipes drained/closed and are reaped.
Successful model/TTS playback behavior is unchanged; the shared cleanup helper's
additional drain/reap is covered by fake TTS regressions.

A kernel process stuck in uninterruptible I/O cannot be guaranteed to disappear
within a Python timeout even after SIGKILL. Tests simulate this exceptional case;
the application ends its session and reports uncertainty instead of hiding it.
This is a documented OS limitation, not a claim of guaranteed shutdown in that
case. Ordinary cancellation/failure fixtures prove no surviving recording child.

## E. WAV integrity and lifetime

Validator opens without following symlinks/nonregular files and bounds file size.
Requires RIFF/WAVE, finalized RIFF length equal to actual file size, complete chunk
boundaries/padding, unique format/data chunks, and aligned complete PCM payload.
Format must be uncompressed integer PCM, two channels, 16-bit samples, 48,000 Hz,
192,000 bytes/s, four-byte frame alignment. Frame count/read length must agree.
Natural capture specifically requires **576,000 frames** (twelve seconds), not
merely a nonempty recording. Decoder input repeats validation with the existing
≤twelve-second bound; harmless shorter synthetic decoder fixtures remain valid.
No normalization, trimming, header rewrite or partial-recording salvage.

Audio remains inside a private temporary directory. WAV/temporary directory
cleanup occurs on ordinary success/error/cancellation and before transcript
confirmation/assistant dispatch. Fatal cleanup uncertainty also unwinds temporary
file/session/controller contexts. No permanent raw audio or transcript store.

## F. Security invariants

Explicit `/voice` plus Enter activation; startup OFF; visible cue; bounded capture;
no always-on/wake word/background service. Direct ALC256/card/device trust policy
and owned-pointer checks preserved. `default`/PipeWire fallback was not introduced:
its virtual PCM ownership/format may not match the verified hardware readiness
contract, and owner device intent must not be guessed.

Typed transcript preview/confirmation remains mandatory. Capture failure calls
neither STT nor assistant; voices remain `persist=False`, outside SQLite/reusable
history. Spoken approval cannot authorize tools. Permission-gateway behavior,
adaptive L0–L3 and trusted sensitive-output speech restrictions remain intact.
All diagnostics are fixed categories without private paths, samples, transcripts,
raw stderr/environment or tokens; diagnostic strings never enter automatic speech.

Preservation hashes match benchmark, configuration loader, TTS source, assistant
and response provenance. Existing model pin remains:
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
Whisper binary remains:
`c488e598e073312a7addb7b5964ca1ae060656e1637df511d4060a49bdb2472a`.
No audio cloud services or network transcription. Only upstream source was read
for diagnosis; no dependency archive/model/package was downloaded.

## G. Validation results

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -B -m unittest discover -s tests` | **947 passed, 7.475 s** |
| `.venv/bin/python -B -m unittest discover -s tests -p 'test_voice*.py'` | **177 passed, 2.730 s** |
| `make -C native/sync` | Exit0; already current |
| `.venv/bin/python -B -m unittest discover -s tests -p test_sync.py` | **31 passed, 0.207 s** |
| `git diff --check` | Passed |
| `--check-voice-config` | Exit0, verified_files, microphone OFF |
| Local model/binary checksums | Unchanged |

Focused/native counts are subsets of 947. **38 new tests** above the verified
909 baseline. No failures/errors/skips in final runs. Earlier mocks assumed
normal SIGINT, no completed WAV, or an immediate synthetic timeout; they were
updated to model the new lifecycle without weakening timing/security assertions.

New coverage includes natural completion/full cue window; early/nonzero/signal
exits; readiness timeout/wrong owner; delayed cue; cancellation; ignored SIGINT/
SIGKILL; cleanup uncertainty/fatal CLI exit; missing/corrupt/truncated/unfinalized/
wrong-format/empty/oversized WAVs; rate/alignment mismatch; FIFO/symlink rejection;
no decoder on invalid file; temporary cleanup and no dispatch on capture failure.
Controlled non-audio subprocesses record exact exit1, -SIGINT, -SIGKILL behavior
and are reaped. Existing identity/busy-device, permission/privacy, automatic
speech, `/q`, `/q hello`, `/speak`, and navigation/routing regressions still pass.

## H. Remaining limitations

No autonomous live recording or speaker playback. Hardware direct-path success,
post-cue audio quality, natural WAV finalization on the installed device and live
recognition accuracy remain unverified. No gain/fallback/model change. Terminal
scrollback, SIGKILL/system crash cleanup interruption and OS audio buffers remain
privacy limitations. Cleanup uncertainty is explicitly fatal, not silently OFF.

## I. Owner validation commands — pending

```bash
cd ~/Projects/FRIDAY
.venv/bin/python -B -m friday.main --check-voice-config
.venv/bin/python -B -m friday.main --adaptive
```

Type `/voice`; press Enter to activate. Stay quiet until **CAPTURE READY — SPEAK
NOW**, say **Hello Friday**, finish within eight seconds, then remain quiet through
**Speech window complete; finalizing recording.** Expect OFF, local transcription
and preview. Type `n`/Enter if wrong; `y` only if accurate. Verify text reply and
eligible speech once. Test Ctrl+C cancellation separately and confirm OFF. After
a safe greeting succeeds, optionally test **Open my downloads folder** with
transcript confirmation before separate typed filesystem permission; no spoken
approval or listing playback. `/q`, `/q hello`, `/speak TEXT`, `/bye`, exit/quit
retain behavior. Type only input, not the printed `You:` prefix.

If failure remains, report the fixed error category and whether the cue/full-window/
finalization/OFF messages appeared; do not share private audio/transcripts. No
hardware test is marked passed here. Any agent-operated device experiment still
requires separate approval before capture.

## J. Git/worktree status

Branch stays `feature/voice-foundation`. Existing modified/untracked work remains,
plus the new capture test/report. No commit/push/merge/tag/reset/rebase/stash/clean
or other Git history mutation. Benchmark unchanged. No release tag; **Phase 6E
remains IN PROGRESS pending complete owner microphone→confirmation→response testing**.
