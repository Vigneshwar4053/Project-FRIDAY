"""Opt-in real adapters on original synthetic text; no Qwen generation.

Run only after approving pinned package/model provisioning. Uses a new private
benchmark directory beneath data/intelligence; never opens personal memory.
"""
import argparse
import json
import math
import os
from pathlib import Path
import resource
import statistics
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from friday.intelligence.models import KnowledgeSource, IndexManifest, KnowledgeError
from friday.intelligence.permissions import KnowledgeAuthorization, KnowledgeDecision
from friday.intelligence.repository import KnowledgeRepository
from friday.intelligence.chunking import TextChunker
from friday.intelligence.index import IndexingService
from friday.intelligence.retrieval import RetrievalService
from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
from friday.intelligence.chroma_index import ChromaVectorIndex
from friday.sync import create_synchronization
from friday.tools.grants import directory_descriptor

DOCUMENTS={
    'tcpip': 'TCP/IP connects hosts using network addresses. IP routes packets between networks. TCP and UDP are transport protocols carried inside IP packets.',
    'tcpudp': 'TCP provides an ordered byte stream and retransmits lost data. UDP sends independent datagrams without transport delivery guarantees. Applications decide how to handle missing UDP data.',
    'nmap': 'Authorized Nmap scanning begins with an approved target scope. Host discovery locates reachable hosts. Port scanning identifies exposed services. Results describe an observation, not permission to attack.',
    'linux': 'Linux hardening uses least privilege, timely security updates, restricted service access, and reviewed file permissions. Reduce unnecessary services and review security logs.',
    'assessment': 'Defensive vulnerability assessment records an authorized scope, identifies exposed weaknesses, evaluates business impact, prioritizes remediation, and verifies fixes. Document evidence and limitations.',
}
QUERIES=(('How does IP route packets across networks?','tcpip'),
    ('Which protocol retransmits data and offers an ordered stream?','tcpudp'),
    ('What must happen before port scanning with Nmap?','nmap'),
    ('How can Linux services and permissions be hardened?','linux'),
    ('How should defensive assessment prioritize remediation?','assessment'))


def rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    except OSError:pass
    return 0


def ollama_pids():
    result=set();parents={}
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():continue
        try:
            fields=(path/'stat').read_text().rsplit(')',1)[1].split()
            parents[int(path.name)]=int(fields[1])
            if (path/'comm').read_text().strip()=='ollama':result.add(int(path.name))
        except (OSError,ValueError,IndexError):pass
    while True:
        children={pid for pid,parent in parents.items() if parent in result}
        if children<=result:break
        result.update(children)
    return sorted(result)


def cpu_seconds(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    except (OSError,ValueError,IndexError):return 0.0


class MemorySample:
    def __init__(self,worker_pid,cancelled,baseline_python,baseline_ollama):
        self.worker_pid=worker_pid;self.stop=Event();self.samples=[]
        self.cancelled=cancelled;self.baseline_python=baseline_python;self.baseline_ollama=baseline_ollama
        self.cpu_start={pid:cpu_seconds(pid) for pid in [os.getpid(),worker_pid,*ollama_pids()]}
        self.cpu_last=dict(self.cpu_start);self.unsafe=False
        self.thread=Thread(target=self.run,daemon=True)
    def run(self):
        while not self.stop.is_set():
            sample={'parent':rss(os.getpid()),'worker':rss(self.worker_pid),
                    'ollama':sum(rss(pid) for pid in ollama_pids())}
            for pid in [os.getpid(),self.worker_pid,*ollama_pids()]:
                self.cpu_last[pid]=max(self.cpu_last.get(pid,0),cpu_seconds(pid))
            available=next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
            additional=max(0,sample['parent']-self.baseline_python)+sample['worker']+max(0,sample['ollama']-self.baseline_ollama)
            if additional>2*1024**3 or available<2*1024**3:
                self.unsafe=True;self.cancelled.set()
            self.samples.append(sample);self.stop.wait(.05)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*_):self.stop.set();self.thread.join(2)


def p95(values):return sorted(values)[math.ceil(.95*len(values))-1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-digest',required=True)
    parser.add_argument('--samples',type=int,default=50)
    args=parser.parse_args()
    if not 10<=args.samples<=100:parser.error('samples must be between 10 and 100')
    manifest=IndexManifest('nomic-embed-text:v1.5',args.model_digest,768,'search_document: ','search_query: ')
    root=Path(__file__).resolve().parents[1]/'data/intelligence/phase1c-benchmarks'/uuid4().hex
    with directory_descriptor(root,create=True):pass
    # Every input is the fixed synthetic corpus above, authorized by this task.
    auth=KnowledgeAuthorization(lambda _:KnowledgeDecision.ALLOW_ONCE)
    report={'synthetic_only':True,'manifest':manifest.generation_id,'model_digest':args.model_digest,
        'generation_calls':0,'samples':args.samples,'baseline_python_rss_bytes':rss(os.getpid())}
    gate=create_synchronization()
    cancelled=Event()
    try:
        with KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repository, \
             ChromaVectorIndex(root/'chroma',manifest,cancelled=cancelled) as index:
            provider=OllamaEmbeddingProvider(manifest,gate,timeout=60,cancelled=cancelled)
            indexer=IndexingService(repository,provider,index,auth)
            retriever=RetrievalService(repository,provider,index,auth)
            sources={key:repository.ingest(KnowledgeSource('synthetic:'+key,key,'Original synthetic benchmark'),
                text,auth,TextChunker()) for key,text in DOCUMENTS.items()}
            scope=tuple(r.source.source_id for r in sources.values())
            baseline_ollama=sum(rss(pid) for pid in ollama_pids())
            measured_started=monotonic()
            with MemorySample(index._process.pid,cancelled,report['baseline_python_rss_bytes'],baseline_ollama) as memory:
                started=monotonic();indexed=0;loads=[]
                while True:
                    count=indexer.index_batch(scope)
                    if provider.last_metrics:loads.append(provider.last_metrics)
                    if not count:break
                    indexed+=count
                report['indexing_seconds']=monotonic()-started;report['indexed_chunks']=indexed
                report['indexing_chunks_per_second']=indexed/report['indexing_seconds']
                report['embedding_batches']=loads
                latencies=[];embedding=[];search=[];correct=0;citation_valid=0
                for sample in range(args.samples):
                    query,key=QUERIES[sample%len(QUERIES)]
                    started=monotonic();vector=provider.embed_query(query);embedding.append(monotonic()-started)
                    started=monotonic();candidates=index.query(vector,scope,3);search.append(monotonic()-started)
                    latencies.append(embedding[-1]+search[-1])
                    correct+=bool(candidates and repository.evidence(candidates[0].chunk_id,scope,manifest) and
                        repository.evidence(candidates[0].chunk_id,scope,manifest)[1].source.source_id==sources[key].source.source_id)
                    evidence=retriever.retrieve(query,scope)
                    citation_valid+=bool(evidence.evidence and all(
                        repository.evidence(e.chunk.chunk_id,scope,manifest) for e in evidence.evidence))
                report.update(top1_accuracy=correct/args.samples,citation_validation_rate=citation_valid/args.samples,
                    first_retrieval_seconds=latencies[0],
                    cache_warm_reload_p50_seconds=statistics.median(latencies[1:]),
                    cache_warm_reload_p95_seconds=p95(latencies[1:]),
                    model_lifecycle='Every request uses keep_alive=0; first retrieval and subsequent filesystem-cache-warm reloads, not a resident warm model. No OS cache eviction.',
                    retrieval_p50_seconds=statistics.median(latencies),retrieval_p95_seconds=p95(latencies),
                    embedding_p50_seconds=statistics.median(embedding),embedding_p95_seconds=p95(embedding),
                    vector_search_p50_seconds=statistics.median(search),vector_search_p95_seconds=p95(search))
                old=sources['tcpip'];updated=repository.ingest(old.source,DOCUMENTS['tcpip']+' IPv4 and IPv6 use different address sizes.',auth,TextChunker())
                indexer.index_batch(scope)
                report['stale_revision_excluded']=all(e.chunk.revision_id!=old.revision_id for e in retriever.retrieve('IP packets',scope).evidence)
                repository.revoke(sources['nmap'].source.source_id,auth)
                report['revoked_source_excluded']=not retriever.retrieve('Nmap',(sources['nmap'].source.source_id,)).evidence
                report['unknown_scope_empty']=not retriever.retrieve('Unknown',(KnowledgeSource('synthetic:missing','missing','Synthetic').source_id,)).evidence
            report['peak_rss_bytes']={key:max(s[key] for s in memory.samples) for key in ('parent','worker','ollama')}
            report['peak_combined_additional_rss_bytes']=max(max(0,s['parent']-report['baseline_python_rss_bytes'])+s['worker']+max(0,s['ollama']-baseline_ollama) for s in memory.samples)
            report['measured_wall_seconds']=monotonic()-measured_started
            report['measured_cpu_seconds']=sum(max(0,value-memory.cpu_start.get(pid,0)) for pid,value in memory.cpu_last.items())
            report['average_cpu_cores']=report['measured_cpu_seconds']/report['measured_wall_seconds']
            report['resource_safety_passed']=not memory.unsafe
            report['measurement_limits']='50ms process RSS/CPU sampling can miss brief peaks and exited-runner CPU tails; worker startup is outside the sampled interval.'
            report['additional_rag_ram_bytes']=report['peak_rss_bytes']['parent']-report['baseline_python_rss_bytes']+report['peak_rss_bytes']['worker']+max(0,report['peak_rss_bytes']['ollama']-baseline_ollama)
        with ChromaVectorIndex(root/'chroma',manifest) as reopened, KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repository:
            provider=OllamaEmbeddingProvider(manifest,gate,timeout=60)
            result=RetrievalService(repository,provider,reopened,auth).retrieve('TCP reliability',(sources['tcpudp'].source.source_id,))
            report['persistent_reopen_verified']=bool(result.evidence)
    finally:gate.close()
    report['disk_bytes']=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    report['ram_target_met']=report['additional_rag_ram_bytes']<=2*1024**3
    report['latency_target_met']=report['retrieval_p95_seconds']<=1
    report['correctness_passed']=all(report[key] for key in ('stale_revision_excluded','revoked_source_excluded','unknown_scope_empty','persistent_reopen_verified')) and report['top1_accuracy']==1 and report['citation_validation_rate']==1
    from friday.intelligence.repository import private_creation
    with private_creation(),open(root/'report.json','x') as output:json.dump(report,output,indent=2)
    print(json.dumps({'report_path':str(root/'report.json'),**report},indent=2))


if __name__=='__main__':main()
