"""Pinned local embeddings over direct HTTP; no proxies, redirects or pulls."""
from contextlib import nullcontext
import http.client
import json
import math
from threading import Event
from time import monotonic
from urllib.parse import urlsplit

from friday.intelligence.models import IndexManifest, KnowledgeError
from friday.intelligence.embeddings import normalized_vector
from friday.intelligence.ingestion import normalize_text, reject_secrets
from friday.sync.base import Synchronization


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


class OllamaEmbeddingProvider:
    """Inject the same execution gate as generation. Refuse resident workloads.

    FRIDAY's shared gate excludes its own generation; it cannot lock external
    Ollama clients. No existing model is unloaded. Our requests use keep_alive=0.
    """
    def __init__(self,manifest,synchronization,*,base_url='http://127.0.0.1:11434',timeout=30,cancelled=None):
        if (type(manifest) is not IndexManifest or manifest.model!='nomic-embed-text:v1.5' or
                manifest.dimensions!=768 or manifest.document_prefix!='search_document: ' or
                manifest.query_prefix!='search_query: ' or not isinstance(synchronization,Synchronization)):
            raise KnowledgeError('Reviewed embedding manifest and shared synchronization are required.')
        try:
            parsed=urlsplit(base_url)
            if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','::1'} or
                    parsed.username is not None or parsed.password is not None or
                    parsed.path not in {'','/'} or parsed.query or parsed.fragment):raise ValueError()
            port=parsed.port or 11434
            if not 1<=port<=65535:raise ValueError()
        except (ValueError,TypeError):raise KnowledgeError('Only an explicit loopback Ollama endpoint is supported.') from None
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=60:
            raise KnowledgeError('Invalid embedding timeout.')
        self.manifest=manifest;self.synchronization=synchronization;self.host=parsed.hostname;self.port=port
        self.timeout=timeout;self.cancelled=cancelled if cancelled is not None else Event()
        self.last_metrics=None

    def _check(self,deadline):
        if self.cancelled.is_set():raise KnowledgeError('Embedding request cancelled.')
        if monotonic()>=deadline:raise KnowledgeError('Embedding request exceeded its deadline.')

    def _request(self,path,deadline,payload=None):
        self._check(deadline)
        data=json.dumps(payload,allow_nan=False,separators=(',',':')).encode() if payload is not None else None
        if data is not None and len(data)>32768:raise KnowledgeError('Embedding request exceeds its byte limit.')
        connection=http.client.HTTPConnection(self.host,self.port,timeout=min(self.timeout,max(.001,deadline-monotonic())))
        try:
            connection.request('POST' if data is not None else 'GET',path,body=data,
                headers={'Content-Type':'application/json','Accept':'application/json'})
            response=connection.getresponse()
            if response.status!=200 or response.getheader('Content-Type','').split(';')[0].strip()!='application/json':
                raise KnowledgeError('Local Ollama response is unavailable or unsupported.')
            chunks=[];size=0
            while True:
                self._check(deadline)
                if connection.sock is not None:connection.sock.settimeout(max(.001,deadline-monotonic()))
                block=response.read1(min(65536,1048577-size))
                if not block:break
                size+=len(block)
                if size>1048576:raise KnowledgeError('Ollama response exceeds its byte limit.')
                chunks.append(block)
            result=json.loads(b''.join(chunks),object_pairs_hook=_unique,
                parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if type(result) is not dict or 'error' in result:raise KnowledgeError('Local Ollama request failed safely.')
            self._check(deadline)
            return result
        except KnowledgeError:raise
        except Exception:raise KnowledgeError('Local Ollama embedding transport failed safely.') from None
        finally:connection.close()

    def _verify(self,deadline):
        tags=self._request('/api/tags',deadline).get('models')
        if type(tags) is not list:raise KnowledgeError('Invalid installed model metadata.')
        matches=[m for m in tags if type(m) is dict and m.get('name')==self.manifest.model]
        if len(matches)!=1 or matches[0].get('digest')!=self.manifest.model_revision:
            raise KnowledgeError('Pinned embedding model is absent or changed; no model was pulled.')
        show=self._request('/api/show',deadline,{'model':self.manifest.model,'verbose':False})
        if ('embedding' not in show.get('capabilities',[]) or
                show.get('model_info',{}).get('nomic-bert.embedding_length')!=self.manifest.dimensions):
            raise KnowledgeError('Installed embedding model capability or dimensions changed.')

    def _embed(self,texts,prefix):
        if type(texts) is not tuple or not 1<=len(texts)<=4:
            raise KnowledgeError('Embedding batch must contain one to four texts.')
        for text in texts:
            normalize_text(text);reject_secrets(text)
            if len(text.encode('utf-8'))>2048:raise KnowledgeError('Embedding input exceeds its byte limit.')
        if sum(len(t.encode('utf-8')) for t in texts)>8192:raise KnowledgeError('Embedding batch exceeds its byte limit.')
        self.last_metrics=None
        try:
            with self.synchronization:
                deadline=monotonic()+self.timeout
                self._verify(deadline)
                resident=self._request('/api/ps',deadline).get('models')
                if type(resident) is not list or resident:
                    raise KnowledgeError('Embedding deferred: an Ollama workload is already resident; no model was evicted.')
                started=monotonic()
                result=self._request('/api/embed',deadline,{'model':self.manifest.model,
                    'input':[prefix+t for t in texts],'truncate':False,'keep_alive':0,
                    'options':{'num_ctx':2048,'num_thread':4}})
                vectors=result.get('embeddings')
                if result.get('model')!=self.manifest.model or type(vectors) is not list or len(vectors)!=len(texts):
                    raise KnowledgeError('Embedding response identity or count is invalid.')
                vectors=tuple(normalized_vector(v,self.manifest.dimensions) for v in vectors)
                self._verify(deadline)
                after=self._request('/api/ps',deadline).get('models')
                if type(after) is not list or any(type(m) is not dict or m.get('name')!=self.manifest.model for m in after):
                    raise KnowledgeError('External Ollama workload appeared during embedding; no model was evicted.')
                def counter(name):
                    value=result.get(name)
                    return value if type(value) is int and value>=0 else None
                self.last_metrics={'wall_seconds':monotonic()-started,'load_ns':counter('load_duration'),
                    'total_ns':counter('total_duration'),'prompt_tokens':counter('prompt_eval_count')}
                return vectors
        except KnowledgeError:raise
        except Exception:raise KnowledgeError('Embedding synchronization failed safely.') from None

    def embed_documents(self,texts):return self._embed(texts,self.manifest.document_prefix)
    def embed_query(self,text):return self._embed((text,),self.manifest.query_prefix)[0]
