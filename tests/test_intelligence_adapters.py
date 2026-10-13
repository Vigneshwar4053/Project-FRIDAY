"""Adapter contracts without installed packages, model weights or live inference."""
from dataclasses import asdict, replace
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import types
import unittest
from unittest.mock import Mock, patch

from friday.intelligence.models import IndexManifest, KnowledgeError, digest
from friday.intelligence.index import VectorRecord
from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
from friday.intelligence.chroma_index import ChromaVectorIndex, _worker, _private_tree, CHROMA_VERSION
from friday.sync import PythonSemaphore


class OllamaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.manifest=IndexManifest('nomic-embed-text:v1.5',digest('synthetic artifact'),768,
            'search_document: ','search_query: ')
        self.gate=PythonSemaphore();self.addCleanup(self.gate.close)
        self.provider=OllamaEmbeddingProvider(self.manifest,self.gate)
        self.calls=[]
        def request(path,deadline,payload=None):
            self.calls.append((path,payload))
            if path=='/api/tags':return {'models':[{'name':self.manifest.model,'digest':self.manifest.model_revision}]}
            if path=='/api/show':return {'capabilities':['embedding'],'model_info':{'nomic-bert.embedding_length':768}}
            if path=='/api/ps':return {'models':[]}
            return {'model':self.manifest.model,'embeddings':[[1.]+[0.]*767 for _ in payload['input']],
                    'load_duration':100,'total_duration':200,'prompt_eval_count':10}
        self.request=request
        self.provider._request=Mock(side_effect=request)

    def test_manifest_endpoint_and_timeout_validation(self):
        for url in ('https://127.0.0.1:11434','http://localhost:11434','http://example.com:11434',
                    'http://user:pass@127.0.0.1:11434','http://127.0.0.1/api','http://127.0.0.1?token=a',
                    'http://127.0.0.1:99999'):
            with self.assertRaises(KnowledgeError):OllamaEmbeddingProvider(self.manifest,self.gate,base_url=url)
        with self.assertRaises(KnowledgeError):OllamaEmbeddingProvider(replace(self.manifest,dimensions=384),self.gate)
        with self.assertRaises(KnowledgeError):OllamaEmbeddingProvider(self.manifest,self.gate,timeout=math.nan)

    def test_explicit_prefixes_no_truncation_or_pull_and_scalar_metrics(self):
        result=self.provider.embed_documents(('TCP versus UDP','Linux security'))
        self.assertEqual(len(result),2);self.assertEqual(len(result[0]),768)
        payload=next(body for path,body in self.calls if path=='/api/embed')
        self.assertEqual(payload['input'],['search_document: TCP versus UDP','search_document: Linux security'])
        self.assertIs(payload['truncate'],False);self.assertEqual(payload['keep_alive'],0)
        self.assertNotIn('/api/pull',[p for p,_ in self.calls])
        self.assertEqual(self.provider.last_metrics['load_ns'],100)
        self.calls.clear();self.provider.embed_query('What is UDP?')
        self.assertEqual(next(b for p,b in self.calls if p=='/api/embed')['input'],['search_query: What is UDP?'])

    def test_missing_model_or_changed_digest_is_not_downloaded(self):
        for models in ([],[{'name':self.manifest.model,'digest':digest('changed')}],
                       [{'name':self.manifest.model,'digest':self.manifest.model_revision}]*2):
            self.calls.clear()
            self.provider._request.side_effect=lambda path,deadline,payload=None:{'models':models}
            with self.assertRaises(KnowledgeError):self.provider.embed_query('TCP')
        self.assertFalse(any(p=='/api/embed' for p,_ in self.calls))

    def test_resident_qwen_or_other_model_is_never_evicted(self):
        def request(path,deadline,payload=None):
            if path=='/api/ps':return {'models':[{'name':'qwen3:4b'}]}
            return self.request(path,deadline,payload)
        self.provider._request.side_effect=request
        with self.assertRaises(KnowledgeError):self.provider.embed_query('TCP')
        self.assertNotIn('/api/embed',[p for p,_ in self.calls]);self.assertNotIn('/api/generate',[p for p,_ in self.calls])

    def test_shared_gate_excludes_generation(self):
        self.gate.acquire();finished=Event()
        thread=Thread(target=lambda:(self.provider.embed_query('TCP'),finished.set()))
        thread.start()
        self.assertFalse(finished.wait(.03));self.assertEqual(self.calls,[])
        self.gate.release();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertTrue(finished.is_set())

    def test_bounds_secrets_and_cancellation_prevent_inference(self):
        for value in ('','x'*2049,'api_key=synthetic','\ud800'):
            with self.assertRaises(KnowledgeError):self.provider.embed_query(value)
        self.assertEqual(self.calls,[])
        self.provider.cancelled.set()
        # _request is mocked; production checks are tested directly below.
        with self.assertRaises(KnowledgeError):self.provider._check(math.inf)

    def test_nonfinite_wrong_dimension_and_wrong_model_fail_closed(self):
        original=self.request
        for result in ({'model':self.manifest.model,'embeddings':[[math.nan]*768]},
                       {'model':self.manifest.model,'embeddings':[[1.,0.]]},
                       {'model':'qwen3:4b','embeddings':[[1.]*768]}):
            self.provider._request.side_effect=lambda p,d,b=None,r=result:r if p=='/api/embed' else original(p,d,b)
            with self.assertRaises(KnowledgeError):self.provider.embed_query('TCP')

    def test_transport_rejects_redirects_content_types_and_malformed_json(self):
        provider=OllamaEmbeddingProvider(self.manifest,self.gate)
        response=Mock();connection=Mock();connection.getresponse.return_value=response
        for status,kind,body in [(302,'application/json',b'{}'),(200,'text/html',b'{}'),
                                  (200,'application/json',b'{"x":1,"x":2}'),
                                  (200,'application/json',b'{"value":NaN}')]:
            response.status=status;response.getheader.return_value=kind;response.read1.side_effect=[body,b'']
            with patch('http.client.HTTPConnection',return_value=connection):
                from time import monotonic
                with self.assertRaises(KnowledgeError):provider._request('/api/tags',monotonic()+10)
        connection.close.assert_called()

    def test_transport_byte_limits_timeout_and_no_proxy_configuration(self):
        provider=OllamaEmbeddingProvider(self.manifest,self.gate)
        response=Mock(status=200);response.getheader.return_value='application/json'
        response.read1.side_effect=[b'x'*65536]*17
        connection=Mock();connection.getresponse.return_value=response
        from time import monotonic
        with patch.dict(os.environ,{'HTTP_PROXY':'http://external.invalid','ALL_PROXY':'http://external.invalid'}), \
             patch('http.client.HTTPConnection',return_value=connection) as factory:
            with self.assertRaises(KnowledgeError):provider._request('/api/tags',monotonic()+10)
        self.assertEqual(factory.call_args.args,('127.0.0.1',11434))
        connection.request.side_effect=TimeoutError('PRIVATE text')
        with patch('http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(KnowledgeError) as caught:provider._request('/api/tags',monotonic()+10)
        self.assertNotIn('PRIVATE',str(caught.exception))


class ChromaContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest=IndexManifest('synthetic',digest('artifact'),2)
        self.adapter=object.__new__(ChromaVectorIndex);self.adapter.manifest=self.manifest
        self.adapter._rpc=Mock(return_value=[])
        self.record=VectorRecord('chk_'+digest('c'),'src_'+digest('s'),'rev_'+digest('r'),digest('text'),(1.,0.))

    def test_upsert_sends_vectors_and_opaque_metadata_only(self):
        self.adapter.upsert((self.record,))
        operation,rows=self.adapter._rpc.call_args.args
        self.assertEqual(operation,'upsert');self.assertEqual(rows,[asdict(self.record)])
        self.assertNotIn('text',rows[0]);self.assertNotIn('documents',rows[0])

    def test_bounds_scopes_and_invalid_distances(self):
        for records in ((),(self.record,)*5):
            with self.assertRaises(KnowledgeError):self.adapter.upsert(records)
        with self.assertRaises(KnowledgeError):self.adapter.query((1.,0.),(),1)
        with self.assertRaises(KnowledgeError):self.adapter.query((1.,0.),(self.record.source_id,),9)
        for distance in (math.nan,math.inf,True,3.):
            self.adapter._rpc.return_value=[(self.record.chunk_id,distance)]
            with self.assertRaises(KnowledgeError):self.adapter.query((1.,0.),(self.record.source_id,),1)

    def test_worker_disables_implicit_embeddings_and_filters_exact_sources(self):
        with TemporaryDirectory() as temp:
            collection=Mock();collection.metadata={'friday_manifest':self.manifest.generation_id.removeprefix('idx_'),'hnsw:space':'cosine'}
            collection.configuration={'hnsw':{'space':'cosine'}}
            collection.query.return_value={'ids':[[self.record.chunk_id]],'distances':[[.1]]}
            client=Mock();client.get_collection.return_value=collection
            module=types.ModuleType('chromadb');module.PersistentClient=Mock(return_value=client)
            module.errors=types.SimpleNamespace(NotFoundError=KeyError)
            config=types.ModuleType('chromadb.config');config.Settings=Mock()
            channel=Mock();channel.recv.side_effect=[('upsert',[asdict(self.record)]),
                ('query',((1.,0.),(self.record.source_id,),1)),('close',None)]
            with patch.dict('sys.modules',{'chromadb':module,'chromadb.config':config}), \
                 patch.dict(os.environ,{'CLOUD_SECRET':'PRIVATE'}),patch('os.dup2'),patch('os.umask'),patch('os.chdir'), \
                 patch('friday.intelligence.chroma_index.deny_worker_network') as deny, \
                 patch('importlib.metadata.version',return_value=CHROMA_VERSION):
                _worker(channel,temp,asdict(self.manifest))
            deny.assert_called_once()
            self.assertEqual(client.get_collection.call_args.kwargs['embedding_function'],None)
            kwargs=collection.upsert.call_args.kwargs
            self.assertNotIn('documents',kwargs);self.assertIn('embeddings',kwargs)
            query=collection.query.call_args.kwargs
            self.assertEqual(query['where'],{'source_id':{'$in':[self.record.source_id]}})
            self.assertEqual(query['include'],['distances']);self.assertNotIn('query_texts',query)
            config.Settings.assert_called_once_with(_env_file=None,anonymized_telemetry=False,allow_reset=False)
            self.assertEqual(channel.send.call_args_list[0].args, (('ready',None),))

    def test_manifest_mismatch_and_network_isolation_failure_do_not_initialize(self):
        with TemporaryDirectory() as temp:
            channel=Mock()
            with patch('os.dup2'),patch('os.umask'),patch('os.chdir'),patch.dict(os.environ), \
                 patch('friday.intelligence.chroma_index.deny_worker_network',side_effect=RuntimeError('PRIVATE')):
                _worker(channel,temp,asdict(self.manifest))
            channel.send.assert_called_once_with(('error',None))

    def test_cancellation_and_deadline_are_not_success(self):
        self.adapter.cancelled=Event();self.adapter._channel=Mock();self.adapter._process=Mock()
        self.adapter.cancelled.set()
        with self.assertRaises(KnowledgeError):self.adapter._receive(math.inf)
        self.adapter.cancelled.clear()
        with self.assertRaises(KnowledgeError):self.adapter._receive(0)

    def test_native_network_denial_in_owned_child_does_not_affect_parent(self):
        code=('import ctypes, errno; '
              'from friday.intelligence.chroma_index import deny_worker_network; '
              'deny_worker_network(); c=ctypes.CDLL(None,use_errno=True); '
              'assert c.socket(2,2,0)==-1 and ctypes.get_errno()==errno.EPERM; '
              'print("native networking denied")')
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'native networking denied')

    def test_env_file_is_rejected_before_optional_package_import(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'.env';path.write_text('synthetic fixture');path.chmod(0o600)
            with patch('pathlib.Path.read_text',side_effect=AssertionError('environment content forbidden')):
                with self.assertRaises(RuntimeError):_private_tree(temp)


if __name__=='__main__':unittest.main()
