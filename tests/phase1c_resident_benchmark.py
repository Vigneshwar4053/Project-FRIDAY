"""Synthetic-only resident warm measurement with explicit owned-model cleanup.

This experiment does not change the runtime provider's ephemeral policy.
It requires an empty resident-model list, holds the benchmark synchronization
gate, verifies the exact model, and unloads only the model this experiment owns.
"""
import argparse
import json
from pathlib import Path
import statistics
from threading import Event
from time import monotonic

from phase1c_rag_benchmark import MemorySample, QUERIES, rss, ollama_pids, p95
from friday.intelligence.chroma_index import ChromaVectorIndex
from friday.intelligence.embeddings import normalized_vector
from friday.intelligence.models import IndexManifest, KnowledgeSource
from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
from friday.intelligence.repository import KnowledgeRepository
from friday.sync import create_synchronization


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-root',required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    root=Path(args.report_root)
    if root.parent!=project/'data/intelligence/phase1c-benchmarks' or root.is_symlink():
        raise RuntimeError('Only the exact synthetic benchmark directory is allowed')
    previous=json.loads((root/'report.json').read_text())
    if not previous['synthetic_only'] or not previous['correctness_passed']:
        raise RuntimeError('Synthetic benchmark prerequisite failed')
    manifest=IndexManifest('nomic-embed-text:v1.5',previous['model_digest'],768,'search_document: ','search_query: ')
    scope=tuple(KnowledgeSource('synthetic:'+key,key,'Original synthetic benchmark').source_id
                for key in ('tcpip','tcpudp','linux','assessment'))
    gate=create_synchronization();cancelled=Event();owned=False
    baseline_python=rss(__import__('os').getpid())
    try:
        with ChromaVectorIndex(root/'chroma',manifest,cancelled=cancelled) as index, KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repository:
            provider=OllamaEmbeddingProvider(manifest,gate,timeout=60,cancelled=cancelled)
            with gate:
                provider._verify(monotonic()+60)
                if provider._request('/api/ps',monotonic()+60)['models']:
                    raise RuntimeError('Resident workload exists; no model evicted')
                baseline_ollama=sum(rss(pid) for pid in ollama_pids())
                started=monotonic();latencies=[];embed_latencies=[];search_latencies=[];loads=[];correct=0
                with MemorySample(index._process.pid,cancelled,baseline_python,baseline_ollama) as memory:
                    try:
                        for query,key in [QUERIES[1]]*21:
                            provider._verify(monotonic()+60)
                            resident=provider._request('/api/ps',monotonic()+60)['models']
                            if any(m.get('name')!=manifest.model or m.get('digest')!=manifest.model_revision for m in resident):
                                raise RuntimeError('External workload appeared; stop')
                            request_started=monotonic();owned=True
                            response=provider._request('/api/embed',monotonic()+60,{
                                'model':manifest.model,'input':[manifest.query_prefix+query],
                                'truncate':False,'keep_alive':'30s','options':{'num_ctx':2048,'num_thread':4}})
                            if response.get('model')!=manifest.model or len(response['embeddings'])!=1:
                                raise RuntimeError('Embedding response identity mismatch')
                            vector=normalized_vector(response['embeddings'][0],768)
                            embed_latencies.append(monotonic()-request_started)
                            search_started=monotonic();candidates=index.query(vector,scope,3)
                            search_latencies.append(monotonic()-search_started)
                            latencies.append(embed_latencies[-1]+search_latencies[-1]);loads.append(response.get('load_duration'))
                            evidence=repository.evidence(candidates[0].chunk_id,scope,manifest) if candidates else None
                            correct+=bool(evidence and evidence[1].source.source_id==KnowledgeSource('synthetic:'+key,key,'Original synthetic benchmark').source_id)
                    finally:
                        if owned:
                            # Exact tag/digest still verified before unloading only our own model.
                            provider._verify(monotonic()+60)
                            provider._request('/api/embed',monotonic()+60,{'model':manifest.model,'input':[],'keep_alive':0})
                report={'synthetic_only':True,'model_digest':manifest.model_revision,'samples':20,
                        'query':'TCP ordered-stream question repeated; small lifecycle microbenchmark',
                        'cold_model_retrieval_seconds':latencies[0],
                        'resident_warm_retrieval_p50_seconds':statistics.median(latencies[1:]),
                        'resident_warm_retrieval_p95_seconds':p95(latencies[1:]),
                        'resident_warm_embedding_p50_seconds':statistics.median(embed_latencies[1:]),
                        'resident_warm_search_p50_seconds':statistics.median(search_latencies[1:]),
                        'top1_accuracy':correct/21,'load_durations_ns':loads,
                        'peak_additional_rss_bytes':max(max(0,s['parent']-baseline_python)+s['worker']+max(0,s['ollama']-baseline_ollama) for s in memory.samples),
                        'cpu_seconds':sum(max(0,v-memory.cpu_start.get(pid,0)) for pid,v in memory.cpu_last.items()),
                        'wall_seconds':monotonic()-started,'resource_safety_passed':not memory.unsafe,
                        'only_owned_model_unloaded':True,'runtime_provider_unchanged':True}
    finally:
        gate.close()
    with (root/'resident-report.json').open('x') as stream:json.dump(report,stream,indent=2)
    (root/'resident-report.json').chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
