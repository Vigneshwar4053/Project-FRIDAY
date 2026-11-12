# Voice interaction

The Voice page is reachable from Settings → Voice preferences. Speech and Speak Welcome Greeting default to OFF and save locally in the existing desktop preferences. Choose an installed voice, speed and volume; Test Voice reports process success or a safe failure, not proof that sound was heard. Missing saved voices select an installed fallback with a notice. Output routing uses Ubuntu's system default; this adapter does not expose device selection.

`Talk to ZORVYQ` is available in both conversations and Voice. First enable microphone actions for this session. Each click asks permission for one bounded local capture. Wait for the SPEAK NOW cue. Stop recording / Cancel transcription discards that attempt. There is no startup recording or always-on listener.

Visible states are IDLE, LISTENING, TRANSCRIBING, PROCESSING, SPEAKING and ERROR. The Voice page displays the state; the window title displays active/error states from any page. Workers emit signals to Qt rather than modifying widgets.

After successful transcription, temporary audio is removed. Review the recognized words, edit or cancel, then press Send in AI Chat. Neither the recording nor an unconfirmed transcript is submitted to a model. Session chat is not persisted. Confirmed task intents use the same deterministic handler as text and require a separate task edit/change confirmation.

Ordinary requests retain the selected Qwen3:4b or Foundation-Sec model and Short / Medium / Deep Analysis setting. The existing model synchronization and residency rules remain intact. Automatic speech uses trusted response provenance and excludes private, unknown, tool and RAG responses. Speak this answer asks explicit permission for an answer the owner wants read aloud. Code, citations and tables get a brief spoken notice; long prose uses a short summary. The full answer stays visible. Stop speaking signals the owned eSpeak process and the worker reaps it.

Welcome speech waits up to 20 seconds for a desktop audio socket and an idle worker. When enabled along with speech, it makes at most one attempt per application startup. It uses the time-of-day greeting and actual task count. A failed attempt leaves the visual greeting available; focus changes do not retry it or activate recording. Recent-project launch still uses existing explicit project selection.

## Owner-operated acceptance (no development audio tests were run)

1. Open Voice, enable speech, choose an installed voice, set a comfortable volume, click Test Voice and confirm audible sound. Test Stop speaking with a longer entered sentence.
2. Enable session microphone actions. Click Talk to ZORVYQ and deny: no recording should start.
3. Activate again and approve; wait for SPEAK NOW, say “Explain Python”, review and correct the words, then Send. Confirm the selected model answers visibly and speech works when eligible.
4. Repeat and cancel during capture, during transcription, and during transcript review. No cancelled input should be submitted. Early recording stop intentionally discards the attempt.
5. Try “Add a task to review my project tomorrow.” Confirm transcript, Send, inspect the editable task form and Save. Review actual pending count; do not expect a reminder unless a reminder time was explicitly saved.
6. Disable speech and verify no spoken answer. Enable welcome speech, restart once and verify one greeting; change focus repeatedly and confirm silence. Confirm the microphone remains off at startup.
7. Verify a RAG response stays silent unless explicitly requested. Confirm missing/busy hardware produces a visible failure without cloud fallback.

Known limits: exact approved ALSA device only; English tiny.en; recognition accuracy, microphone access, audible output, desktop routing and Wayland behavior await these manual tests. No new dependency is required by the file inventory.
