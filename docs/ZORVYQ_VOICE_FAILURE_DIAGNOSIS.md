# Phase 2C voice investigation — 2026-10-31

## Confirmed causes and limits

The existing Qt desktop only connected eSpeak NG to Test Voice and manually entered text. Chat completion never dispatched speech. There was no spoken startup greeting. The saved desktop preferences had `speech_enabled: false`; default preferences also disable speech. These explain silent conversational use without implying a broken audio driver.

The selected voice was `gmw/en-US`; installed inventory returned 141 voices from `/usr/bin/espeak-ng --voices`. The existing backend passes the selected voice, speed and amplitude through validated argv and text through stdin. It treats stderr or nonzero exit as an unverified playback failure, including eSpeak failures that exit zero. No playback was performed, so the owner's previous audible failure is not reproduced or attributed to hardware.

The legacy speech `stop()` was a no-op. It now signals only the owned playback process group; the worker still drains/reaps it. Transcript review was read-only and audio exceptions often became generic GUI worker errors. Review is now editable, with fixed safe audio categories and visible interaction states. Qt widget access and result handling stay on the GUI thread; blocking audio stays in the worker.

## Existing offline input

`friday.voice.configuration` loads the existing owner-provisioned `~/.config/friday/voice.json`. `LocalVoiceBackend` uses whisper.cpp, not a cloud service. Read-only inspection confirmed:

- Executable: `~/.local/share/friday/voice/bin/whisper-cli`.
- Model: `~/.local/share/friday/voice/models/ggml-tiny.en.bin`.
- Existing pinned SHA-256 verified: `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
- Native capture is deliberately restricted to `hw:CARD=Generic_1,DEV=0`, card 1, ALC256 Analog; ALSA metadata matched this identity and showed `closed` during inspection.
- PulseAudio compatibility and PipeWire session sockets existed. Their presence does not verify device access, microphone levels, output routing or audible playback.
- Qt is installed. No required offline engine/model dependency was found missing. No installation or download is requested at this point.

`arecord` records native 48 kHz stereo PCM. The backend verifies readiness, grants an eight-second speaking window, and permits up to four additional seconds for readiness/finalization. Files are temporary and removed before transcript review. Early stop cancels and discards the recording; it does not transcribe an incomplete WAV. Transcription has a 60-second timeout. Session cancellation now interrupts waits and reaps the owned subprocess.

The backend's exact-device and readiness restrictions can refuse busy, changed or inaccessible devices. No microphone was opened, so access and transcription compatibility remain owner acceptance items. Linux ALSA access is enforced by the operating system; the application requests explicit per-recording approval rather than pretending a Qt toggle grants OS permissions.

## Privacy and desktop behavior

Speech remains off by default. Welcome speech has its own default-off preference. Ordinary automatic replies use existing trusted response provenance; RAG, tools, private and unknown context stay silent. An owner can explicitly request speech for a visible answer. Sensitive credential-shaped text is still withheld. No cloud fallback, background microphone, model download or autostart change was introduced.

Wayland focus/input behavior cannot be certified with offscreen Qt tests. The buttons use Qt signals, with no global hotkey or focus automation. Output selection is unsupported by eSpeak's current adapter; Ubuntu's selected output is used. Capture selection remains the existing approved ALSA device.

## Owner acceptance

Follow `ZORVYQ_VOICE_INTERACTION.md`: test the selected voice, enable speech, explicitly activate the microphone, correct/cancel a transcript, send it, and verify an audible public response. Test cancellation and device-unavailable behavior. Keep desktop startup audio and Wayland focus acceptance separate from mocked tests. Neither speech recognition nor audible output is certified operational by this investigation.
