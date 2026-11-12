# ZORVYQ Phase 2A migration inventory

## Protected starting checkpoint

Branch: `feature/voice-foundation`. The initial working tree contained 11 modified
tracked files and 15 untracked files from Phase 1F/1G. Before implementation,
all 26 files were archived with SHA-256 hashes under the ignored local directory
`data/migration/phase2a/`; a binary Git diff is stored beside the archive.
No reset, clean, restore, history rewrite, environment recreation, or data move
is part of this checkpoint. `.env` must remain unopened and unchanged.

Current read-only SQLite inspection found 20 active source records, 20 revisions,
312 chunks and 312 indexed-chunk records. Those counts are observations, not UI
constants. ChromaDB is absent from this checkout's Python 3.14 environment; vector
search cannot be certified live here. The existing venv is preserved.

## Dependency and compatibility map

| Area | Phase 2A treatment |
| --- | --- |
| Public package and startup | Add `zorvyq`, GUI by default; explicit developer CLI |
| Existing Python imports and test imports | Retain `friday.*` implementation; new facade delegates to it |
| Native ABI | Keep `friday_semaphore_*`, `libfriday_sync.so`, C sources and loader paths |
| Conversation SQLite | Keep `data/friday.db`; GUI uses session memory only |
| Knowledge SQLite/Chroma | Keep all paths, schema IDs, manifests, collection names and records |
| Source provenance and approval fingerprints | Keep original identities; GUI approval uses existing exact request |
| Owner credentials | Keep legacy keys and file; Existing authenticator retained; no startup/inventory credential read; hidden dialog only on explicit protected operation |
| Voice settings | Keep XDG `friday/voice.json` and dependency paths; no automatic microphone or speech |
| Browser protocol and saved application IDs | Keep legacy wire markers and `friday_browser` identity |
| Existing scripts | Keep module paths and historical corpus validation artifacts |
| Reports and engineering history | Preserve historical product names and original evidence |
| User-facing identity | ZORVYQ in new GUI, public entry points, current documentation and settings |
| Git and remote | Keep branch/history and current remote until separately approved remote rename |
| Local directory | Keep current root until separately reviewed move; do not copy models/data |

A mass module rename would break native loading, absolute imports, owner settings,
recorded tool identities and reviewed corpus artifacts. The public facade is the
first reversible stage. Removing it restores legacy entry points without a data
migration.

## Desktop framework decision

Use PySide6 Qt Widgets with a single serialized service worker and GUI-thread
approval dialogs. Qt provides native desktop windows, keyboard accessibility,
layout management and local Markdown rendering without a browser engine. Qt 6.10
supports Python 3.14: https://doc.qt.io/qtforpython-6.10/release_notes/pyside6_release_notes.html
Packaging guidance: https://doc.qt.io/qtforpython-6.11/gettingstarted.html
Electron adds a browser runtime; GTK bindings are absent in this venv. No large
dependency may be installed until the owner approves. No specialist routing is
introduced.

## GitHub preflight and exact proposed operation

Observed origin: `https://github.com/Vigneshwar4053/Project-FRIDAY.git`.
The GitHub CLI is unavailable in this environment. Authenticated permissions and
whether the target exists must be verified through an authorized GitHub session.
No repository rename is authorized by the implementation request.

Proposed separate operation, only after explicit approval and successful preflight:
`PATCH /repos/Vigneshwar4053/Project-FRIDAY` with JSON `{"name":"ZORVYQ"}`.
Then verify owner/name, branches and commit IDs, update origin to
`https://github.com/Vigneshwar4053/ZORVYQ.git`, verify connectivity and update links.
Never create a duplicate repository or force push. The remote stays unchanged here.

## Directory move checkpoint

Do not move this active checkout. First stop assistant processes; record DB and
vector fingerprints, absolute references and venv interpreter paths; review a move
from `~/Projects/FRIDAY` to `~/Projects/ZORVYQ` separately with the owner. Reinstall
launchers, repair venv script shebangs if necessary, and verify native sync, imports,
regression tests, read-only inventory and authorized retrieval before retirement of
the legacy path. Do not duplicate multi-gigabyte models or remove the old directory.

## Additional requirements checkpoint — 2026-10-31

The active environment now places this checkout at
`/home/vigneshwar/Projects/zorvyq`; the historical FRIDAY directory is absent.
This extension performed no move. The installed wrapper still needs an approved
path repair, and the exact legacy login entry was identified read-only.
The [additional requirements report](ZORVYQ_PHASE2A_ADDITIONAL_REPORT.md) supersedes
older current-state statements about the checkout path, session-only preferences,
recent-work GUI and specialist integration. Historical evidence above is retained.

Answer-length/voice preferences now persist locally; the desktop reuses the existing
recent-work SQLite store. Manual experimental specialist questions and a bounded,
explicitly authorized Nmap adapter have been added. Automatic routing and specialist
RAG remain blocked. No startup replacement or package installation was performed.
Full current regression: 1,780 passing tests; owner device/login/model acceptance
remains separate. See the five feature guides linked from the additional report.

## Phase 2B extension

The [Phase 2B report](ZORVYQ_PHASE2B_REPORT.md) records the incremental dual-model
composer controls, repaired cybersecurity mode/error UI, reviewed operation framework,
read-only diagnostic adapters and conservative model cleanup on exit. The environment,
knowledge, native synchronization and existing startup approval gates remain intact.
