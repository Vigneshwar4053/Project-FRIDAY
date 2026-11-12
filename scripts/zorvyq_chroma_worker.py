"""Fixed read-only desktop vector worker. No model calls or knowledge text IPC."""
from pathlib import Path
import sys
# -I intentionally ignores PYTHONPATH. Only this fixed checkout is inserted.
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from zorvyq.chroma_protocol import JsonPipe
from zorvyq.rag_runtime import approved_scope,approved_manifest,VERSION

class ReadOnlyChannel:
    def __init__(self,pipe,manifest,sources):
        from time import monotonic
        self.pipe=pipe;self.manifest=manifest;self.sources=set(sources);self.sequence=0
        self.deadline=monotonic()+600
    def send(self,value):
        kind,payload=value
        if kind not in ('ready','ok','error'):raise ValueError('Invalid worker response')
        self.pipe.write(self.sequence,kind,payload)
    def recv(self):
        from time import monotonic
        import re
        from friday.intelligence.embeddings import normalized_vector
        from friday.intelligence.repository import scope_ids
        frame=self.pipe.read(self.deadline)
        if frame['sequence']!=self.sequence+1:raise ValueError('Stale vector request')
        self.sequence=frame['sequence'];operation=frame['kind'];payload=frame['payload']
        if operation in ('count','close'):
            if payload is not None:raise ValueError('Unexpected operation payload')
        elif operation=='inspect':
            if (type(payload) is not list or not 1<=len(payload)<=4 or
                any(type(item) is not str or not re.fullmatch(r'chk_[0-9a-f]{64}',item) for item in payload) or
                len(set(payload))!=len(payload)):
                raise ValueError('Invalid bounded inspection')
        elif operation=='query':
            if type(payload) is not list or len(payload)!=3:raise ValueError('Invalid vector query')
            vector,scope,limit=payload
            if type(vector) is not list or type(scope) is not list or type(limit) is not int or not 1<=limit<=8:
                raise ValueError('Invalid vector query')
            normalized_vector(vector,self.manifest.dimensions)
            if not set(scope_ids(tuple(scope)))<=self.sources:raise ValueError('Foreign query scope')
        else:raise ValueError('Only read-only vector operations are supported')
        return operation,payload
    def close(self):self.pipe.close()


def limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--reader',type=int);parser.add_argument('--writer',type=int);parser.add_argument('--nonce')
    parser.add_argument('--probe',action='store_true')
    args=parser.parse_args()
    limits()
    if args.probe:
        # Import compatibility only. Never instantiate PersistentClient or open
        # the real index during environment verification.
        import os,json,importlib.metadata,tempfile
        from friday.intelligence.chroma_index import deny_worker_network
        os.environ.clear()
        os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False',
                           'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2'})
        with tempfile.TemporaryDirectory(prefix='zorvyq-chroma-probe-') as temporary:
            os.chdir(temporary);deny_worker_network()
            import chromadb
            from chromadb.config import Settings
            assert importlib.metadata.version('chromadb')==VERSION
            assert Settings(_env_file=None,anonymized_telemetry=False,allow_reset=False,migrations='validate').migrations=='validate'
            print(json.dumps({'version':VERSION,'import_compatible':True,'index_opened':False,'network':'denied'}))
        return 0
    if args.reader is None or args.writer is None or min(args.reader,args.writer)<3 or args.reader==args.writer:
        parser.error('Private inherited pipe descriptors required')
    pipe=JsonPipe(args.reader,args.writer,args.nonce)
    try:
        manifest=approved_manifest();scope=approved_scope()
        channel=ReadOnlyChannel(pipe,manifest,(d['knowledge_source_id'] for d in scope['documents']))
        from friday.intelligence.chroma_index import _worker
        _worker(channel,str(ROOT/'data/intelligence/phase1e/chroma'),__import__('dataclasses').asdict(manifest),existing_only=True,read_only=True)
    except BaseException:
        try:pipe.write(0,'error',None)
        except Exception:pass
    finally:pipe.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
