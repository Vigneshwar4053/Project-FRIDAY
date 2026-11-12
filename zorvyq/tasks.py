"""Local task records and deterministic intents, independent of chat and knowledge."""
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import os
import re
import sqlite3
import uuid

STATUSES = ('Pending', 'In progress', 'Completed', 'Cancelled')
PRIORITIES = ('Low', 'Normal', 'High')
# Preserve sub-millisecond completion ordering, including legacy timezone offsets.
COMPLETION_ORDER = (
    "CAST(strftime('%s',substr(completed,1,19)||CASE "
    "WHEN substr(completed,-1)='Z' THEN 'Z' "
    "WHEN substr(completed,-6,1) IN ('+','-') THEN substr(completed,-6) ELSE '' END) AS INTEGER) DESC,"
    "CASE WHEN substr(completed,20,1)='.' THEN CAST('0.'||substr(completed,21) AS REAL) ELSE 0 END DESC,id DESC"
)


def now():
    return datetime.now().astimezone()

def timestamp(value):
    if not value:
        return None
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        result = result.astimezone()
    return result.isoformat()

class TaskStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError('Task database symlinks are unsupported.')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL, priority TEXT NOT NULL, created TEXT NOT NULL,
                due TEXT, reminder TEXT, completed TEXT, project TEXT NOT NULL,
                notified TEXT)''')

            db.execute("CREATE INDEX IF NOT EXISTS tasks_completed_precise ON tasks("+COMPLETION_ORDER+") WHERE status='Completed'")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def recent_completed(self, limit=3):
        """Existing Phase 2C records, with chronological ordering across UTC offsets."""
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tasks WHERE status='Completed' AND completed IS NOT NULL "
                "ORDER BY "+COMPLETION_ORDER+" LIMIT ?", (max(1,min(3,int(limit))),))]

    def rows(self, query='', view='All'):
        with closing(self.connect()) as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY created, id')]
        today = now().date()
        def include(row):
            due = datetime.fromisoformat(row['due']).astimezone().date() if row['due'] else None
            active = row['status'] in STATUSES[:2]
            return (query.casefold() in (row['title']+' '+row['description']+' '+row['project']).casefold() and
                    (view == 'All' or row['status'] == view or
                     view == 'Active' and active or
                     view == 'Today' and active and due == today or
                     view == 'Upcoming' and active and due is not None and due > today or
                     view == 'Overdue' and active and due is not None and due < today))
        return [row for row in rows if include(row)]

    def save(self, *, identity=None, title, description='', status='Pending', priority='Normal', due=None, reminder=None, project=''):
        if (not isinstance(title, str) or not title.strip() or len(title) > 500 or
                status not in STATUSES or priority not in PRIORITIES or
                any(not isinstance(x, str) or len(x) > 4000 for x in (description, project))):
            raise ValueError('Invalid task fields.')
        due, reminder = timestamp(due), timestamp(reminder)
        completed = now().isoformat() if status == 'Completed' else None
        with closing(self.connect()) as db, db:
            if identity:
                old = db.execute('SELECT * FROM tasks WHERE id=?', (identity,)).fetchone()
                if old is None:
                    raise ValueError('Task no longer exists.')
                notified = old['notified'] if old['reminder'] == reminder else None
                completed = old['completed'] or completed if status == 'Completed' else None
                db.execute('''UPDATE tasks SET title=?,description=?,status=?,priority=?,due=?,reminder=?,completed=?,project=?,notified=? WHERE id=?''',
                           (title.strip(), description, status, priority, due, reminder, completed, project, notified, identity))
            else:
                identity = uuid.uuid4().hex
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (identity, title.strip(), description, status, priority, now().isoformat(), due, reminder, completed, project, None))
        return identity

    def change_status(self, row, status):
        return self.save(identity=row['id'], **{k: (status if k == 'status' else row[k]) for k in
                         ('title','description','status','priority','due','reminder','project')})

    def delete(self, identity):
        with closing(self.connect()) as db, db:
            if db.execute('DELETE FROM tasks WHERE id=?', (identity,)).rowcount != 1:
                raise ValueError('Task no longer exists.')

    def claim_reminders(self, at=None):
        at = at or now()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            rows = [dict(r) for r in db.execute("SELECT * FROM tasks WHERE reminder IS NOT NULL AND notified IS NULL AND status IN ('Pending','In progress')")
                    if datetime.fromisoformat(r['reminder']) <= at]
            for row in rows:
                db.execute('UPDATE tasks SET notified=? WHERE id=?', (at.isoformat(), row['id']))
        return rows

    def summary(self):
        return (f"{len(self.rows(view='Active'))} pending or in progress · "
                f"{len(self.rows(view='Today'))} due today · {len(self.rows(view='Overdue'))} overdue · "
                f"{sum(bool(r['reminder'] and not r['notified'] and datetime.fromisoformat(r['reminder']) > now()) for r in self.rows(view='Active'))} upcoming reminders")


def intent(text):
    """A deliberately narrow grammar. Return structured data; never execute here."""
    text = re.sub(r'^(?:zorvyq|friday)[, ]+', '', text.strip(), flags=re.I).rstrip('.!?')
    if text.casefold() in ('what tasks do i have', 'show my pending tasks', 'show my tasks', 'list my tasks'):
        return {'action': 'list'}
    match = re.fullmatch(r'add (?:a )?task(?: to)? (.+)', text, re.I)
    if match:
        title = match[1]; due = None
        if title.casefold().endswith(' tomorrow'):
            title = title[:-9]; due = (now()+timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0).isoformat()
        return {'action': 'add', 'title': title, 'due': due}
    match = re.fullmatch(r'mark (?:the )?(.+?)(?: task)? complete', text, re.I)
    if match:
        return {'action': 'complete', 'query': match[1]}
    match = re.fullmatch(r'delete (?:the )?(.+?)(?: task)?', text, re.I)
    if match and ('task' in text.casefold()):
        query = match[1]
        completed = query.casefold().startswith('completed ')
        return {'action': 'delete', 'query': query[10:] if completed else query, 'completed_only': completed}
    return None
