"""Read-only Chroma transport under the existing pinned RAG Python environment."""
import os
import secrets
import subprocess
from threading import Event,Lock
from time import monotonic

from friday.intelligence.chroma_index import ChromaVectorIndex
from friday.intelligence.models import IndexManifest,KnowledgeError
from friday.tools.grants import directory_descriptor,lexical_path
from .chroma_protocol import JsonPipe
from .rag_runtime import ROOT,EXECUTABLE,ENTRYPOINT,runtime_status

class CompatibleChromaIndex(ChromaVectorIndex):
    """Reuse original vector/result validators; expose count/inspect/query only.

    No question, document, prompt, answer, credential or authorization decision is
    sent to this worker. All model calls and exact knowledge permissions stay in
    the parent's original RAG orchestrator and synchronization gate.
    """
    def __init__(self,path,manifest,*,timeout=30,cancelled=None,existing_only=True):
        self._closed=False;self._process=None;self._channel=None;self._lock=Lock();self._sequence=0
        self.cancelled=cancelled if cancelled is not None else Event()
        self.manifest=manifest;self.timeout=timeout
        self._deadline=monotonic()+600
        if type(manifest) is not IndexManifest or existing_only is not True or type(timeout) not in (int,float) or not 1<=timeout<=60:
            raise KnowledgeError('Exact existing-only vector runtime required.',category='backend_failure')
        expected=ROOT/'data/intelligence/phase1e/chroma'
        if lexical_path(str(path))!=expected:
            raise KnowledgeError('Only the existing approved vector directory is supported.',category='backend_failure')
        if not runtime_status()['available'] or not ENTRYPOINT.is_file():
            raise KnowledgeError('Compatible existing RAG runtime unavailable.',category='backend_failure')
        # The manifest must be the original pinned corpus generation, not IPC input.
        from .rag_runtime import approved_manifest
        if manifest!=approved_manifest():raise KnowledgeError('Vector generation differs from approved scope.')
        if self.cancelled.is_set():raise KnowledgeError('Vector worker cancelled.',category='cancelled')
        try:
            with directory_descriptor(expected) as fd:
                info=os.fstat(fd)
                if info.st_uid!=os.getuid() or info.st_mode&0o777!=0o700:raise ValueError()
            if not (expected/'chroma.sqlite3').is_file():raise ValueError()
            to_child_read,to_child_write=os.pipe()
            from_child_read,from_child_write=os.pipe()
            nonce=secrets.token_hex(32)
            self._channel=JsonPipe(from_child_read,to_child_write,nonce)
            try:
                # -I ignores user site/PYTHONPATH; fixed script inserts this checkout only.
                self._process=subprocess.Popen([str(EXECUTABLE),'-I','-B',str(ENTRYPOINT),
                    '--reader',str(to_child_read),'--writer',str(from_child_write),'--nonce',nonce],
                    shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    close_fds=True,pass_fds=(to_child_read,from_child_write),cwd=str(ROOT),
                    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                         'ANONYMIZED_TELEMETRY':'False','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2'})
            finally:
                os.close(to_child_read);os.close(from_child_write)
            status,payload=self._receive(monotonic()+timeout)
            if status!='ready' or payload is not None:raise ValueError()
        except KnowledgeError:
            self.close()
            raise
        except Exception:
            self.close()
            raise KnowledgeError('Existing compatible vector worker could not start safely.',category='backend_failure') from None

    def _receive(self,deadline):
        try:
            message=self._channel.read(min(deadline,self._deadline),self.cancelled)
            if message['sequence']!=self._sequence or message['kind'] not in ('ready','ok','error'):
                raise ValueError()
            return message['kind'],message['payload']
        except InterruptedError:raise KnowledgeError('Vector worker cancelled.',category='cancelled') from None
        except TimeoutError:raise KnowledgeError('Vector worker deadline exceeded.',category='vector_timeout') from None
        except Exception:raise KnowledgeError('Vector worker protocol or process failed.',category='backend_failure') from None

    def _rpc(self,operation,payload):
        if operation not in ('count','inspect','query'):
            raise KnowledgeError('Mutation is not supported by the desktop vector bridge.')
        if not self._lock.acquire(blocking=False):raise KnowledgeError('Vector operation already active.')
        try:
            if self._closed:raise KnowledgeError('Vector worker closed.')
            if self.cancelled.is_set():raise KnowledgeError('Vector worker cancelled.',category='cancelled')
            self._sequence+=1
            deadline=min(monotonic()+self.timeout,self._deadline)
            self._channel.write(self._sequence,operation,payload,deadline=deadline)
            status,result=self._receive(deadline)
            if status!='ok':raise KnowledgeError('Existing vector verification failed.',category='backend_failure')
            return result
        except KnowledgeError:
            self.close();raise
        except TimeoutError:
            self.close();raise KnowledgeError('Vector IPC deadline exceeded.',category='vector_timeout') from None
        except Exception:
            self.close();raise KnowledgeError('Vector IPC failed safely.',category='backend_failure') from None
        finally:self._lock.release()

    def close(self):
        if self._closed:return
        self._closed=True
        process=self._process
        if process is not None:
            if process.poll() is None and self._channel is not None:
                try:
                    self._sequence+=1
                    self._channel.write(self._sequence,'close',None,deadline=monotonic()+.2)
                except Exception:pass
            try:process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
        if self._channel is not None:self._channel.close()
