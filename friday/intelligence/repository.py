"""Separate authoritative knowledge SQLite; never opens personal memory."""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import stat
from friday.tools.grants import directory_descriptor, lexical_path
from friday.intelligence.models import (KnowledgeError, KnowledgeSource, SourceRevision,
    KnowledgeChunk, IndexManifest, TrustClassification, MAX_ACTIVE_CHUNKS, digest, fingerprint, utc_now)
from friday.intelligence.ingestion import normalize_text, reject_secrets
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose

APPLICATION_ID=0x46524B31
SCHEMA_VERSION=1
SCHEMA='''
CREATE TABLE sources(source_id TEXT PRIMARY KEY, identifier TEXT NOT NULL UNIQUE,
    current_revision TEXT, state TEXT NOT NULL CHECK(state IN ('active','revoked')));
CREATE TABLE revisions(revision_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
    source_json TEXT NOT NULL, document_revision TEXT, content_sha256 TEXT NOT NULL,
    ingested_at TEXT NOT NULL, text TEXT NOT NULL, chunker_version TEXT NOT NULL);
CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
    revision_id TEXT NOT NULL REFERENCES revisions, ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    start INTEGER NOT NULL CHECK(start>=0), end INTEGER NOT NULL CHECK(end>start),
    content_sha256 TEXT NOT NULL, text TEXT NOT NULL, UNIQUE(revision_id,ordinal));
CREATE INDEX chunks_revision ON chunks(revision_id);
CREATE TABLE manifests(generation_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL);
CREATE TABLE indexed_chunks(generation_id TEXT NOT NULL REFERENCES manifests,
    chunk_id TEXT NOT NULL REFERENCES chunks, content_sha256 TEXT NOT NULL,
    PRIMARY KEY(generation_id,chunk_id));
CREATE TABLE approvals(approval_id INTEGER PRIMARY KEY, purpose TEXT NOT NULL,
    scope_sha256 TEXT NOT NULL, approved_at TEXT NOT NULL);
'''


def scope_ids(scope):
    import re
    if (type(scope) is not tuple or not 1<=len(scope)<=100 or
            any(type(s) is not str or not re.fullmatch(r'src_[0-9a-f]{64}',s) for s in scope) or
            len(set(scope))!=len(scope)):
        raise KnowledgeError('An exact nonempty knowledge scope is required.')
    return tuple(sorted(scope))


@contextmanager
def private_creation():
    previous=os.umask(0o077)
    try:yield
    finally:os.umask(previous)


class KnowledgeRepository:
    """Synchronous, single-owner storage; private parent stays pinned until close.

    SQLite path opening cannot isolate malicious code running under the same UID.
    No default construction or migration of the conversation database occurs.
    """
    def __init__(self,path):
        self._stack=ExitStack();self.connection=None
        path=lexical_path(str(path))
        if not path.is_absolute() or path.name!='knowledge.sqlite3':
            raise KnowledgeError('A separate knowledge.sqlite3 path is required.')
        try:
            parent=self._stack.enter_context(directory_descriptor(path.parent,create=True))
            info=os.fstat(parent)
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
                raise KnowledgeError('Knowledge storage must be private and owner-controlled.')
            self._parent=parent
            try:
                fd=os.open(path.name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
                fresh=True
            except FileExistsError:
                fd=os.open(path.name,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent);fresh=False
            try:
                info=os.fstat(fd);self._identity=(info.st_dev,info.st_ino)
                self._private(info)
                # SQLite can inspect existing WAL/journal files during opening.
                # Reject unsafe sidecars before handing the path to SQLite.
                self._check_files()
                with private_creation():
                    self.connection=sqlite3.connect(f'file:/proc/self/fd/{parent}/knowledge.sqlite3?mode=rw',
                        uri=True,timeout=5)
                    self.connection.row_factory=sqlite3.Row
                    self.connection.execute('PRAGMA foreign_keys=ON')
                    self.connection.execute('PRAGMA trusted_schema=OFF')
                    application=self.connection.execute('PRAGMA application_id').fetchone()[0]
                    version=self.connection.execute('PRAGMA user_version').fetchone()[0]
                    if fresh:
                        self.connection.executescript('BEGIN IMMEDIATE;'+SCHEMA+
                            f'PRAGMA application_id={APPLICATION_ID};PRAGMA user_version={SCHEMA_VERSION};COMMIT;')
                    elif application!=APPLICATION_ID or version!=SCHEMA_VERSION:
                        raise KnowledgeError('Unknown knowledge database identity or schema.')
                self._check_files()
            finally:os.close(fd)
        except (OSError,sqlite3.Error,KnowledgeError):
            self.close()
            raise KnowledgeError('Knowledge storage is unavailable, insecure or incompatible.') from None

    @staticmethod
    def _private(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or
                stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1):
            raise KnowledgeError('Knowledge storage file is not private.')

    def _check_files(self):
        info=os.fstat(self._parent)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise KnowledgeError('Knowledge storage directory changed.')
        for suffix in ('','-journal','-wal','-shm'):
            try:info=os.stat('knowledge.sqlite3'+suffix,dir_fd=self._parent,follow_symlinks=False)
            except FileNotFoundError:
                if suffix:continue
                raise KnowledgeError('Knowledge storage identity changed.') from None
            self._private(info)
            if not suffix and (info.st_dev,info.st_ino)!=self._identity:
                raise KnowledgeError('Knowledge storage identity changed.')

    @contextmanager
    def transaction(self):
        if self.connection is None:raise KnowledgeError('Knowledge repository is closed.')
        try:
            self._check_files()
            with private_creation(),self.connection:
                self.connection.execute('BEGIN IMMEDIATE')
                yield self.connection
                self._check_files()
        except (OSError,sqlite3.Error):
            raise KnowledgeError('Knowledge transaction failed safely.') from None

    def close(self):
        if self.connection is not None:self.connection.close();self.connection=None
        self._stack.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()

    @staticmethod
    def _audit(db,request):
        db.execute('INSERT INTO approvals(purpose,scope_sha256,approved_at) VALUES(?,?,?)',
            (request.purpose.value,request.scope_sha256,utc_now()))

    def ingest(self,source,text,authorization,chunker,*,document_revision=None):
        if type(source) is not KnowledgeSource:raise KnowledgeError('Typed source provenance required.')
        if document_revision is not None:
            from friday.intelligence.models import bounded_text
            bounded_text(document_revision,128);reject_secrets(document_revision)
        text=normalize_text(text)
        source_json=json.dumps(asdict(source),sort_keys=True,separators=(',',':'))
        reject_secrets(source_json)
        revision_id='rev_'+fingerprint([source_json,document_revision,digest(text),chunker.version])
        request=AuthorizationRequest(KnowledgePurpose.RETAIN,(source.source_id,),fingerprint([revision_id,digest(text)]))
        authorization.require(request)
        chunks=chunker.chunks(source.source_id,revision_id,text)
        with self.transaction() as db:
            old=db.execute('SELECT * FROM sources WHERE source_id=?',(source.source_id,)).fetchone()
            if old is not None and old['state']=='revoked':raise KnowledgeError('Source is revoked; reenrollment requires a separate contract.')
            if old is not None and old['current_revision']==revision_id:
                self._audit(db,request)
                return self._revision(db.execute('SELECT * FROM revisions WHERE revision_id=?',(revision_id,)).fetchone())
            active=db.execute("SELECT COUNT(*) FROM chunks c JOIN sources s ON c.revision_id=s.current_revision AND c.source_id=s.source_id WHERE s.state='active' AND s.source_id!=?",
                (source.source_id,)).fetchone()[0]
            if active+len(chunks)>MAX_ACTIVE_CHUNKS:raise KnowledgeError('Knowledge corpus exceeds its chunk limit.')
            db.execute("INSERT INTO sources VALUES(?,?,?,'active') ON CONFLICT(source_id) DO UPDATE SET current_revision=excluded.current_revision",
                (source.source_id,source.identifier,revision_id))
            db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?,?,?,?,?)',
                (revision_id,source.source_id,source_json,document_revision,digest(text),utc_now(),text,chunker.version))
            db.executemany('INSERT OR IGNORE INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                [(c.chunk_id,c.source_id,c.revision_id,c.ordinal,c.start,c.end,c.content_sha256,c.text) for c in chunks])
            self._audit(db,request)
            return self._revision(db.execute('SELECT * FROM revisions WHERE revision_id=?',(revision_id,)).fetchone())

    @staticmethod
    def _revision(row):
        try:
            metadata=json.loads(row['source_json']);metadata['trust']=TrustClassification(metadata['trust']);metadata['topics']=tuple(metadata['topics'])
            source=KnowledgeSource(**metadata)
            if source.source_id!=row['source_id'] or digest(row['text'])!=row['content_sha256']:
                raise KnowledgeError('Source revision integrity failed.')
            if 'rev_'+fingerprint([json.dumps(asdict(source),sort_keys=True,separators=(',',':')),
                    row['document_revision'],row['content_sha256'],row['chunker_version']])!=row['revision_id']:
                raise KnowledgeError('Source provenance integrity failed.')
            return SourceRevision(row['revision_id'],source,row['content_sha256'],row['ingested_at'],row['document_revision'],row['text'])
        except (ValueError,TypeError,KeyError):
            raise KnowledgeError('Source provenance is malformed.') from None

    def snapshot(self,scope):
        scope=scope_ids(scope)
        with self.transaction() as db:
            return tuple(tuple(row) for row in db.execute(
                "SELECT s.source_id,s.current_revision,r.content_sha256 FROM sources s JOIN revisions r ON r.revision_id=s.current_revision AND r.source_id=s.source_id WHERE s.state='active' AND s.source_id IN ("+
                ','.join('?' for _ in scope)+') ORDER BY s.source_id',scope))

    def register_manifest(self,manifest):
        if type(manifest) is not IndexManifest:raise KnowledgeError('Typed index manifest required.')
        with self.transaction() as db:
            self._check_manifest(db,manifest)
            db.execute('INSERT OR IGNORE INTO manifests VALUES(?,?)',(manifest.generation_id,json.dumps(asdict(manifest),sort_keys=True)))

    @staticmethod
    def _check_manifest(db,manifest):
        row=db.execute('SELECT manifest_json FROM manifests WHERE generation_id=?',(manifest.generation_id,)).fetchone()
        if row is not None and row[0]!=json.dumps(asdict(manifest),sort_keys=True):
            raise KnowledgeError('Stored index manifest integrity failed.')
        return row is not None

    def pending_chunks(self,scope,manifest,limit=4):
        scope=scope_ids(scope)
        with self.transaction() as db:
            self._check_manifest(db,manifest)
            rows=db.execute("SELECT c.*,r.chunker_version FROM chunks c JOIN sources s ON c.revision_id=s.current_revision AND c.source_id=s.source_id JOIN revisions r ON r.revision_id=c.revision_id AND r.source_id=s.source_id WHERE s.state='active' AND s.source_id IN ("+
                ','.join('?' for _ in scope)+') AND NOT EXISTS(SELECT 1 FROM indexed_chunks i WHERE i.chunk_id=c.chunk_id AND i.generation_id=?) ORDER BY c.source_id,c.ordinal LIMIT ?',
                (*scope,manifest.generation_id,limit)).fetchall()
            if any(r['chunker_version']!=manifest.chunker_version for r in rows):raise KnowledgeError('Chunker/index manifest mismatch.')
            for row in rows:
                revision=self._revision(db.execute('SELECT * FROM revisions WHERE revision_id=?',(row['revision_id'],)).fetchone())
                if (revision.source.source_id!=row['source_id'] or row['text']!=revision.text[row['start']:row['end']] or
                        digest(row['text'])!=row['content_sha256']):raise KnowledgeError('Chunk integrity failed before embedding.')
            return tuple(KnowledgeChunk(*(r[key] for key in ('chunk_id','source_id','revision_id','ordinal','start','end','content_sha256','text'))) for r in rows)

    def acknowledge(self,chunks,manifest,request):
        with self.transaction() as db:
            if not self._check_manifest(db,manifest):raise KnowledgeError('Index generation is not registered.')
            for chunk in chunks:
                row=db.execute("SELECT current_revision FROM sources WHERE source_id=? AND state='active'",(chunk.source_id,)).fetchone()
                if row is None or row[0]!=chunk.revision_id:raise KnowledgeError('Source changed during indexing.')
                db.execute('INSERT OR REPLACE INTO indexed_chunks VALUES(?,?,?)',(manifest.generation_id,chunk.chunk_id,chunk.content_sha256))
            self._audit(db,request)

    def evidence(self,chunk_id,scope,manifest):
        scope=scope_ids(scope)
        with self.transaction() as db:
            if not self._check_manifest(db,manifest):return None
            row=db.execute("SELECT c.* FROM chunks c JOIN sources s ON c.revision_id=s.current_revision AND c.source_id=s.source_id JOIN indexed_chunks i ON i.chunk_id=c.chunk_id AND i.content_sha256=c.content_sha256 WHERE c.chunk_id=? AND i.generation_id=? AND s.state='active' AND s.source_id IN ("+
                ','.join('?' for _ in scope)+')',(chunk_id,manifest.generation_id,*scope)).fetchone()
            if row is None:return None
            revision=self._revision(db.execute('SELECT * FROM revisions WHERE revision_id=?',(row['revision_id'],)).fetchone())
            chunk=KnowledgeChunk(*(row[key] for key in ('chunk_id','source_id','revision_id','ordinal','start','end','content_sha256','text')))
            if (chunk.text!=revision.text[chunk.start:chunk.end] or digest(chunk.text)!=chunk.content_sha256 or
                    chunk.source_id!=revision.source.source_id):raise KnowledgeError('Chunk integrity failed.')
            return chunk,revision

    def has_indexed(self,scope,manifest):
        scope=scope_ids(scope)
        with self.transaction() as db:
            if not self._check_manifest(db,manifest):return False
            return db.execute("SELECT 1 FROM indexed_chunks i JOIN chunks c ON c.chunk_id=i.chunk_id JOIN sources s ON c.revision_id=s.current_revision AND c.source_id=s.source_id WHERE i.generation_id=? AND s.state='active' AND s.source_id IN ("+
                ','.join('?' for _ in scope)+') LIMIT 1',(manifest.generation_id,*scope)).fetchone() is not None

    def revoke(self,source_id,authorization):
        scope=scope_ids((source_id,));snapshot=self.snapshot(scope)
        request=AuthorizationRequest(KnowledgePurpose.REVOKE,scope,fingerprint(snapshot))
        authorization.require(request)
        with self.transaction() as db:
            current=db.execute('SELECT current_revision FROM sources WHERE source_id=?',(source_id,)).fetchone()
            if snapshot and (current is None or current[0]!=snapshot[0][1]):raise KnowledgeError('Source changed during revocation approval.')
            db.execute("UPDATE sources SET state='revoked' WHERE source_id=?",(source_id,))
            db.execute('DELETE FROM indexed_chunks WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE source_id=?)',(source_id,))
            self._audit(db,request)
