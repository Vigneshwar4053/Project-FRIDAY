"""Small persistence API; SQL stays outside conversation flow."""
from datetime import datetime, timezone
from pathlib import Path

from friday.memory.database import Database, MemoryStorageError
from friday.memory.models import Memory, Message, Session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _validate_message(role: str, content: str) -> None:
    if role not in {'user', 'assistant'}:
        raise ValueError('Only user and final assistant messages can be saved.')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('A message cannot be blank.')


class MemoryManager:
    def __init__(self, database_path: str | Path):
        self._database = Database(database_path)

    def __enter__(self) -> 'MemoryManager':
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._database.close()

    def start_session(self) -> Session:
        started_at = _now()
        with self._database.transaction() as db:
            cursor = db.execute('INSERT INTO sessions(started_at) VALUES (?)', (started_at,))
            session_id = cursor.lastrowid
        return Session(session_id, started_at, None)

    def end_session(self, session_id: int) -> None:
        # Idempotent: preserve the first recorded end time.
        with self._database.transaction() as db:
            cursor = db.execute(
                'UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?',
                (_now(), session_id),
            )
            if cursor.rowcount != 1:
                raise MemoryStorageError('The memory session does not exist.')

    def get_most_recent_session(self) -> Session | None:
        with self._database.transaction() as db:
            row = db.execute('SELECT * FROM sessions ORDER BY id DESC LIMIT 1').fetchone()
        return Session(**dict(row)) if row else None

    def save_message(self, session_id: int, role: str, content: str) -> Message:
        """Save an explicit message; callers must supply final, sanitized assistant text."""
        _validate_message(role, content)
        created_at = _now()
        with self._database.transaction() as db:
            self._require_active_session(db, session_id)
            cursor = db.execute(
                'INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)',
                (session_id, role, content, created_at),
            )
            message_id = cursor.lastrowid
        return Message(message_id, session_id, role, content, created_at)

    def save_turn(self, session_id: int, user_content: str, assistant_content: str) -> None:
        """Commit a successful turn as one transaction, never a partial pair."""
        _validate_message('user', user_content)
        _validate_message('assistant', assistant_content)
        with self._database.transaction() as db:
            self._require_active_session(db, session_id)
            db.executemany(
                'INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)',
                [(session_id, 'user', user_content, _now()),
                 (session_id, 'assistant', assistant_content, _now())],
            )

    @staticmethod
    def _require_active_session(db, session_id: int) -> None:
        row = db.execute('SELECT ended_at FROM sessions WHERE id = ?', (session_id,)).fetchone()
        if row is None or row['ended_at'] is not None:
            raise MemoryStorageError('Messages require an existing, active session.')

    def get_recent_messages(self, limit: int, session_id: int | None = None) -> list[Message]:
        """Newest N messages returned in chronological insertion order.

        With no session_id, search across sessions so an empty intervening
        session does not erase useful context. Zero disables retrieval.
        """
        if not isinstance(limit, int) or limit < 0:
            raise ValueError('The recent message limit must be a nonnegative integer.')
        with self._database.transaction() as db:
            if session_id is None:
                rows = db.execute('SELECT * FROM messages ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            else:
                rows = db.execute(
                    'SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?',
                    (session_id, limit),
                ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def store_memory(self, category: str, key: str, value: str, importance: int = 0) -> Memory:
        """Upsert a key within a category, retaining its id and creation time."""
        if not category.strip() or not key.strip() or not isinstance(value, str):
            raise ValueError('Memory needs a category, key, and string value.')
        if not isinstance(importance, int) or not 0 <= importance <= 10:
            raise ValueError('Importance must be an integer between 0 and 10.')
        now = _now()
        with self._database.transaction() as db:
            db.execute(
                'INSERT INTO memories(category, key, value, importance, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(category, key) DO UPDATE SET '
                'value = excluded.value, importance = excluded.importance, updated_at = excluded.updated_at',
                (category, key, value, importance, now, now),
            )
            row = db.execute('SELECT * FROM memories WHERE category = ? AND key = ?',
                             (category, key)).fetchone()
        return Memory(**dict(row))

    def get_memory(self, category: str, key: str) -> Memory | None:
        with self._database.transaction() as db:
            row = db.execute('SELECT * FROM memories WHERE category = ? AND key = ?',
                             (category, key)).fetchone()
        return Memory(**dict(row)) if row else None
