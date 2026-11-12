"""Owner-requested retrieval-only diagnostics; never generation or indexing.

Run in the existing RAG environment. Output contains metadata and sizes only.
An optional private query-vector cache permits offline replay after repairs.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import Mock

from scripts.phase1e_index import revalidate, verify_repository, inspect_vectors, require
from scripts.phase1d_dataset import ROOT
from friday.intelligence.models import IndexManifest, EvidenceBundle, RetrievalEvidence
from friday.intelligence.repository import KnowledgeRepository
from friday.intelligence.chroma_index import ChromaVectorIndex
from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
from friday.intelligence.permissions import KnowledgeAuthorization, KnowledgeDecision, KnowledgePurpose
from friday.intelligence.retrieval import RetrievalService, topic_matches
from friday.sync import PythonSemaphore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--repair', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scope, _ = revalidate()
    manifest = IndexManifest(**scope['index_manifest'])
    documents = {d['knowledge_source_id']: d for d in scope['documents']}
    sources = tuple(sorted(documents))
    questions = json.loads((ROOT/'docs/FRIDAY_PHASE1E_RETRIEVAL_QUESTIONS.json').read_text())['questions']
    questions += [{'id': 'bola_acceptance', 'question': 'Explain broken object-level authorization using the approved OWASP knowledge.',
                   'expected_source_id': questions[3]['expected_source_id']}]
    cache = json.loads(args.cache.read_text()) if args.replay else {}
    results = []
    root = ROOT/'data/intelligence/phase1e'
    # This scoped diagnostic approval follows the owner's explicit Phase 1F-R
    # request. It never becomes a grant used by the application CLI.
    auth = KnowledgeAuthorization(lambda request: KnowledgeDecision.ALLOW_ONCE
        if request.purpose is KnowledgePurpose.RETRIEVE and request.targets == sources
        else KnowledgeDecision.DENY)
    class Check:
        def check(self, *_): pass
    with closing(PythonSemaphore()) as gate, KnowledgeRepository(root/'knowledge/knowledge.sqlite3') as repo, \
            ChromaVectorIndex(root/'chroma', manifest, existing_only=True) as index:
        rows = verify_repository(repo, scope, manifest)
        require(inspect_vectors(index, repo, sources, manifest, rows, Check()) ==
                '0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca')
        provider = OllamaEmbeddingProvider(manifest, gate)
        for q in questions:
            if args.replay:
                vector = cache[q['id']]
            else:
                deadline = monotonic() + 10
                while provider._request('/api/ps', deadline).get('models'):
                    require(monotonic() < deadline)
                    sleep(.1)
                vector = provider.embed_query(q['question'])
                cache[q['id']] = vector
            candidates = index.query(vector, sources, 8)
            ranked = []
            selected = []
            for rank, c in enumerate(candidates, 1):
                exact = repo.evidence(c.chunk_id, sources, manifest)
                entry = {'rank': rank, 'chunk_id': c.chunk_id, 'distance': c.distance}
                if exact is None:
                    entry['decision'] = 'ineligible'
                else:
                    chunk, revision = exact
                    item = RetrievalEvidence('S'+str(len(selected)+1), chunk, revision.source,
                        revision.document_revision, revision.content_sha256, revision.ingestion_timestamp)
                    size = len(EvidenceBundle((item,)).serialize(compact=args.repair).encode())
                    entry.update(source_id=chunk.source_id, title=revision.source.title, evidence_bytes=size)
                    if args.repair and not topic_matches(q['question'], chunk):
                        entry['decision'] = 'topic_mismatch'
                    elif len(selected) >= 3:
                        entry['decision'] = 'evidence_limit'
                    elif len(EvidenceBundle(tuple(selected+[item])).serialize(compact=args.repair).encode()) > 2048:
                        entry['decision'] = 'byte_budget'
                    else:
                        entry['decision'] = 'accepted'
                        selected.append(item)
                ranked.append(entry)
            cached = Mock(manifest=manifest)
            cached.embed_query.return_value = vector
            bundle = RetrievalService(repo, cached, index, auth, compact_evidence=args.repair,
                require_topic_match=args.repair).retrieve(q['question'], sources)
            results.append({'id': q['id'], 'expected_source_id': q['expected_source_id'], 'candidates': ranked,
                'selected': [{'source_id': e.chunk.source_id, 'chunk_id': e.chunk.chunk_id} for e in bundle.evidence],
                'empty_reason': bundle.empty_reason})
        require(inspect_vectors(index, repo, sources, manifest, rows, Check()) ==
                '0dd87879a2e4b35f8653cfbd76d0b90d378e1a57b8143041d9a368d928650eca')
    if not args.replay:
        fd = os.open(args.cache, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream: json.dump(cache, stream)
    args.output.write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
