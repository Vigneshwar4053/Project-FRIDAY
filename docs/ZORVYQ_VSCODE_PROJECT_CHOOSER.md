# VS Code project chooser

Type **ZORVYQ, open VS Code** in AI Chat or Cybersecurity, or click
**Choose Another Project** on the dashboard. ZORVYQ checks for `code` on PATH,
then lists only direct child directories under `/home/vigneshwar/Projects`.
This host has `/snap/bin/code`. Missing launchers produce a setup message;
no package is installed automatically.

Names sort by case-insensitive name, then exact name, beginning with 1. Files
are excluded. Hidden folders are excluded unless enabled in Settings. Folder
listing never reads source-code contents. Click a numbered row or type its number
in the same chat. Selection expires after two minutes; any intervening non-number
message cancels that chat's selection before normal handling. Type **cancel** to
cancel explicitly. Opening a newer chooser invalidates older click snapshots.
Closing the floating chooser alone allows the requested numbered chat reply.

Selections are revalidated at execution: existing directories only, direct children
of the authorized root, symlinks resolved without escaping that root, no traversal
or control characters. Spaces and shell punctuation are separate literal arguments.
Execution is `[resolved_code_binary, '--new-window', validated_project_path]` with
`shell=False`, no stdin, no model-selected path and a 20-second launch timeout.
The assistant never runs project code.

A zero process exit records the accepted launch in the existing recent-work store.
A missing binary, timeout or nonzero exit saves nothing. Zero exit confirms only
that VS Code accepted the request, not window visibility or project execution.
Two-minute snapshots are in memory only; recent successful launches persist in
`data/friday.db`. See `ZORVYQ_RECENT_PROJECTS.md` for history controls.

Owner acceptance: request VS Code, verify the current numbered folder list, select
a folder by number, and check VS Code's workspace path. Repeat by clicking a row,
test Cancel, then restart and use Continue. Automated tests mock the launcher and
cover deterministic numbering, space-containing names, invalid/expired/stale
selections, symlink escapes, safe arguments, restart/deduplication and launch failures.
No owner's source files or real VS Code sessions are used in automated tests.
