> The [current lifecycle/compatibility repair](PHASE_7A_BROWSER_REUSE.md) supersedes the initial uncertain-channel cleanup and default-command decisions below. Live uncertain renderers now remain intact; bare Files commands use Nautilus and explicit Browser commands select managed navigation.

# Managed browser security design (implementation gate)

The existing Nautilus APIs cannot navigate an identified window to an arbitrary
reviewed folder. A separate FRIDAY Browser will provide that contract. It will
not replace Nautilus, control its windows or pretend to be Ubuntu Files.

Installed dependencies: system Python 3.14, PyGObject 3.56 and GTK 4.22. The venv
does not expose GTK; use a separately reviewed, pinned root-owned native system
interpreter with isolated imports and fixed reviewed helper code. No installation
or venv changes. Runtime checks fail closed if this interpreter or GTK is absent.

Process: one dedicated GTK process and window, created only after typed launch
approval. Parent holds an anonymous Unix socketpair; only its inherited child
endpoint is available to the helper. There is no listening socket, network port,
public D-Bus service, shell or general execution request. Messages have bounded
sizes, strict operation schemas and request identifiers. The child handles only
health checks, location presentation, supplied listing presentation and shutdown.
It cannot request reads, supply paths for execution or grant itself approval.
The parent verifies responses before committing history or Q. Window closure
ends the process/channel. Every action checks liveness; uncertain channels are
terminated and reaped before another managed process may start.

Permissions remain separate: (A) typed launch_browser approval for a new process;
(B) typed navigate_browser approval for each exact folder; (C) existing
FilesystemAccess/list_directory approval and policy for any listing; (D) no file
opening in this minimal browser; (E) no file modification. A launch approval does
not approve navigation. Navigation approval authorizes a location label only,
not directory contents. The UI explains that contents are hidden until separately
requested. Home is a navigation landmark, not a recursive read grant; existing
Home listing restrictions are preserved. Existing configured read roots/grants
retain their normal meaning. No new persistent grant is made by the browser.

Targets: fixed Home/Downloads/Documents aliases and registered project folders,
validated through existing lexical, sensitive-path and no-symlink descriptor
checks. Identity is rechecked after approvals and before commit. Stored/history
targets are untrusted and revalidated. The worker receives sanitized display
strings and bounded approved listing rows, not filesystem descriptors or authority
to browse. It performs no directory traversal, file-content reading, writes,
thumbnail generation or file activation. GTK itself loads trusted system assets;
this is a reviewed application contract, not an OS sandbox against compromised GTK.
The renderer uses a fresh private GTK configuration/cache directory beneath
FRIDAY's data directory, with descriptor handoff and owner-only permissions.
It does not load the owner's personal GTK CSS, user fonts or browser settings.
Fixed local GIO and in-memory settings backends avoid remote location dispatch.
Internal toolkit caches are distinct from browsed files and contain no navigation
history or listing data. These internal directories may remain after exit.

History: at most 16 exact approved locations, cursor bounded, forward history
discarded on a new visit; repeated current location does not append. Revalidate
before back/forward and require fresh typed navigation approval. No background
filesystem scans or monitoring. Commands originate only from deterministic routing;
the helper cannot navigate independently. GUI shows terminal command guidance.

Q: extend existing SQLite row outcome schema without rebuilding/deleting old
history. New managed-browser folder activities have distinct application identity,
stable target keys, validated directory identities and fixed resume descriptors.
Only acknowledged navigation enters Q. Report application-confirmed location,
not compositor-confirmed visibility or completed work. Denials/failures never
refresh Q. Legacy Nautilus entries retain their backend and remain readable.

Compatibility: open files/downloads/documents and explicit project-folder commands
will target FRIDAY Browser; open ubuntu files/open nautilus will keep Nautilus.
Go back/forward belongs to the managed browser while its session history is active;
existing terminal listing navigation otherwise remains unchanged. List downloads
remains the existing filesystem tool. First managed process start counts toward
the shared four-launch limit; reusing its window does not. Closing/reopening counts.

Testing: mock transport and process creation for all GUI tests; exercise history,
closure, approvals, stale identities, Q persistence/resume and launch budget. Test
the actual protocol schema and anonymous socket responses without importing GTK
or opening any window. Required full suite/native build/diff checks precede manual
desktop acceptance. Do not claim live GUI success before owner testing.
