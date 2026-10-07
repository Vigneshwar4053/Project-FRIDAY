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
