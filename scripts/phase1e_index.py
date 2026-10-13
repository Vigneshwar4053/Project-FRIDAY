"""Explicit owner-approved real corpus experiment; never live FRIDAY routing.

Resume by rerunning this module: exact corpus/files/backend identity is checked
again and SQLite pending acknowledgments drive deterministic vector upserts.
Resource thresholds are monitored soft admission limits, not hard ceilings.
"""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import statistics
from threading import Event
from time import monotonic
from unittest.mock import Mock, patch

from friday.intelligence.chunking import TextChunker
from friday.intelligence.chroma_index import ChromaVectorIndex, _private_tree
from friday.intelligence.index import IndexingService, VectorCandidate
from friday.intelligence.ingestion import normalize_text, read_text_file
from friday.intelligence.models import KnowledgeError, KnowledgeSource, IndexManifest, TrustClassification, digest, fingerprint
from friday.intelligence.permissions import AuthorizationRequest, KnowledgeAuthorization, KnowledgeDecision, KnowledgePurpose
from friday.intelligence.repository import KnowledgeRepository, scope_ids
from friday.intelligence.retrieval import RetrievalService
from friday.sync import create_synchronization
from friday.tools.grants import directory_descriptor
from scripts import phase1d_dataset as dataset
from scripts.phase1e_index_preflight import APPROVED, QWEN, verify_packages, verify_models
from scripts.phase1e_monitored import Monitor, admit_monitored
from scripts.phase1e_admission import AdmissionDenied, available_ram, GIB
import shutil


def require(condition):
    if not condition:raise KnowledgeError('Exact approved corpus/index integrity failed.')


def revalidate():
    """Only approved document content is read; excluded files remain unopened."""
    artifact=json.loads((dataset.ROOT/'docs/FRIDAY_PHASE1E_CORPUS.json').read_text())
    scope=artifact['approval_scope']
    require(fingerprint(scope)==artifact['approval_sha256']==APPROVED)
    manifest_bytes=dataset.read_file(dataset.DATASET,'manifest.json')
    require(dataset.sha(manifest_bytes)==scope['manifest_sha256'])
    manifest=json.loads(manifest_bytes);entries={d['id']:d for d in manifest['documents']}
    documents=scope['documents'];require(len(documents)==20 and sum(d['chunks'] for d in documents)==312)
    require(len({d['id'] for d in documents})==20)
    forbidden={'wstg-345317d8a05797f6','cheatsheets-92f7483b28548679',
               'wstg-7a1e7d6157efc92b','cheatsheets-86ddfbe1de52c357'}
    require(not forbidden & {d['id'] for d in documents})
    identities={}
    for d in documents:
        require({k:v for k,v in d.items() if k not in {'knowledge_source_id','chunks'}}==entries[d['id']])
        for path_key,hash_key in (('original_path','sha256'),('processed_path','processed_sha256')):
            before=(dataset.DATASET/d[path_key]).stat(follow_symlinks=False)
            raw=dataset.read_file(dataset.DATASET,d[path_key]);require(dataset.sha(raw)==d[hash_key])
            require(file_identity(before)==file_identity((dataset.DATASET/d[path_key]).stat(follow_symlinks=False)))
            require(len(raw)==d['size_bytes' if path_key=='original_path' else 'processed_size_bytes'])
            if path_key=='processed_path':
                text=raw.decode();require(normalize_text(text)==text)
                source=source_for(d);require(source.source_id==d['knowledge_source_id'])
                require(len(TextChunker().chunks(source.source_id,'review-only',text))==d['chunks'])
                info=(dataset.DATASET/d[path_key]).stat(follow_symlinks=False)
                identities[str(dataset.DATASET/d[path_key])]=file_identity(info)
        require(dataset.sha(dataset.read_file(dataset.DATASET,d['license']['path']))==d['license']['sha256'])
    return scope,identities


def file_identity(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def source_for(document):
    return KnowledgeSource(document['source_url'],document['title'],document['publisher'],
        TrustClassification.VERIFIED_PUBLISHER,tuple(document['topics']),document['publication_date'])


def revision_for(document):
    source=source_for(document)
    source_json=json.dumps(asdict(source),sort_keys=True,separators=(',',':'))
    return 'rev_'+fingerprint([source_json,document['document_version'],document['processed_sha256'],TextChunker().version])


class ExactAuthority:
    def __init__(self,scope,identities,repository,manifest,queries):
        self.scope=scope;self.identities=identities;self.repository=repository;self.manifest=manifest
        self.queries=queries;self.validation=False
        self.documents={d['knowledge_source_id']:d for d in scope['documents']}

    def decide(self,request):
        expected=None
        if request.purpose is KnowledgePurpose.READ_DOCUMENT and len(request.targets)==1:
            path=request.targets[0]
            if path in self.identities:expected=fingerprint([path,self.identities[path]])
        elif request.purpose is KnowledgePurpose.RETAIN and len(request.targets)==1:
            d=self.documents.get(request.targets[0])
            if d:expected=fingerprint([revision_for(d),d['processed_sha256']])
        elif request.purpose in {KnowledgePurpose.INDEX,KnowledgePurpose.RETRIEVE,KnowledgePurpose.REVOKE}:
            targets=scope_ids(request.targets)
            if set(targets)<=set(self.documents):
                snapshot=self.repository.snapshot(targets)
                if request.purpose is KnowledgePurpose.INDEX and set(targets)==set(self.documents):
                    require(all(rev==revision_for(self.documents[sid]) and sha==self.documents[sid]['processed_sha256']
                                for sid,rev,sha in snapshot))
                    expected=fingerprint([snapshot,self.manifest.generation_id])
                elif request.purpose is KnowledgePurpose.RETRIEVE:
                    allowed={fingerprint([snapshot,self.manifest.generation_id,q]) for q in self.queries}
                    if request.scope_sha256 in allowed:expected=request.scope_sha256
                elif request.purpose is KnowledgePurpose.REVOKE and self.validation and len(targets)==1:
                    expected=fingerprint(snapshot)
        return KnowledgeDecision.ALLOW_ONCE if expected==request.scope_sha256 else KnowledgeDecision.DENY


def write_json(root,name,value):
    """Private atomic checkpoint. SQLite acknowledgments remain authoritative."""
    data=(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
    require(len(data)<=2*1024**2 and '/' not in name)
    with directory_descriptor(root) as directory:
        temporary=name+'.tmp-'+str(os.getpid())
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        with os.fdopen(descriptor,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,name,src_dir_fd=directory,dst_dir_fd=directory)
        os.fsync(directory)


def counts(repository,manifest):
    with repository.transaction() as db:
        documents=db.execute("SELECT COUNT(*) FROM sources WHERE state='active'").fetchone()[0]
        chunks=db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
        indexed=db.execute('SELECT COUNT(*) FROM indexed_chunks WHERE generation_id=?',(manifest.generation_id,)).fetchone()[0]
    require(chunks<=312 and indexed<=312 and documents<=20)
    return {'documents':documents,'chunks':chunks,'indexed_chunks':indexed}


def verify_repository(repository,scope,manifest,*,complete=True):
    expected={d['knowledge_source_id']:d for d in scope['documents']}
    rows=[]
    with repository.transaction() as db:
        sources=db.execute('SELECT * FROM sources').fetchall()
        require(all(s['source_id'] in expected and s['state']=='active' and
                    s['identifier']==expected[s['source_id']]['source_url'] and
                    s['current_revision']==revision_for(expected[s['source_id']]) for s in sources))
        revisions=db.execute('SELECT * FROM revisions').fetchall()
        require(len(revisions)==len(sources))
        for row in revisions:
            revision=repository._revision(row);d=expected[revision.source.source_id]
            require(revision.revision_id==revision_for(d) and revision.content_sha256==d['processed_sha256'])
            require(revision.document_revision==d['document_version'] and revision.source==source_for(d))
            generated=TextChunker().chunks(revision.source.source_id,revision.revision_id,revision.text)
            stored=db.execute('SELECT * FROM chunks WHERE revision_id=? ORDER BY ordinal',(revision.revision_id,)).fetchall()
            require(len(stored)==len(generated)==d['chunks'])
            for chunk,stored_chunk in zip(generated,stored,strict=True):
                require(all(stored_chunk[k]==v for k,v in asdict(chunk).items()))
                rows.append({k:stored_chunk[k] for k in ('chunk_id','source_id','revision_id','content_sha256')})
        require(db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]==len(rows))
        acknowledged=db.execute('SELECT * FROM indexed_chunks').fetchall()
        mapping={r['chunk_id']:r for r in rows}
        require(all(r['generation_id']==manifest.generation_id and r['chunk_id'] in mapping and
                    r['content_sha256']==mapping[r['chunk_id']]['content_sha256'] for r in acknowledged))
        if complete:require(len(sources)==20 and len(rows)==len(acknowledged)==312)
    return sorted(rows,key=lambda r:r['chunk_id'])


def inspect_vectors(index,repository,scope,manifest,rows,monitor):
    require(index.count()==len(rows))
    fingerprints=[]
    for start in range(0,len(rows),4):
        monitor.check(len(rows));batch=rows[start:start+4]
        records=index.inspect(tuple(r['chunk_id'] for r in batch));require(len(records)==len(batch))
        actual={r.chunk_id:r for r in records}
        for row in batch:
            record=actual[row['chunk_id']]
            require(all(getattr(record,k)==v for k,v in row.items()))
            require(repository.evidence(record.chunk_id,scope,manifest) is not None)
            fingerprints.append(fingerprint(asdict(record)))
    return fingerprint(fingerprints)


def wait_idle(provider,monitor,*,owned=False):
    deadline=monotonic()+10
    while True:
        monitor.check()
        resident=provider._request('/api/ps',monotonic()+5).get('models')
        require(type(resident) is list)
        if not resident:return
        if not owned or any(m.get('name')!=provider.manifest.model or m.get('digest')!=provider.manifest.model_revision for m in resident):
            raise AdmissionDenied('Unrelated Ollama workload is resident; stopped without eviction.')
        if monotonic()>=deadline:raise AdmissionDenied('Owned Nomic unload did not finish within ten seconds.')
        monitor.cancelled.wait(.1)


def validate_citation(repository,evidence,scope,manifest,documents):
    authoritative=repository.evidence(evidence.chunk.chunk_id,scope,manifest)
    require(authoritative is not None)
    chunk,revision=authoritative;d=documents[chunk.source_id]
    require(evidence.chunk==chunk and evidence.source==revision.source and evidence.document_sha256==d['processed_sha256'])
    require(evidence.document_revision==d['document_version'] and chunk.revision_id==revision_for(d))


class ValidationRollback(Exception):pass


def validate_exclusion(repository,index,provider,auth,authority,scope,manifest,question):
    """Exercise actual revocation/stale filtering in one rolled-back transaction.

    Reuse the sole repository and production vectors; no new document revision,
    test repository, irreversible source revocation or vector mutation occurs.
    """
    before=repository.snapshot(scope);source=scope[0]
    with repository.transaction() as db:
        chunk=db.execute('SELECT chunk_id FROM chunks WHERE source_id=? LIMIT 1',(source,)).fetchone()[0]
    results={}
    for mode in ('revoked','outdated'):
        try:
            with repository.transaction() as db:
                @contextmanager
                def nested():
                    repository._check_files();yield db;repository._check_files()
                with patch.object(repository,'transaction',nested):
                    authority.validation=True
                    if mode=='revoked':repository.revoke(source,auth)
                    else:db.execute('UPDATE sources SET current_revision=? WHERE source_id=?',('rev_'+digest('isolated stale pointer'),source))
                    require(repository.evidence(chunk,scope,manifest) is None)
                    result=RetrievalService(repository,provider,index,auth).retrieve(question,(source,))
                    require(not result.evidence);results[mode+'_source_excluded']=True
                    raise ValidationRollback()
        except ValidationRollback:pass
        finally:authority.validation=False
        require(repository.snapshot(scope)==before)
    # The existing evidence service must reject a genuine foreign candidate.
    foreign=next(s for s in scope if s!=source)
    with repository.transaction() as db:
        foreign_chunk=db.execute('SELECT chunk_id FROM chunks WHERE source_id=? LIMIT 1',(foreign,)).fetchone()[0]
    fake_provider=Mock();fake_provider.manifest=manifest;fake_provider.embed_query.return_value=(1.,)+(0.,)*(manifest.dimensions-1)
    candidate_index=Mock();candidate_index.manifest=manifest;candidate_index.query.return_value=(VectorCandidate(foreign_chunk,.1),)
    require(not RetrievalService(repository,fake_provider,candidate_index,auth).retrieve(question,(source,)).evidence)
    results['wrong_document_candidate_rejected']=True
    results['production_snapshot_restored']=True
    return results


def evaluate(repository,index,provider,auth,authority,scope,manifest,questions,monitor):
    documents=authority.documents;results=[];latencies=[];citation_total=0
    for question in questions:
        wait_idle(provider,monitor,owned=True)
        snapshot=repository.snapshot(scope)
        auth.require(AuthorizationRequest(KnowledgePurpose.RETRIEVE,scope_ids(scope),
            fingerprint([snapshot,manifest.generation_id,question['question']])))
        started=monotonic();vector=provider.embed_query(question['question']);embed_seconds=monotonic()-started
        started=monotonic();candidates=index.query(vector,scope,5);search_seconds=monotonic()-started
        require(repository.snapshot(scope)==snapshot)
        verified=[repository.evidence(c.chunk_id,scope,manifest) for c in candidates]
        require(all(v is not None for v in verified))
        sources=[v[0].source_id for v in verified]
        # Reuse the existing retrieval/citation path without a second embedding.
        cached=Mock();cached.manifest=manifest;cached.embed_query.return_value=vector
        evidence=RetrievalService(repository,cached,index,auth).retrieve(question['question'],scope)
        for item in evidence.evidence:
            validate_citation(repository,item,scope,manifest,documents)
            require(evidence.citation(item.citation_id)['source']==item.source.identifier)
            citation_total+=1
        duration=embed_seconds+search_seconds;latencies.append(duration)
        results.append({'id':question['id'],'expected_source_id':question['expected_source_id'],
            'ranked_source_ids':sources,'top1_correct':bool(sources and sources[0]==question['expected_source_id']),
            'expected_source_in_top5':question['expected_source_id'] in sources,
            'expected_source_in_budgeted_evidence':any(e.source.source_id==question['expected_source_id'] for e in evidence.evidence),
            'citation_count':len(evidence.evidence),'embedding_seconds':embed_seconds,'search_seconds':search_seconds,
            'retrieval_seconds':duration,'ollama_metrics':provider.last_metrics})
        monitor.check(312)
    # A repeated query measures cache-warm reload, not a kept-resident model.
    wait_idle(provider,monitor,owned=True);started=monotonic()
    result=RetrievalService(repository,provider,index,auth).retrieve(questions[0]['question'],scope)
    repeated=monotonic()-started
    for item in result.evidence:validate_citation(repository,item,scope,manifest,documents)
    return {'questions':results,'sample_size':len(results),
        'top1_accuracy':sum(r['top1_correct'] for r in results)/len(results),
        'recall_at_5':sum(r['expected_source_in_top5'] for r in results)/len(results),
        'budgeted_evidence_accuracy':sum(r['expected_source_in_budgeted_evidence'] for r in results)/len(results),
        'wrong_document_top1_retrieval_rate':sum(not r['top1_correct'] for r in results)/len(results),
        'citation_integrity_failure_rate':0.,'verified_citations':citation_total,
        'first_model_nonresident_retrieval_seconds':latencies[0],
        'cache_warm_reload_retrieval_p50_seconds':statistics.median(latencies[1:]),
        'retrieval_p50_seconds':statistics.median(latencies),'retrieval_max_seconds':max(latencies),
        'repeated_query_end_to_end_seconds':repeated,
        'limitations':'Seven curated questions, one expected document each, document-level recall@5 over five chunks. '
                     'Not comprehensive relevance judgments or strong quality evidence. Every model request keep_alive=0; '
                     'warm means filesystem/cache-warm reload, not model-resident latency. No OS cache eviction.'}


def main():
    scope,identities=revalidate()
    manifest=IndexManifest(**scope['index_manifest'])
    packages=verify_packages(dataset.ROOT);models=verify_models(dataset.ROOT,manifest)
    free=shutil.disk_usage(dataset.ROOT).free;ram=available_ram()
    admit_monitored(ram=ram,disk=free,storage=0,chunks=0)
    question_artifact=json.loads((dataset.ROOT/'docs/FRIDAY_PHASE1E_RETRIEVAL_QUESTIONS.json').read_text())
    questions=question_artifact['questions'];require(len(questions)==7 and question_artifact['corpus_sha256']==APPROVED)
    docs={d['knowledge_source_id']:d for d in scope['documents']}
    for q in questions:
        d=docs[q['expected_source_id']]
        require(q['expected_document_id']==d['id'] and q['expected_processed_sha256']==d['processed_sha256'] and q['expected_source_url']==d['source_url'])
    root=dataset.ROOT/'data/intelligence/phase1e'
    with directory_descriptor(root,create=True) as directory:
        lock_fd=os.open('.session.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=directory)
    cancelled=Event();gate=create_synchronization();report={'corpus_sha256':APPROVED,
        'index_manifest':asdict(manifest),'embedding_generation_id':manifest.generation_id,'packages':packages,'models_before':models,
        'policy':'Owner authorized monitored soft limits; no hard quota/cgroup prerequisite.',
        'status':'incomplete','completed_batches':[],'initial_available_ram_bytes':ram,'initial_free_disk_bytes':free}
    old_handlers={}
    try:
        fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        _private_tree(str(root))
        for sig in (signal.SIGINT,signal.SIGTERM):
            old_handlers[sig]=signal.signal(sig,lambda *_:cancelled.set())
        if (root/'approved-scope.json').exists():
            require(json.loads((root/'approved-scope.json').read_text())==scope)
        else:write_json(root,'approved-scope.json',scope)
        with Monitor(root,cancelled) as monitor:
            try:
                with KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repository:
                    authority=ExactAuthority(scope,identities,repository,manifest,{q['question'] for q in questions})
                    auth=KnowledgeAuthorization(authority.decide);sources=tuple(sorted(docs))
                    verify_repository(repository,scope,manifest,complete=False)
                    for d in scope['documents']:
                        monitor.check(counts(repository,manifest)['chunks'])
                        text=read_text_file(dataset.DATASET/d['processed_path'],auth)
                        require(digest(text)==d['processed_sha256'])
                        revision=repository.ingest(source_for(d),text,auth,TextChunker(),document_revision=d['document_version'])
                        require(revision.revision_id==revision_for(d))
                    verify_repository(repository,scope,manifest,complete=False)
                    report['starting_progress']=counts(repository,manifest)
                    provider=__import__('friday.intelligence.ollama_embeddings',fromlist=['OllamaEmbeddingProvider']).OllamaEmbeddingProvider(manifest,gate,timeout=30,cancelled=cancelled)
                    with ChromaVectorIndex(root/'chroma',manifest,timeout=30,cancelled=cancelled) as index:
                        service=IndexingService(repository,provider,index,auth)
                        started=monotonic();new_chunks=0
                        while True:
                            wait_idle(provider,monitor,owned=bool(report['completed_batches']))
                            current=counts(repository,manifest);monitor.check(current['chunks'])
                            size=service.index_batch(sources)
                            if not size:break
                            require(1<=size<=4);new_chunks+=size;require(new_chunks<=312)
                            current=counts(repository,manifest)
                            observed=monitor.check(current['chunks'])
                            report['completed_batches'].append({'batch':len(report['completed_batches'])+1,'chunks':size,
                                'acknowledged_chunks':current['indexed_chunks'],'resources':observed,'embedding':provider.last_metrics})
                            write_json(root,'progress.json',{'corpus_sha256':APPROVED,'progress':current,
                                'last_batch':report['completed_batches'][-1],'status':'indexing'})
                            monitor.check(current['chunks'])
                            if len(report['completed_batches'])%10==0:print('Indexed',current['indexed_chunks'],'of 312 chunks',flush=True)
                        report['indexing_seconds']=monotonic()-started;report['new_chunks_this_session']=new_chunks
                        rows=verify_repository(repository,scope,manifest)
                        before=inspect_vectors(index,repository,sources,manifest,rows,monitor)
                        report['vector_fingerprint_before_close']=before
                    # Both stores close and reopen before persistence checks.
                with KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repository, \
                     ChromaVectorIndex(root/'chroma',manifest,timeout=30,cancelled=cancelled) as index:
                    authority=ExactAuthority(scope,identities,repository,manifest,{q['question'] for q in questions})
                    auth=KnowledgeAuthorization(authority.decide)
                    rows=verify_repository(repository,scope,manifest)
                    after=inspect_vectors(index,repository,sources,manifest,rows,monitor)
                    require(after==before);report['vector_fingerprint_after_reopen']=after
                    report['persisted_counts']=counts(repository,manifest);report['persisted_vector_count']=index.count()
                    report['idempotent_no_pending_chunks']=not repository.pending_chunks(sources,manifest)
                    require(report['idempotent_no_pending_chunks'])
                    provider=__import__('friday.intelligence.ollama_embeddings',fromlist=['OllamaEmbeddingProvider']).OllamaEmbeddingProvider(manifest,gate,timeout=30,cancelled=cancelled)
                    report['exclusion_validation']=validate_exclusion(repository,index,provider,auth,authority,sources,manifest,questions[0]['question'])
                    verify_repository(repository,scope,manifest)
                    report['retrieval']=evaluate(repository,index,provider,auth,authority,sources,manifest,questions,monitor)
                    verify_repository(repository,scope,manifest)
                    wait_idle(provider,monitor,owned=True)
                    tags=provider._request('/api/tags',monotonic()+10)['models']
                    require(any(m.get('name')=='qwen3:4b' and m.get('digest')==QWEN for m in tags))
                    report['unrelated_models_unchanged']=all(any(m.get('name')==name and m.get('digest')==sha for m in tags)
                        for name,sha in (('qwen3:4b',QWEN),(manifest.model,manifest.model_revision)))
                    require(report['unrelated_models_unchanged'])
                monitor.check(312);report['status']='complete'
                write_json(root,'progress.json',{'corpus_sha256':APPROVED,'progress':report['persisted_counts'],'status':'complete'})
            except (KnowledgeError,AdmissionDenied,OSError,ValueError) as error:
                report['status']='stopped_recoverable';report['stop_reason']=str(error) if isinstance(error,(KnowledgeError,AdmissionDenied)) else 'Local storage or verification failed safely.'
                cancelled.set();raise
            finally:
                report['measurements']=monitor.summary()
                write_json(root,'execution.json',report)
        _private_tree(str(root));print(json.dumps({k:report[k] for k in ('status','persisted_counts','indexing_seconds','retrieval','measurements')},indent=2))
        return 0
    finally:
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
        gate.close();os.close(lock_fd)


if __name__=='__main__':raise SystemExit(main())
