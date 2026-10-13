"""Optional explicit-vector Chroma in an owned, network-denied worker."""
from dataclasses import asdict
import ctypes
import errno
import importlib.metadata
import math
import multiprocessing
import os
from pathlib import Path
import platform
import re
import stat
from threading import Event, Lock
from time import monotonic

from friday.intelligence.models import IndexManifest, KnowledgeError, fingerprint
from friday.intelligence.embeddings import normalized_vector
from friday.intelligence.index import VectorRecord, VectorCandidate
from friday.intelligence.repository import scope_ids, private_creation
from friday.tools.grants import directory_descriptor, lexical_path

CHROMA_VERSION='1.5.9'


def deny_worker_network():
    """Linux x86-64 seccomp: deny connect/bind in Python and native threads.

    Pipes remain usable. Failure to install the filter prevents Chroma import.
    """
    if platform.system()!='Linux' or platform.machine()!='x86_64':raise RuntimeError('Unsupported isolation platform')
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    # Check architecture before syscall numbers. Kill on a mismatched ABI.
    instructions=[(0x20,0,0,4),(0x15,1,0,0xC000003E),(0x06,0,0,0x80000000),
        (0x20,0,0,0),(0x35,0,1,0x40000000),(0x06,0,0,0x80000000)]
    # No new sockets or datagram/raw sends; also deny io_uring network bypasses.
    for syscall in (41,42,44,46,49,307,425,426,427):
        instructions.extend([(0x15,0,1,syscall),(0x06,0,0,0x00050000|errno.EPERM)])
    instructions.append((0x06,0,0,0x7FFF0000))
    filters=(Filter*len(instructions))(*(Filter(*i) for i in instructions))
    program=Program(len(filters),filters);libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(22,2,ctypes.byref(program),0,0)!=0:
        raise RuntimeError('Network isolation unavailable')


def _private_tree(path):
    """Inspect only the adapter's exact private tree, never source directories."""
    for folder,dirs,files in os.walk(path,followlinks=False):
        for name in [folder,*[str(Path(folder)/n) for n in dirs+files]]:
            if Path(name).name=='.env' or Path(name).name.startswith('.env.'):
                raise RuntimeError('Environment files are forbidden in vector storage')
            info=os.lstat(name)
            if (info.st_uid!=os.getuid() or stat.S_ISLNK(info.st_mode) or
                    not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or
                    stat.S_IMODE(info.st_mode)!=(0o700 if stat.S_ISDIR(info.st_mode) else 0o600) or
                    (stat.S_ISREG(info.st_mode) and info.st_nlink!=1)):
                raise RuntimeError('Unsafe vector storage')


def _worker(channel,path,manifest_values):
    client=None
    try:
        # No inherited cloud credentials, telemetry endpoints or loader settings.
        os.environ.clear()
        os.environ.update({'HOME':path,'XDG_CACHE_HOME':path+'/cache','HF_HUB_OFFLINE':'1',
            'TRANSFORMERS_OFFLINE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2',
            'RAYON_NUM_THREADS':'2','ANONYMIZED_TELEMETRY':'False'})
        os.umask(0o077)
        os.chdir(path)
        with open(os.devnull,'w') as null:
            os.dup2(null.fileno(),1);os.dup2(null.fileno(),2)
        deny_worker_network()
        _private_tree(path)
        if importlib.metadata.version('chromadb')!=CHROMA_VERSION:raise RuntimeError('Chroma version changed')
        chromadb = importlib.import_module('chromadb')
        chromadb_config = importlib.import_module('chromadb.config')
        Settings = chromadb_config.Settings
        manifest=IndexManifest(**manifest_values)
        client=chromadb.PersistentClient(path=path,settings=Settings(_env_file=None,anonymized_telemetry=False,allow_reset=False))
        name='friday_'+manifest.generation_id.removeprefix('idx_')[:48]
        expected={'friday_manifest':fingerprint(asdict(manifest)),'hnsw:space':'cosine'}
        try:collection=client.get_collection(name,embedding_function=None)
        except chromadb.errors.NotFoundError:
            collection=client.create_collection(name,embedding_function=None,metadata=expected,
                configuration={'hnsw':{'space':'cosine','num_threads':2}})
        if collection.metadata!=expected:raise RuntimeError('Index manifest changed')
        if collection.configuration.get('hnsw',{}).get('space')!='cosine':raise RuntimeError('Index distance changed')
        _private_tree(path)
        channel.send(('ready',None))
        while True:
            operation,payload=channel.recv()
            if operation=='close':break
            if operation=='upsert':
                collection.upsert(ids=[r['chunk_id'] for r in payload],embeddings=[list(r['vector']) for r in payload],
                    metadatas=[{k:r[k] for k in ('source_id','revision_id','content_sha256')} for r in payload])
                result=None
            elif operation=='delete':collection.delete(ids=payload);result=None
            elif operation=='query':
                vector,scope,limit=payload
                where={'source_id':{'$in':list(scope)}}
                response=collection.query(query_embeddings=[list(vector)],n_results=limit,where=where,include=['distances'])
                result=list(zip(response['ids'][0],response['distances'][0]))
            elif operation=='count':result=collection.count()
            elif operation=='inspect':
                response=collection.get(ids=payload,include=['embeddings','metadatas'])
                result=[{'chunk_id':identifier,**metadata,'vector':[float(v) for v in vector]}
                    for identifier,metadata,vector in zip(response['ids'],response['metadatas'],response['embeddings'],strict=True)]
            else:raise RuntimeError('Invalid worker operation')
            _private_tree(path)
            channel.send(('ok',result))
    except BaseException:
        try:channel.send(('error',None))
        except (OSError,EOFError):pass
    finally:
        if client is not None:
            try:client._system.stop()
            except Exception:pass
        channel.close()


class ChromaVectorIndex:
    """Owned worker enforces hard waits/cancellation and cannot use networking.

    Local paths are explicit. No implicit embeddings, SDK loaders or document text
    are sent to Chroma. SQLite remains authoritative for consent and revisions.
    """
    def __init__(self,path,manifest,*,timeout=30,cancelled=None):
        if type(manifest) is not IndexManifest:raise KnowledgeError('Typed Chroma manifest required.')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=60:
            raise KnowledgeError('Invalid Chroma timeout.')
        path=lexical_path(str(path))
        if not path.is_absolute():raise KnowledgeError('Explicit absolute vector storage is required.')
        self.manifest=manifest;self.timeout=timeout;self.cancelled=cancelled if cancelled is not None else Event()
        self._lock=Lock();self._closed=False;self._process=None;self._channel=None
        try:
            with directory_descriptor(path,create=True) as fd:
                info=os.fstat(fd)
                if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
                    raise KnowledgeError('Vector storage must be private and owner-controlled.')
            context=multiprocessing.get_context('spawn')
            parent,child=context.Pipe();self._channel=parent
            self._process=context.Process(target=_worker,args=(child,str(path),asdict(manifest)),daemon=False)
            try:self._process.start()
            finally:child.close()
            status,_=self._receive(monotonic()+timeout)
            if status!='ready':raise KnowledgeError('Optional Chroma is unavailable, incompatible or unsafe.')
        except KnowledgeError:
            self.close();raise
        except Exception:
            self.close();raise KnowledgeError('Chroma worker startup failed safely.') from None

    def _receive(self,deadline):
        while True:
            if self.cancelled.is_set():raise KnowledgeError('Chroma operation cancelled.')
            if monotonic()>=deadline:raise KnowledgeError('Chroma operation exceeded its deadline; state is uncertain.')
            if self._channel.poll(min(.05,max(.001,deadline-monotonic()))):return self._channel.recv()
            if not self._process.is_alive():raise KnowledgeError('Chroma worker ended unexpectedly.')

    def _rpc(self,operation,payload):
        if not self._lock.acquire(blocking=False):raise KnowledgeError('Chroma operation already active.')
        try:
            if self._closed:raise KnowledgeError('Chroma index is closed.')
            if self.cancelled.is_set():raise KnowledgeError('Chroma operation cancelled.')
            self._channel.send((operation,payload))
            status,result=self._receive(monotonic()+self.timeout)
            if status!='ok':raise KnowledgeError('Chroma operation failed safely.')
            return result
        except Exception:
            self.close();raise KnowledgeError('Chroma operation failed, timed out or was cancelled; reopen before retry.') from None
        finally:self._lock.release()

    def upsert(self,records):
        if type(records) is not tuple or not 1<=len(records)<=4:raise KnowledgeError('Chroma batch exceeds its bound.')
        for record in records:
            if type(record) is not VectorRecord:raise KnowledgeError('Typed vector record required.')
            for value,prefix in ((record.chunk_id,'chk_'),(record.source_id,'src_'),(record.revision_id,'rev_'),(record.content_sha256,'')):
                if type(value) is not str or not re.fullmatch(prefix+r'[0-9a-f]{64}',value):raise KnowledgeError('Invalid vector provenance.')
            normalized_vector(record.vector,self.manifest.dimensions)
        self._rpc('upsert',[{**asdict(r),'vector':normalized_vector(r.vector,self.manifest.dimensions)} for r in records])

    def delete(self,chunk_ids):
        if type(chunk_ids) is not tuple or not 1<=len(chunk_ids)<=100 or any(
                type(i) is not str or not re.fullmatch(r'chk_[0-9a-f]{64}',i) for i in chunk_ids):
            raise KnowledgeError('Invalid bounded vector deletion.')
        self._rpc('delete',list(chunk_ids))

    def query(self,vector,scope,limit):
        scope=scope_ids(scope)
        if type(limit) is not int or not 1<=limit<=8:raise KnowledgeError('Invalid Chroma candidate limit.')
        vector=normalized_vector(vector,self.manifest.dimensions)
        rows=self._rpc('query',(vector,scope,limit))
        if type(rows) is not list or len(rows)>limit:raise KnowledgeError('Invalid Chroma candidate response.')
        result=[]
        for row in rows:
            if type(row) not in (list,tuple) or len(row)!=2:raise KnowledgeError('Invalid Chroma candidate shape.')
            chunk_id,distance=row
            if (type(chunk_id) is not str or not re.fullmatch(r'chk_[0-9a-f]{64}',chunk_id) or
                    type(distance) not in (float,int) or not math.isfinite(distance) or not -.000001<=distance<=2.000001):
                raise KnowledgeError('Invalid Chroma candidate values.')
            result.append(VectorCandidate(chunk_id,max(0.,min(2.,distance))))
        return tuple(result)

    def count(self):
        value=self._rpc('count',None)
        if type(value) is not int or not 0<=value<=10000:
            raise KnowledgeError('Invalid Chroma record count.')
        return value

    def inspect(self,chunk_ids):
        """Bounded explicit-vector integrity inspection; no text or embeddings."""
        if (type(chunk_ids) is not tuple or not 1<=len(chunk_ids)<=4 or len(set(chunk_ids))!=len(chunk_ids) or
                any(type(i) is not str or not re.fullmatch(r'chk_[0-9a-f]{64}',i) for i in chunk_ids)):
            raise KnowledgeError('Invalid bounded vector inspection.')
        rows=self._rpc('inspect',list(chunk_ids))
        if type(rows) is not list or len(rows)>len(chunk_ids):raise KnowledgeError('Invalid vector inspection response.')
        result=[];seen=set()
        for row in rows:
            if type(row) is not dict or set(row)!={'chunk_id','source_id','revision_id','content_sha256','vector'}:
                raise KnowledgeError('Invalid vector inspection metadata.')
            for key,prefix in (('chunk_id','chk_'),('source_id','src_'),('revision_id','rev_'),('content_sha256','')):
                if type(row[key]) is not str or not re.fullmatch(prefix+r'[0-9a-f]{64}',row[key]):
                    raise KnowledgeError('Invalid inspected vector provenance.')
            if row['chunk_id'] not in chunk_ids or row['chunk_id'] in seen:
                raise KnowledgeError('Foreign or duplicate inspected vector.')
            seen.add(row['chunk_id'])
            vector=tuple(row['vector']) if type(row['vector']) in (tuple,list) else ()
            normalized_vector(vector,self.manifest.dimensions)
            if abs(sum(v*v for v in vector)-1)>1e-4:raise KnowledgeError('Stored vector normalization changed.')
            result.append(VectorRecord(row['chunk_id'],row['source_id'],row['revision_id'],row['content_sha256'],vector))
        return tuple(result)

    def close(self):
        if self._closed:return
        self._closed=True
        process=self._process
        if process is not None and process.pid is not None:
            if process.is_alive():
                try:self._channel.send(('close',None))
                except (OSError,EOFError):pass
                process.join(.5)
            if process.is_alive():process.terminate();process.join(1)
            if process.is_alive():process.kill();process.join(1)
            process.close()
        if self._channel is not None:self._channel.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
