"""Monitored-policy, exact-authorization and rollback validation tests."""
from dataclasses import asdict
import os
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from scripts.phase1e_monitored import admit_monitored, Monitor, descendants
from scripts.phase1e_admission import AdmissionDenied, GIB, MIB
from scripts.phase1e_index import (ExactAuthority, revision_for, source_for, validate_exclusion,
                                  revalidate, file_identity)
from friday.intelligence.models import digest, fingerprint, TrustClassification, KnowledgeError
from friday.intelligence.permissions import AuthorizationRequest, KnowledgeAuthorization, KnowledgePurpose, KnowledgeDecision
from friday.intelligence.chroma_index import ChromaVectorIndex, _worker, CHROMA_VERSION
from test_intelligence_foundation import FoundationFixture, NETWORKING


class MonitoredPolicyTests(unittest.TestCase):
    def test_soft_policy_does_not_require_hard_quota(self):
        admit_monitored(ram=3*GIB,disk=10*GIB,storage=100*MIB,chunks=312)

    def test_every_admission_boundary_and_cancellation(self):
        good={'ram':3*GIB,'disk':10*GIB,'storage':100*MIB,'chunks':312}
        for key,value in (('ram',3*GIB-1),('disk',10*GIB-1),('storage',100*MIB+1),('chunks',313),('cancelled',True)):
            with self.subTest(key=key),self.assertRaises(AdmissionDenied):
                admit_monitored(**{**good,key:value})
        for bad in (None,True,-1):
            with self.assertRaises(AdmissionDenied):admit_monitored(**{**good,'ram':bad})

    def test_descendants_include_ollama_runner_and_grandchildren(self):
        values={1:{'parent':0},2:{'parent':1},3:{'parent':2},4:{'parent':0}}
        self.assertEqual(descendants(values,{1}),{1,2,3})

    def test_monitor_denies_low_ram_and_session_deadline(self):
        values={os.getpid():{'parent':0,'start':1,'cpu':1.,'rss':1024,'name':'python'}}
        for low_ram in (True,False):
            with TemporaryDirectory() as folder,patch('scripts.phase1e_monitored.processes',return_value=values), \
                 patch('scripts.phase1e_monitored.available_ram',return_value=2*GIB if low_ram else 4*GIB), \
                 patch('scripts.phase1e_monitored.shutil.disk_usage',return_value=Mock(free=20*GIB)):
                event=Event();monitor=Monitor(Path(folder),event)
                if not low_ram:monitor.deadline=0
                with self.assertRaises(AdmissionDenied):monitor.check()
                self.assertTrue(event.is_set());self.assertIsNotNone(monitor.reason)

    def test_approved_content_revalidation_does_not_open_excluded_documents(self):
        from scripts import phase1d_dataset as d
        if not d.DATASET.exists():self.skipTest('Local corpus is required')
        original=d.read_file
        def read(root,path):
            self.assertFalse(any(identifier in path for identifier in
                ('345317d8a05797f6','92f7483b28548679','7a1e7d6157efc92b','86ddfbe1de52c357')))
            return original(root,path)
        with patch('scripts.phase1e_index.dataset.read_file',side_effect=read):
            scope,identities=revalidate()
        self.assertEqual(len(scope['documents']),20);self.assertEqual(len(identities),20)


class ExactExperimentTests(FoundationFixture):
    def fixtures(self):
        documents=[]
        for name in ('one','two'):
            source=self.source(name,trust=TrustClassification.VERIFIED_PUBLISHER)
            d={'source_url':source.identifier,'title':source.title,'publisher':source.publisher,
               'topics':list(source.topics),'publication_date':None,'document_version':'test-v1',
               'processed_sha256':digest(NETWORKING),'knowledge_source_id':source.source_id}
            revision=self.repo.ingest(source,NETWORKING,self.auth,self.chunker,document_revision='test-v1')
            self.assertEqual(revision.revision_id,revision_for(d))
            documents.append(d)
        scope=tuple(sorted(d['knowledge_source_id'] for d in documents))
        self.indexer.index_batch(scope)
        authority=ExactAuthority({'documents':documents},{},self.repo,self.manifest,{'approved question'})
        return scope,authority,KnowledgeAuthorization(authority.decide)

    def test_exact_retain_and_index_authorization_rejects_new_revision(self):
        scope,authority,auth=self.fixtures();d=authority.documents[scope[0]]
        request=AuthorizationRequest(KnowledgePurpose.RETAIN,(scope[0],),fingerprint([revision_for(d),d['processed_sha256']]))
        auth.require(request)
        with self.assertRaises(PermissionError):
            auth.require(AuthorizationRequest(KnowledgePurpose.RETAIN,(scope[0],),digest('new revision')))
        with self.assertRaises(PermissionError):
            auth.require(AuthorizationRequest(KnowledgePurpose.INDEX,(scope[0],),digest('subset indexing')))
        with self.assertRaises(PermissionError):
            auth.require(AuthorizationRequest(KnowledgePurpose.REVOKE,(scope[0],),fingerprint(self.repo.snapshot((scope[0],)))))

    def test_rolled_back_revocation_outdated_pointer_and_wrong_source_filtering(self):
        scope,authority,auth=self.fixtures()
        before=self.repo.snapshot(scope)
        result=validate_exclusion(self.repo,self.index,self.provider,auth,authority,scope,self.manifest,'approved question')
        self.assertTrue(all(result.values()));self.assertEqual(self.repo.snapshot(scope),before)
        self.assertTrue(self.repo.has_indexed(scope,self.manifest))
        self.assertFalse(authority.validation)


class VectorInspectionTests(unittest.TestCase):
    def setUp(self):
        from friday.intelligence.models import IndexManifest
        self.adapter=object.__new__(ChromaVectorIndex)
        self.adapter.manifest=IndexManifest('synthetic',digest('model'),2)
        self.row={'chunk_id':'chk_'+digest('chunk'),'source_id':'src_'+digest('source'),
                  'revision_id':'rev_'+digest('revision'),'content_sha256':digest('text'),'vector':[1.,0.]}
        self.adapter._rpc=Mock(return_value=[self.row])

    def test_bounded_inspection_and_count(self):
        result=self.adapter.inspect((self.row['chunk_id'],))
        self.assertEqual(result[0].vector,(1.,0.))
        self.adapter._rpc.assert_called_once_with('inspect',[self.row['chunk_id']])
        self.adapter._rpc.return_value=312;self.assertEqual(self.adapter.count(),312)
        self.adapter._rpc.return_value=True
        with self.assertRaises(KnowledgeError):self.adapter.count()
        for ids in ((),(self.row['chunk_id'],)*2,tuple('chk_'+digest(str(i)) for i in range(5))):
            with self.assertRaises(KnowledgeError):self.adapter.inspect(ids)

    def test_inspection_rejects_foreign_duplicate_and_unnormalized_vectors(self):
        for row in ({**self.row,'vector':[2.,0.]},{**self.row,'chunk_id':'chk_'+digest('foreign')},
                    {**self.row,'text':'document text forbidden'}):
            self.adapter._rpc.return_value=[row]
            with self.assertRaises(KnowledgeError):self.adapter.inspect((self.row['chunk_id'],))

    def test_worker_inspection_returns_explicit_vectors_and_metadata(self):
        collection=Mock()
        collection.metadata={'friday_manifest':self.adapter.manifest.generation_id.removeprefix('idx_'),'hnsw:space':'cosine'}
        collection.configuration={'hnsw':{'space':'cosine'}}
        collection.count.return_value=1
        collection.get.return_value={'ids':[self.row['chunk_id']],
            'embeddings':[self.row['vector']],
            'metadatas':[{k:self.row[k] for k in ('source_id','revision_id','content_sha256')}]}
        client=Mock();client.get_collection.return_value=collection
        module=types.ModuleType('chromadb');module.PersistentClient=Mock(return_value=client)
        module.errors=types.SimpleNamespace(NotFoundError=KeyError)
        config=types.ModuleType('chromadb.config');config.Settings=Mock()
        channel=Mock();channel.recv.side_effect=[('count',None),('inspect',[self.row['chunk_id']]),('close',None)]
        with TemporaryDirectory() as folder,patch.dict('sys.modules',{'chromadb':module,'chromadb.config':config}), \
             patch.dict(os.environ),patch('os.dup2'),patch('os.umask'),patch('os.chdir'), \
             patch('friday.intelligence.chroma_index.deny_worker_network'), \
             patch('importlib.metadata.version',return_value=CHROMA_VERSION):
            _worker(channel,folder,asdict(self.adapter.manifest))
        self.assertEqual(channel.send.call_args_list[1].args,(('ok',1),))
        self.assertEqual(channel.send.call_args_list[2].args,(('ok',[self.row]),))
        collection.get.assert_called_once_with(ids=[self.row['chunk_id']],include=['embeddings','metadatas'])
