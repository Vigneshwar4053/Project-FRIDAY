"""Small persistence API; SQL stays outside conversation flow."""
from datetime import datetime, timezone
from pathlib import Path
import json

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

    def record_project_interaction(self, project_id, path, identity, application_id, status, *, opened_at=None):
        """Explicit managed launch metadata only; no prompts/transcripts/content."""
        import re
        from uuid import uuid4
        from friday.tools.grants import lexical_path
        if (type(project_id) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',project_id) or
                application_id!='vscode' or status not in {'launch_accepted','launch_outcome_unverified'} or
                type(identity) is not tuple or len(identity)!=2 or
                any(type(value) is not int or value<0 for value in identity)):
            raise ValueError('Invalid desktop session metadata.')
        if not lexical_path(path).is_absolute() or any(ord(c)<32 or ord(c)==127 for c in path):
            raise ValueError('Invalid desktop session target.')
        stamp=opened_at or _now()
        parsed=datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:
            raise ValueError('UTC timestamp required.')
        stamp=parsed.isoformat(timespec='microseconds')
        with self._database.transaction() as db:
            db.execute('INSERT INTO desktop_project_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (str(uuid4()),project_id,path,application_id,*identity,stamp,stamp,status,'friday_managed',1))

    def project_interactions_between(self, start, end):
        with self._database.transaction() as db:
            rows=db.execute('SELECT * FROM desktop_project_sessions WHERE opened_at >= ? AND opened_at < ? '
                            'ORDER BY opened_at,session_id LIMIT 129',(start,end)).fetchall()
        if len(rows)>128:
            raise ValueError('Desktop session lookup exceeds the bounded history window.')
        return tuple(dict(row) for row in rows)

    def record_recent_work(self, activity, *, launched_at=None,equivalent_ids=(),duplicate_groups=()):
        """Atomically upsert and trim runtime-verified accepted launches to three."""
        from uuid import uuid4
        if activity['launch_status'] not in {'launch_accepted', 'launch_outcome_unverified','navigation_confirmed'}:
            raise ValueError('Invalid recent-work launch outcome.')
        stamp = launched_at or _now()
        with self._database.transaction() as db:
            # Normalize existing alias duplicates BEFORE trimming, so a duplicate
            # cannot evict the third distinct activity. Archive original rows.
            for group in duplicate_groups:
                rows=db.execute('SELECT * FROM recent_work ORDER BY launch_order DESC').fetchall()
                matching=[dict(row) for row in rows if row['entry_id'] in group]
                if len(matching)>1:
                    db.execute('CREATE TABLE IF NOT EXISTS recent_work_legacy_archive (entry_id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')
                    for row in matching[1:]:
                        db.execute('INSERT OR IGNORE INTO recent_work_legacy_archive VALUES (?,?)',(row['entry_id'],json.dumps(row,sort_keys=True)))
                        db.execute('DELETE FROM recent_work WHERE entry_id=?',(row['entry_id'],))
            if equivalent_ids:
                # Preserve old metadata before normalizing a historical alias.
                # Only validated runtime queue records supply these stable IDs.
                rows=db.execute('SELECT * FROM recent_work ORDER BY launch_order DESC').fetchall()
                matching=[dict(row) for row in rows if row['entry_id'] in equivalent_ids]
                if matching:
                    survivor=matching[0]['entry_id']
                    changed=[row for row in matching if row['activity_key']!=activity['activity_key'] or row['entry_id']!=survivor]
                    if changed:
                        db.execute('CREATE TABLE IF NOT EXISTS recent_work_legacy_archive (entry_id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')
                        for row in changed:
                            db.execute('INSERT OR IGNORE INTO recent_work_legacy_archive VALUES (?,?)',(row['entry_id'],json.dumps(row,sort_keys=True)))
                        for row in matching[1:]: db.execute('DELETE FROM recent_work WHERE entry_id=?',(row['entry_id'],))
                        db.execute('UPDATE recent_work SET activity_key=? WHERE entry_id=?',(activity['activity_key'],survivor))
            order = db.execute('SELECT COALESCE(MAX(launch_order), 0) + 1 FROM recent_work').fetchone()[0]
            db.execute('INSERT INTO recent_work '
                       '(entry_id,activity_key,activity_type,application_id,target_identity,title,summary,'
                       'resume_descriptor,launched_at,safe_link,launch_order,launch_status) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(activity_key) DO UPDATE SET '
                       'activity_type=excluded.activity_type, application_id=excluded.application_id, target_identity=excluded.target_identity, title=excluded.title, '
                       'summary=excluded.summary, resume_descriptor=excluded.resume_descriptor, '
                       'launched_at=excluded.launched_at, safe_link=excluded.safe_link, '
                       'launch_order=excluded.launch_order, launch_status=excluded.launch_status',
                       (str(uuid4()), activity['activity_key'], activity['activity_type'],
                        activity['application_id'], activity['target_identity'], activity['title'],
                        activity['summary'], activity['resume_descriptor'], stamp,
                        activity['safe_link'], order, activity['launch_status']))
            db.execute('DELETE FROM recent_work WHERE entry_id NOT IN '
                       '(SELECT entry_id FROM recent_work ORDER BY launch_order DESC LIMIT 3)')

    def recent_work(self):
        with self._database.transaction() as db:
            rows = db.execute('SELECT * FROM recent_work ORDER BY launch_order DESC LIMIT 3').fetchall()
        return tuple(dict(row) for row in rows)
