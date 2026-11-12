# ZORVYQ voice settings

Settings → **Voice preferences** opens **Settings → Voice** (also accessible from
the Voice sidebar). This extends the existing eSpeak NG output and local capture
backends. No audio engine, voice model or package is downloaded.

Enable explicit speech output, select an installed voice, adjust speed (80–450)
and volume (0–200), then press **Test Voice**. The preview is “Hello, I am ZORVYQ,
your local AI assistant.” It is never played at startup. “Speak entered text” is
also explicit; chat and private RAG responses are never spoken automatically.

Inventory comes from the installed `/usr/bin/espeak-ng --voices`; the File column
provides engine voice identifiers. This host reported 141 inventory rows during
read-only inspection. Inventory establishes installation, not successful audible
playback for each voice. An empty inventory is unavailable; one voice is labeled
as a limitation. A missing saved voice falls back to an installed English voice
or the first installed voice and displays a notice.

Necessary preferences are stored atomically in
`~/.config/zorvyq/desktop.json`, or `$XDG_CONFIG_HOME/zorvyq/desktop.json` for an
absolute configured XDG root. New files have mode 0600. Voice ID, speed, volume
and explicit-output enabled state persist. Answer length and hidden-folder choice
share this local preference file. No preview text, recording or transcript is saved.
Legacy `~/.config/friday/voice.json` configuration remains intact for capture.

**Enable microphone actions for this session** starts OFF at every launch. It does
not record; a separate **Activate microphone once…** action requires confirmation.
Captured audio is temporary, removed before transcript review, and sending the
transcript remains separate. No microphone enabled state is persisted.

The current backends expose system-default devices only. Input/output selectors
are disabled with this limitation stated; arbitrary devices are not advertised.
Engine presence, device presence and the last safe audio error are displayed.
`voice_inventory_unavailable`, `speech_disabled`, `offline_playback_failed`, and
capture/cleanup failure categories reveal no private speech text or raw backend logs.

Earlier terminal speech failures remain unverified on the physical device. The
existing backend treats nonzero exit status **or stderr diagnostics** as failure,
including eSpeak failures that exit zero. The GUI exposes this instead of claiming
that playback is fixed. An unconfirmed capture cleanup disables further operations.

Owner acceptance: enable output, test an installed voice at a comfortable volume,
confirm audibility, change speed/volume, restart and verify preferences. Temporarily
select another system audio output if diagnosing failure. Verify microphone stays
OFF until both explicit steps, and review/discard a transcript before testing Send.
These device checks have not been performed by Codex. Automated tests mock inventory,
playback, missing voices, preferences, disabled output and audio errors; see the
additional Phase 2A report for the regression result.
