"""Runtime repair: synthetic pipes, mocked worker/LLM and temporary knowledge only."""
from contextlib import contextmanager
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event,Thread
from time import monotonic
import types
import unittest
from unittest.mock import Mock,patch

from friday.intelligence.models import IndexManifest,KnowledgeError,digest
from friday.intelligence.permissions import KnowledgeDecision
from zorvyq.chroma_protocol import JsonPipe,LIMIT
from zorvyq.chroma_bridge import CompatibleChromaIndex
from zorvyq.rag_runtime import runtime_status,ROOT,EXECUTABLE,ENTRYPOINT,approved_manifest
from scripts.zorvyq_chroma_worker import ReadOnlyChannel

NONCE='a'*64

def frame(sequence,kind,payload=None):
    return dict(version=1,nonce=NONCE,sequence=sequence,kind=kind,payload=payload)

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        a,b=os.pipe();c,d=os.pipe()
        self.client=JsonPipe(c,b,NONCE);self.server=JsonPipe(a,d,NONCE)
        self.addCleanup(self.client.close);self.addCleanup(self.server.close)
    def test_private_pipe_round_trip_and_large_bounded_frame(self):
        payload={'vector':[.1]*768}
        def respond():
            request=self.server.read(monotonic()+2)
            self.server.write(request['sequence'],'ok',payload)
        thread=Thread(target=respond);thread.start()
        self.client.write(1,'query',payload)
        response=self.client.read(monotonic()+2)
        thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(response,frame(1,'ok',payload))
    def test_wrong_identity_schema_duplicates_and_nonfinite_are_rejected(self):
        for changed in ({'nonce':'b'*64},{'version':2},{'sequence':True},{'extra':'PRIVATE'}):
            value={**frame(0,'ready'),**changed}
            os.write(self.server.writer,json.dumps(value).encode()+b'\n')
            with self.assertRaises(ValueError):self.client.read(monotonic()+1)
        os.write(self.server.writer,b'{"version":1,"version":1}\n')
        with self.assertRaises(ValueError):self.client.read(monotonic()+1)
        with self.assertRaises(ValueError):self.server.write(0,'ok',float('nan'))
        with self.assertRaises(ValueError):self.server.write(0,'ok','x'*LIMIT)
    def test_timeout_cancel_and_eof(self):
        with self.assertRaises(TimeoutError):self.client.read(monotonic())
        cancelled=Event();cancelled.set()
        with self.assertRaises(InterruptedError):self.client.read(monotonic()+1,cancelled)
        self.server.close()
        with self.assertRaises(EOFError):self.client.read(monotonic()+1)

class RuntimeMetadataTests(unittest.TestCase):
    def test_exact_existing_environment_metadata_without_import_or_store_open(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);python=root/'data/intelligence/rag-env/bin/python';python.parent.mkdir(parents=True)
            python.write_text('fixture');python.chmod(0o700)
            import sys
            site=root/f'data/intelligence/rag-env/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
            metadata=site/'chromadb-1.5.9.dist-info/METADATA';metadata.parent.mkdir(parents=True)
            metadata.write_text('Name: chromadb\nVersion: 1.5.9\n')
            package=site/'chromadb';package.mkdir();(package/'__init__.py').write_text('raise AssertionError("must not import")')
            self.assertTrue(runtime_status(root)['available'])
            metadata.write_text('Name: chromadb\nVersion: 9.9.9\n')
            self.assertFalse(runtime_status(root)['available'])

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.manifest=IndexManifest('nomic-embed-text:v1.5',digest('fixture'),768,'search_document: ','search_query: ')
        self.patches=[patch('zorvyq.chroma_bridge.runtime_status',return_value={'available':True}),
                      patch('zorvyq.rag_runtime.approved_manifest',return_value=self.manifest),
                      patch('zorvyq.chroma_bridge.secrets.token_hex',return_value=NONCE),
                      patch('zorvyq.chroma_bridge.subprocess.Popen'),
                      patch('zorvyq.chroma_bridge.JsonPipe.read',return_value=frame(0,'ready'))]
        values=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.start,self.read=values[-2:]
        self.child=self.start.return_value;self.child.poll.return_value=0
    def bridge(self):
        result=CompatibleChromaIndex(ROOT/'data/intelligence/phase1e/chroma',self.manifest)
        self.addCleanup(result.close);return result
    def test_fixed_interpreter_script_pipes_no_shell_no_private_payload(self):
        bridge=self.bridge()
        args=self.start.call_args.args[0]
        self.assertEqual(args[:4],[str(EXECUTABLE),'-I','-B',str(ENTRYPOINT)])
        self.assertFalse(self.start.call_args.kwargs['shell'])
        self.assertEqual(len(self.start.call_args.kwargs['pass_fds']),2)
        self.assertEqual(self.start.call_args.kwargs['stdin'],subprocess.DEVNULL)
        self.assertNotIn('question',str(args));self.assertNotIn('PYTHONPATH',self.start.call_args.kwargs['env'])
        bridge.close();self.assertTrue(bridge._channel.closed)
    def test_wrong_root_manifest_and_runtime_fail_without_spawning(self):
        with self.assertRaises(KnowledgeError):CompatibleChromaIndex(Path('/tmp/foreign'),self.manifest)
        with patch('zorvyq.chroma_bridge.runtime_status',return_value={'available':False}):
            with self.assertRaises(KnowledgeError):self.bridge()
        with patch('zorvyq.rag_runtime.approved_manifest',return_value=replace(self.manifest,model_revision='f'*64)):
            with self.assertRaises(KnowledgeError):self.bridge()
        self.start.assert_not_called()
    def test_read_only_allowlist_and_result_schema(self):
        bridge=self.bridge()
        with self.assertRaises(KnowledgeError):bridge._rpc('upsert',[])
        with self.assertRaises(KnowledgeError):bridge._rpc('delete',[])
        bridge._channel.write=Mock()
        self.read.return_value=frame(1,'ok',312)
        self.assertEqual(bridge.count(),312)
        self.read.return_value=frame(2,'ok',[['bad id',.2]])
        with self.assertRaises(KnowledgeError):bridge.query([1.]+[0.]*767,('src_'+'1'*64,),8)
    def test_wrong_sequence_timeout_cancel_kill_only_owned_worker(self):
        bridge=self.bridge();bridge._channel.write=Mock()
        self.read.return_value=frame(7,'ok',1)
        with self.assertRaises(KnowledgeError):bridge.count()
        self.assertTrue(bridge._closed)
        # Constructor cancellation must retain its safe cancellation category.
        self.read.side_effect=InterruptedError()
        with self.assertRaises(KnowledgeError) as caught:self.bridge()
        self.assertEqual(caught.exception.category,'cancelled')
    def test_deadline_failure_closes_worker_and_preserves_category(self):
        bridge=self.bridge();bridge._channel.write=Mock()
        self.read.side_effect=TimeoutError()
        self.child.poll.return_value=None
        self.child.wait.side_effect=[subprocess.TimeoutExpired('fixed worker',.5),0]
        with self.assertRaises(KnowledgeError) as caught:bridge.count()
        self.assertEqual(caught.exception.category,'vector_timeout')
        self.child.terminate.assert_called_once();self.assertTrue(bridge._closed)
    def test_inherited_parent_result_validation_rejects_unknown_fields(self):
        bridge=self.bridge();bridge._channel.write=Mock()
        self.read.return_value=frame(1,'ok',[{'chunk_id':'chk_'+'1'*64,'text':'PRIVATE'}])
        with self.assertRaises(KnowledgeError):bridge.inspect(('chk_'+'1'*64,))
    def test_closed_worker_does_not_accept_more_requests(self):
        bridge=self.bridge();bridge.close()
        with self.assertRaises(KnowledgeError):bridge.count()
    def test_concurrent_rpc_is_refused(self):
        bridge=self.bridge();bridge._lock.acquire()
        try:
            with self.assertRaises(KnowledgeError):bridge.count()
        finally:bridge._lock.release()

class WorkerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest=IndexManifest('fixture',digest('fixture'),2)
        self.source='src_'+'1'*64
    def test_mutations_arbitrary_commands_foreign_scope_and_replay_rejected(self):
        bad=[('upsert',[]),('delete',[]),('exec',{'command':'bad'}),
             ('query',[[1.,0.],['src_'+'2'*64],8]),('query',[[1.,0.],[self.source],9]),('count',{'question':'private'})]
        for operation,payload in bad:
            with self.subTest(operation=operation):
                pipe=Mock();pipe.read.return_value=frame(1,operation,payload)
                channel=ReadOnlyChannel(pipe,self.manifest,[self.source])
                with self.assertRaises((ValueError,KnowledgeError)):channel.recv()
        pipe=Mock();pipe.read.return_value=frame(2,'count')
        with self.assertRaises(ValueError):ReadOnlyChannel(pipe,self.manifest,[self.source]).recv()
    def test_query_allows_only_vectors_scoped_ids_and_bounded_limit(self):
        pipe=Mock();pipe.read.return_value=frame(1,'query',[[1.,0.],[self.source],8])
        channel=ReadOnlyChannel(pipe,self.manifest,[self.source])
        op,payload=channel.recv();self.assertEqual(op,'query');self.assertEqual(payload[1],[self.source])
    def test_original_worker_read_only_mode_validates_migrations_and_refuses_mutation(self):
        from friday.intelligence.chroma_index import _worker,CHROMA_VERSION
        from friday.intelligence.models import fingerprint
        with TemporaryDirectory() as temp:
            channel=Mock();channel.recv.return_value=('upsert',[])
            client=Mock();collection=client.get_collection.return_value
            collection.metadata={'friday_manifest':fingerprint(asdict(self.manifest)),'hnsw:space':'cosine'}
            collection.configuration={'hnsw':{'space':'cosine'}}
            chroma=types.ModuleType('chromadb');chroma.PersistentClient=Mock(return_value=client)
            config=types.ModuleType('chromadb.config');config.Settings=Mock()
            with patch('os.dup2'),patch('os.chdir'),patch('os.umask'),patch.dict(os.environ),patch('friday.intelligence.chroma_index._private_tree'),patch('friday.intelligence.chroma_index.deny_worker_network'),patch('friday.intelligence.chroma_index.importlib.metadata.version',return_value=CHROMA_VERSION),patch.dict('sys.modules',{'chromadb':chroma,'chromadb.config':config}):
                _worker(channel,temp,asdict(self.manifest),existing_only=True,read_only=True)
            config.Settings.assert_called_once_with(_env_file=None,anonymized_telemetry=False,allow_reset=False,migrations='validate')
            collection.upsert.assert_not_called();collection.delete.assert_not_called();client.create_collection.assert_not_called()
            self.assertEqual(channel.send.call_args.args,(('error',None),))

from tests.test_intelligence_foundation import FoundationFixture,OWASP
from friday.intelligence.rag import RagOrchestrator
from friday.models import ModelManager
from friday.config.settings import Settings

class ParentRagBoundaryTests(FoundationFixture):
    def setUp(self):
        super().setUp();self.revision=self.indexed('owasp',OWASP)
        self.bridge=object.__new__(CompatibleChromaIndex);self.bridge.manifest=self.manifest
        chunk=next(iter(self.records))
        self.bridge._rpc=Mock(return_value=[[chunk,.1]])
        self.retriever.index=self.bridge
        self.generation=Mock(model='qwen3:4b',supports_inference_profiles=True)
        self.generation.inference_profile.side_effect=lambda _:__import__('contextlib').nullcontext()
        self.generation.chat.return_value=json.dumps({'claims':[{'text':'Check object authorization.','citations':['S1']}]})
        self.manager=ModelManager(self.generation,'qwen3:4b');self.addCleanup(self.manager.close)
        documents={self.revision.source.source_id:{'source_url':self.revision.source.identifier,'processed_sha256':self.revision.content_sha256,
            'document_version':self.revision.document_revision,'title':'Synthetic source','license':{'name':'Synthetic'}}}
        @contextmanager
        def retrieval():yield self.retriever,documents,Mock()
        self.rag=RagOrchestrator(self.manager,Settings().standard_inference_profile,'Private approved knowledge',retrieval)
        self.approve.reset_mock();self.provider.embed_query.reset_mock()
    def test_each_question_asks_permission_and_preserves_verified_citations_private_jobs(self):
        for _ in range(2):
            answer=self.rag.answer('object authorization')
            self.assertIn('Verified sources:',answer);self.assertIn('[S1]',answer)
        self.assertEqual(self.approve.call_count,2)
        self.assertEqual(self.rag.last_status['citation_validation_status'],'verified')
        self.assertEqual(self.manager.last_job.messages,[]);self.assertIsNone(self.manager.last_job.result)
        self.assertEqual(self.bridge._rpc.call_args.args[0],'query')
    def test_denial_never_embeds_queries_or_generates(self):
        self.approve.return_value=KnowledgeDecision.DENY
        self.assertIn('authorization denied',self.rag.answer('object authorization'))
        self.provider.embed_query.assert_not_called();self.bridge._rpc.assert_not_called();self.generation.chat.assert_not_called()
    def test_invalid_citation_is_rejected_in_parent(self):
        self.generation.chat.return_value=json.dumps({'claims':[{'text':'Bad claim','citations':['S99']}]})
        self.assertIn('Grounding failure',self.rag.answer('object authorization'))
        self.assertEqual(self.rag.last_status['failure_category'],'citation_rejected')
        self.assertNotIn('Verified sources:',self.rag.answer('object authorization'))
    def test_revocation_during_approval_stops_before_query(self):
        def revoke(request):
            self.repo.revoke(self.revision.source.source_id,__import__('friday.intelligence.permissions',fromlist=['KnowledgeAuthorization']).KnowledgeAuthorization(lambda _:KnowledgeDecision.ALLOW_ONCE))
            return KnowledgeDecision.ALLOW_ONCE
        self.approve.side_effect=revoke
        self.assertIn('failed safely',self.rag.answer('object authorization'))
        self.assertEqual(self.rag.last_status['failure_category'],'source_changed')
        self.provider.embed_query.assert_not_called();self.bridge._rpc.assert_not_called()

    def test_live_factory_injects_only_index_transport_preserving_parent_permission_and_citations(self):
        from friday.intelligence.rag import live_orchestrator
        from unittest.mock import MagicMock
        import scripts.phase1e_index
        source=self.revision.source
        document={'knowledge_source_id':source.source_id,'source_url':source.identifier,
            'processed_sha256':self.revision.content_sha256,'document_version':self.revision.document_revision,
            'title':source.title,'license':{'name':'Synthetic'}}
        scope={'index_manifest':asdict(self.manifest),'documents':[document]}
        factory=MagicMock();factory.return_value.__enter__.return_value=self.bridge
        permission=Mock(return_value=KnowledgeDecision.ALLOW_ONCE)
        approval_factory=Mock(return_value=permission)
        cancelled=Event();self.provider._request.return_value={'models':[]}
        with patch('scripts.phase1e_index.revalidate',return_value=(scope,{})), \
             patch('scripts.phase1e_index.verify_repository',return_value=[]), \
             patch('scripts.phase1e_index.inspect_vectors',return_value='0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca'), \
             patch('pathlib.Path.is_file',return_value=True), \
             patch('friday.intelligence.repository.KnowledgeRepository') as repository, \
             patch('friday.intelligence.ollama_embeddings.OllamaEmbeddingProvider',return_value=self.provider):
            repository.return_value.__enter__.return_value=self.repo
            rag=live_orchestrator(self.manager,Settings(),approval_factory=approval_factory,index_factory=factory,cancelled=cancelled)
            answer=rag.answer('object authorization')
        self.assertIn('Verified sources:',answer)
        self.assertEqual(factory.call_args.kwargs,{'cancelled':cancelled,'existing_only':True})
        permission.assert_called_once();approval_factory.assert_called_once()
        self.assertEqual(rag.last_status['citation_validation_status'],'verified')
        self.assertEqual(self.manager.last_job.messages,[])
