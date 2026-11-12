# Welcome and recent projects

The dashboard greets the owner using local time and offers to resume approved
work. It never reopens applications automatically and does not block chat.
Choose Another Project opens the VS Code chooser; Dismiss welcome opens AI Chat.

Successful chooser launches use the existing `RecentWorkQueue` and
`data/friday.db` recent_work table. This is the original approved activity store,
not a parallel JSON history. SQLite transactions persist across restarts/reboots.
New chooser-created database files have mode 0600; existing files are preserved.
Only launch metadata (application, display name, path, identity, operation and
last-opened time) is recorded. No document contents, source code, browser history,
conversation bodies or outside application usage are imported by this feature.

The desktop requests a maximum of ten recent activities, most recent first, with
path/application deduplication. Legacy terminal menus remain three numbered items.
The existing record integrity checks reconstruct display metadata and reject
modified/unsafe records. Missing paths are omitted from the dashboard without
silently deleting saved metadata. Renamed paths require choosing the new folder.

**Continue <project> in VS Code** revalidates that the saved path still exists and
is an authorized direct child of `/home/vigneshwar/Projects`. A historical entry
outside this root can be displayed but cannot bypass the new chooser validation.
Other application activity remains visible with guidance to use the existing
permission-controlled Desktop Tools. Dismiss entry removes that entry;
Clear recent work deletes only recent_work rows, leaving knowledge, conversations,
other tables and integrity migration archives untouched.

Owner acceptance: choose two real projects, close/reopen the GUI and reboot, then
confirm each Continue action opens its exact folder. Repeat one project and confirm
there is one entry. Remove an entry, verify missing folders are not offered, and
clear the visible list if desired. Codex used temporary folders, temporary databases
and mocked VS Code processes for these checks. No real VS Code window was opened.
See the additional Phase 2A report for test results and limitations.
