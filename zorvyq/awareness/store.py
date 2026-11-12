"""Dedicated, versioned owner-only activity storage. No task or RAG contents."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3

DEFAULTS = dict(enabled=False, paused=False, browser=False, titles=False, urls=False,
                metrics=False, retention=30, metrics_retention=7, since=None,
                applications=['code', 'firefox', 'gnome-terminal', 'org.gnome.Nautilus'],
                domains=[], exclusions=[], strict_local_only=True,
                processes=False, network=False, managed_runtime=False,
                start_at_login=False, background=False)
EMPTY = 'No recent activity recorded. Enable activity monitoring to start building your local history.'

def utc(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return dt.astimezone(timezone.utc)

def stamp(value):
    return utc(value).isoformat(timespec='microseconds')

def now():
    return datetime.now(timezone.utc)

class ActivityStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise PermissionError('Activity database must belong to the owner')
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 5:
                raise ValueError('Unsupported activity schema')
            if version < 1:
                db.execute('''CREATE TABLE activities (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, app TEXT NOT NULL, name TEXT NOT NULL,
                    start TEXT NOT NULL, end TEXT NOT NULL, duration REAL NOT NULL CHECK(duration>0),
                    category TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', domain TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL CHECK(state IN ('completed','interrupted','unknown')))''')
                db.execute('CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
                db.execute('INSERT INTO preferences VALUES (1,?)', (json.dumps(DEFAULTS),))
                db.execute('CREATE TABLE deleted_events (id TEXT PRIMARY KEY, deleted TEXT NOT NULL)')
                db.execute('CREATE INDEX activity_end ON activities(end DESC,id DESC)')
                db.execute('CREATE INDEX activity_start ON activities(start)')
                db.execute('CREATE INDEX activity_app ON activities(app,end DESC)')
                db.execute('CREATE INDEX activity_category ON activities(category,end DESC)')
                db.execute('PRAGMA user_version=1')
            if version < 2:
                db.execute('CREATE TABLE system_metrics (at TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute('CREATE TABLE monitoring_events (at TEXT NOT NULL, state TEXT NOT NULL)')
                db.execute('PRAGMA user_version=2')
            if version < 3:
                db.execute("ALTER TABLE activities ADD COLUMN source TEXT NOT NULL DEFAULT ''")
                db.execute('CREATE INDEX activity_source ON activities(source)')
                db.execute('PRAGMA user_version=3')
            if version < 4:
                db.execute('CREATE TABLE IF NOT EXISTS website_categories (domain TEXT PRIMARY KEY, category TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS activity_sessions (id TEXT PRIMARY KEY, start TEXT NOT NULL, end TEXT, state TEXT NOT NULL)')
                # Named views preserve the single canonical timeline rather than duplicate records.
                db.execute("CREATE VIEW IF NOT EXISTS applications AS SELECT DISTINCT app, name FROM activities WHERE kind='application'")
                db.execute("CREATE VIEW IF NOT EXISTS window_activity AS SELECT * FROM activities WHERE kind='application'")
                db.execute("CREATE VIEW IF NOT EXISTS browser_activity AS SELECT * FROM activities WHERE kind='browser'")
                db.execute('PRAGMA user_version=4')
            if version < 5:
                db.execute('CREATE TABLE IF NOT EXISTS monitoring_status (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
                db.execute('PRAGMA user_version=5')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Activity database integrity check failed')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.execute('PRAGMA secure_delete=ON')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def preferences(self):
        with self.db() as db:
            return {**DEFAULTS, **json.loads(db.execute('SELECT value FROM preferences WHERE id=1').fetchone()[0])}

    def configure(self, *, consent=False, **changes):
        p = self.preferences()
        if set(changes)-set(DEFAULTS):
            raise ValueError('Unknown preference')
        for k,v in changes.items():
            if k in ('enabled','paused','browser','titles','urls','metrics','processes','network','strict_local_only','managed_runtime','start_at_login','background') and type(v) is not bool:
                raise ValueError('Invalid switch')
            if k in ('retention','metrics_retention') and (type(v) is not int or not 1 <= v <= 3650):
                raise ValueError('Invalid retention')
            if k in ('applications','domains','exclusions') and (type(v) is not list or len(v)>100 or any(type(s) is not str or not s or len(s)>256 for s in v)):
                raise ValueError('Invalid allowlist or exclusion')
        if changes.get('strict_local_only',True) is not True:
            raise ValueError('Activity processing must remain strictly local')
        if any(changes.get(k) and not p[k] for k in ('enabled','browser','titles','urls','metrics','processes','network','managed_runtime','start_at_login','background')) and not consent:
            raise PermissionError('Explicit owner consent required')
        if 'since' in changes:
            raise ValueError('Collection boundary is managed internally')
        p.update(changes)
        # Every privacy change establishes a fresh boundary; never import old AW history.
        p['since'] = stamp(now())
        with self.db() as db:
            db.execute('DELETE FROM monitoring_status')
            db.execute('UPDATE preferences SET value=? WHERE id=1', (json.dumps(p),))
            if not p['titles']: db.execute("UPDATE activities SET title='' ")
            if not p['urls']: db.execute("UPDATE activities SET url='' ")
            if not p['processes'] or not p['network']:
                for row in db.execute('SELECT at,value FROM system_metrics').fetchall():
                    value=json.loads(row['value'])
                    if not p['processes']:value.pop('processes',None)
                    if not p['network']:value.pop('network',None)
                    db.execute('UPDATE system_metrics SET value=? WHERE at=?',(json.dumps(value),row['at']))
            db.execute('INSERT INTO monitoring_events VALUES (?,?)', (stamp(now()), 'preferences_changed'))
        return p

    def insert(self, record, _db=None):
        # Internal normalized ingestion only; enforce consent again at write boundary.
        p = self.preferences()
        if not p['enabled'] or p['paused'] or record['app'] not in p['applications']:
            return False
        if record['kind']=='browser' and not p['browser']:
            return False
        r = dict(record)
        r['start'], r['end'] = stamp(r['start']), stamp(r['end'])
        if utc(r['start']) < utc(p['since']) or utc(r['end']) <= utc(r['start']): return False
        r['duration'] = (utc(r['end'])-utc(r['start'])).total_seconds()
        if not p['titles']: r['title']=''
        if not p['urls']: r['url']=''
        columns = ('id','kind','app','name','start','end','duration','category','title','domain','url','project','state','source')
        with (nullcontext(_db) if _db is not None else self.db()) as db:
            if _db is None:db.execute('BEGIN IMMEDIATE')
            current={**DEFAULTS, **json.loads(db.execute('SELECT value FROM preferences WHERE id=1').fetchone()[0])}
            if current!=p:return False
            if db.execute('SELECT 1 FROM deleted_events WHERE id=?',(r['id'],)).fetchone():return False
            return bool(db.execute('INSERT INTO activities ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+") ON CONFLICT(id) DO UPDATE SET state=excluded.state,end=excluded.end,duration=excluded.duration WHERE activities.state!=excluded.state OR activities.end!=excluded.end", tuple(r.get(k,'') for k in columns)).rowcount)

    def reconcile(self, source, records):
        """Reconcile corrected idle boundaries without duplicating a source event."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            p={**DEFAULTS, **json.loads(db.execute('SELECT value FROM preferences WHERE id=1').fetchone()[0])}
            if not p['enabled'] or p['paused']:return 0
            if db.execute('SELECT 1 FROM deleted_events WHERE id=?',(source,)).fetchone():return 0
            prior={r[0] for r in db.execute('SELECT id FROM activities WHERE source=?',(source,))}
            wanted={r['id'] for r in records}
            removed=prior-wanted
            db.executemany('DELETE FROM activities WHERE id=?',((x,) for x in removed))
            return len(removed)+sum(self.insert(dict(r,source=source),_db=db) for r in records)

    def search(self, query='', app='', category='', start=None, end=None, limit=200, completed=False, kind=''):
        clauses=[]; args=[]
        for key,value in (('app',app),('category',category),('kind',kind)):
            if value: clauses.append(key+'=?');args.append(value)
        if query:
            clauses.append("instr(lower(name||' '||title||' '||domain||' '||project),lower(?))>0");args.append(query[:500])
        if start: clauses.append('end>?');args.append(stamp(start))
        if end: clauses.append('start<?');args.append(stamp(end))
        if completed: clauses.append("state='completed'")
        with self.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM activities'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY end DESC,id DESC LIMIT ?',(*args,max(1,min(1000,int(limit)))))]
        p=self.preferences()
        for r in rows:
            if not p['titles']: r['title']=''
            if not p['urls']: r['url']=''
        return rows

    def last_three(self):
        # Browser records are details of Firefox use, not a second overlapping computer activity.
        return self.search(limit=3,completed=True,kind='application')

    def associate(self, identity, project, projects, category=None):
        path=str(projects.validate(project)) if project else ''
        if category not in (None,'Programming','Browsing','Terminal','Files','Studying','Other'):
            raise ValueError('Unknown category')
        with self.db() as db:
            if category:
                db.execute('UPDATE activities SET project=?,category=? WHERE id=?',(path,category,identity))
            else:db.execute('UPDATE activities SET project=? WHERE id=?',(path,identity))

    def delete(self, identities=None):
        with self.db() as db:
            rows = db.execute('SELECT id FROM activities').fetchall() if identities is None else [(x,) for x in identities[:1000]]
            for row in rows:
                source=db.execute('SELECT source FROM activities WHERE id=?',(row[0],)).fetchone()
                if source and source[0]:db.execute('INSERT OR IGNORE INTO deleted_events VALUES (?,?)',(source[0],stamp(now())))
            db.executemany('INSERT OR IGNORE INTO deleted_events VALUES (?,?)',((r[0],stamp(now())) for r in rows))
            db.executemany('DELETE FROM activities WHERE id=?',((r[0],) for r in rows))
            if identities is None:
                db.execute('DELETE FROM system_metrics'); db.execute('DELETE FROM monitoring_events')
                db.execute('DELETE FROM activity_sessions')
                db.execute('DELETE FROM monitoring_status')

    def cleanup(self, at=None):
        at=at or now();p=self.preferences()
        with self.db() as db:
            db.execute('DELETE FROM activities WHERE end<?',(stamp(at-timedelta(days=p['retention'])),))
            db.execute('DELETE FROM system_metrics WHERE at<?',(stamp(at-timedelta(days=p['metrics_retention'])),))
            db.execute('DELETE FROM monitoring_events WHERE at<?',(stamp(at-timedelta(days=p['retention'])),))
            db.execute('DELETE FROM deleted_events WHERE deleted<?',(stamp(at-timedelta(days=p['retention'])),))
            db.execute('DELETE FROM activity_sessions WHERE coalesce(end,start)<?',(stamp(at-timedelta(days=p['retention'])),))

    def set_website_category(self, domain, category):
        from .privacy import normalize_domain, safe_title, WEBSITE_CATEGORIES
        domain=normalize_domain(domain)
        if not isinstance(category,str) or not category.strip() or len(category)>60 or safe_title(category)!=category:
            raise ValueError('Invalid category')
        with self.db() as db:
            db.execute('INSERT INTO website_categories VALUES (?,?) ON CONFLICT(domain) DO UPDATE SET category=excluded.category',(domain,category))
            rules={**WEBSITE_CATEGORIES, **dict(db.execute('SELECT domain,category FROM website_categories'))}
            # More specific rules always win, including after editing a parent rule.
            for row in db.execute("SELECT DISTINCT domain FROM activities WHERE kind='browser'").fetchall():
                matches=[d for d in rules if row[0]==d or row[0].endswith('.'+d)]
                value=rules[max(matches,key=len)] if matches else 'Other'
                db.execute("UPDATE activities SET category=? WHERE kind='browser' AND domain=?",(value,row[0]))

    def website_category(self, domain):
        from .privacy import WEBSITE_CATEGORIES
        with self.db() as db:
            rules={**WEBSITE_CATEGORIES, **dict(db.execute('SELECT domain,category FROM website_categories'))}
        matches=[d for d in rules if domain==d or domain.endswith('.'+d)]
        return rules[max(matches,key=len)] if matches else 'Other'

    def export(self, path, rows):
        # Explicit selection, bounded, restrictive file; never upload or overwrite.
        ids={r['id'] for r in rows}
        selected=[r for r in self.search(limit=1000) if r['id'] in ids]
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(selected,stream,indent=2)

    def totals(self, start, end, *, category='', browser=False):
        # Clamp intervals at query boundaries. Application and browser totals stay separate.
        clauses=["kind=?", "state='completed'", 'end>?','start<?'];args=['browser' if browser else 'application',stamp(start),stamp(end)]
        if category:clauses.append('category=?');args.append(category)
        with self.db() as db:
            rows=db.execute("SELECT name, count(*) AS count, sum((julianday(min(end,?))-julianday(max(start,?)))*86400) AS seconds FROM activities WHERE "+' AND '.join(clauses)+' GROUP BY name ORDER BY seconds DESC,name LIMIT 100',(stamp(end),stamp(start),*args)).fetchall()
        return [dict(r) for r in rows]
