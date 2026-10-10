"""SQLite lifecycle and schema; no model or terminal dependencies."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from collections.abc import Iterator


class MemoryStorageError(RuntimeError):
    """An expected local memory failure safe to display without conversation text."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 0 CHECK (importance BETWEEN 0 AND 10),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, key)
);
CREATE TABLE IF NOT EXISTS desktop_project_sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    trusted_project_path TEXT NOT NULL,
    application_id TEXT NOT NULL CHECK(application_id = 'vscode'),
    device INTEGER NOT NULL CHECK(device >= 0),
    inode INTEGER NOT NULL CHECK(inode >= 0),
    opened_at TEXT NOT NULL,
    last_friday_interaction_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('launch_accepted', 'launch_outcome_unverified')),
    source TEXT NOT NULL CHECK(source = 'friday_managed'),
    schema_version INTEGER NOT NULL CHECK(schema_version = 1)
);
CREATE INDEX IF NOT EXISTS desktop_project_opened ON desktop_project_sessions(opened_at);
CREATE TABLE IF NOT EXISTS recent_work (
    entry_id TEXT PRIMARY KEY,
    activity_key TEXT NOT NULL UNIQUE,
    activity_type TEXT NOT NULL,
    application_id TEXT NOT NULL,
    target_identity TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    resume_descriptor TEXT NOT NULL,
    launched_at TEXT NOT NULL,
    safe_link TEXT NOT NULL,
    launch_order INTEGER NOT NULL,
    launch_status TEXT NOT NULL DEFAULT 'launch_accepted'
        CHECK(launch_status IN ('launch_accepted', 'launch_outcome_unverified', 'navigation_confirmed'))
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.connection: sqlite3.Connection | None = None
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.connection.executescript(_SCHEMA)
            # Existing Phase 7A rows came exclusively from zero-exit accepted
            # launches. Preserve their IDs/order and mark that known outcome.
            with self.connection:
                # Explicitly start before DDL: sqlite3's implicit transaction
                # handling starts at DML, too late for an atomic table rebuild.
                self.connection.execute('BEGIN IMMEDIATE')
                columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(recent_work)')}
                if 'launch_status' not in columns:
                    self.connection.execute("ALTER TABLE recent_work ADD COLUMN launch_status TEXT NOT NULL "
                                            "DEFAULT 'launch_accepted' CHECK(launch_status IN "
                                            "('launch_accepted', 'launch_outcome_unverified'))")
                table_sql=self.connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='recent_work'").fetchone()[0]
                if "'navigation_confirmed'" not in table_sql:
                    # SQLite cannot ALTER a CHECK constraint. Rebuild only this
                    # known application-owned table atomically, preserving IDs
                    # and every old field. Refuse unexpected custom objects.
                    if self.connection.execute("SELECT 1 FROM sqlite_master WHERE tbl_name='recent_work' AND type IN ('trigger','index') AND sql IS NOT NULL").fetchone():
                        raise sqlite3.DatabaseError('Unexpected recent-work schema objects.')
                    self.connection.execute('ALTER TABLE recent_work RENAME TO recent_work_before_browser')
                    self.connection.execute(_SCHEMA[_SCHEMA.index('CREATE TABLE IF NOT EXISTS recent_work'):].strip())
                    self.connection.execute('INSERT INTO recent_work SELECT * FROM recent_work_before_browser')
                    self.connection.execute('DROP TABLE recent_work_before_browser')
        except (OSError, sqlite3.Error) as exc:
            self.close()
            raise MemoryStorageError('Could not open or initialize the local memory database.') from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection is None:
            raise MemoryStorageError('The local memory database is closed.')
        try:
            with self.connection:
                yield self.connection
        except sqlite3.Error as exc:
            raise MemoryStorageError('Local memory operation failed; the transaction was rolled back.') from exc

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
