"""Evidence only: no generation, tools, memory writes, speech or network imports."""
import math
import re
from time import monotonic
from friday.intelligence.models import (KnowledgeError, RetrievalEvidence, EvidenceBundle,
    bounded_text, fingerprint)
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose
from friday.intelligence.ingestion import reject_secrets
from friday.intelligence.repository import scope_ids
from friday.intelligence.embeddings import normalized_vector
from friday.intelligence.index import check_backends, VectorCandidate


def topic_matches(query, chunk):
    """Narrow necessary-term guard; not a semantic support classifier.

    Object authorization requires both an object and access-control context.
    Do not infer topic relevance from a document title or model source claims.
    Other topics retain existing vector ordering until separately evaluated.
    """
    object_query = (re.search(r'\b(?:bola|idor)\b', query, re.I) or
        (re.search(r'\bobjects?\b', query, re.I) and
         re.search(r'authori[sz]|access|permissions?', query, re.I)))
    if not object_query:
        return True
    return bool(re.search(r'\bobjects?\b|\bidor\b|\bbola\b', chunk.text, re.I) and
                re.search(r'authori[sz]|access\s+control|permissions?', chunk.text, re.I))


class RetrievalService:
    def __init__(self,repository,provider,index,authorization,*,candidate_limit=8,evidence_limit=3,evidence_bytes=2048,
                 compact_evidence=False, require_topic_match=False):
        if (type(candidate_limit) is not int or not 1<=candidate_limit<=8 or
                type(evidence_limit) is not int or not 1<=evidence_limit<=3 or
                type(evidence_bytes) is not int or not 2<=evidence_bytes<=2048):
            raise KnowledgeError('Invalid retrieval budgets.')
        if type(compact_evidence) is not bool or type(require_topic_match) is not bool:
            raise KnowledgeError('Invalid evidence selection policy.')
        self.repository=repository;self.provider=provider;self.index=index;self.authorization=authorization
        self.candidate_limit=candidate_limit;self.evidence_limit=evidence_limit;self.evidence_bytes=evidence_bytes
        self.compact_evidence=compact_evidence;self.require_topic_match=require_topic_match
        self.last_metrics = None

    def retrieve(self,query,scope):
        self.last_metrics = None
        bounded_text(query,2048);reject_secrets(query)
        scope=scope_ids(scope);manifest=check_backends(self.provider,self.index)
        snapshot=self.repository.snapshot(scope)
        request=AuthorizationRequest(KnowledgePurpose.RETRIEVE,scope,fingerprint([snapshot,manifest.generation_id,query]))
        self.authorization.require(request)
        if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during retrieval approval.', category='source_changed')
        if not self.repository.has_indexed(scope,manifest):return EvidenceBundle(empty_reason='no_indexed_sources')
        try:
            started = monotonic()
            vector=normalized_vector(self.provider.embed_query(query),manifest.dimensions)
            embedding_seconds = monotonic() - started
            started = monotonic()
            candidates=self.index.query(vector,scope,self.candidate_limit)
            retrieval_seconds = monotonic() - started
        except KnowledgeError:raise
        except Exception:raise KnowledgeError('Knowledge retrieval failed safely.') from None
        if type(candidates) not in (tuple,list) or len(candidates)>self.candidate_limit:
            raise KnowledgeError('Index exceeded its candidate contract.')
        started = monotonic()
        evidence=[];seen=set();relevant=0
        for candidate in candidates:
            if (type(candidate) is not VectorCandidate or type(candidate.chunk_id) is not str or
                    not re.fullmatch(r'chk_[0-9a-f]{64}',candidate.chunk_id) or
                    type(candidate.distance) not in (int,float) or not math.isfinite(candidate.distance) or
                    not 0<=candidate.distance<=2):raise KnowledgeError('Index returned an invalid candidate.')
            if candidate.chunk_id in seen:continue
            seen.add(candidate.chunk_id)
            verified=self.repository.evidence(candidate.chunk_id,scope,manifest)
            if verified is None:continue
            chunk,revision=verified
            if self.require_topic_match and not topic_matches(query, chunk):continue
            relevant+=1
            item=RetrievalEvidence('S'+str(len(evidence)+1),chunk,revision.source,revision.document_revision,
                revision.content_sha256,revision.ingestion_timestamp)
            if len(EvidenceBundle(tuple(evidence+[item])).serialize(compact=self.compact_evidence).encode('utf-8'))>self.evidence_bytes:continue
            evidence.append(item)
            if len(evidence)>=self.evidence_limit:break
        if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during retrieval.', category='source_changed')
        self.last_metrics = {'embedding_seconds': embedding_seconds,
            'chroma_retrieval_seconds': retrieval_seconds,
            'evidence_verification_seconds': monotonic() - started}
        return EvidenceBundle(tuple(evidence),None if evidence else
            'no_relevant_evidence' if self.require_topic_match and not relevant else 'no_evidence_within_budget')
