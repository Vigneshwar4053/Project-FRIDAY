"""Evidence only: no generation, tools, memory writes, speech or network imports."""
import math
import re
from friday.intelligence.models import (KnowledgeError, RetrievalEvidence, EvidenceBundle,
    bounded_text, fingerprint)
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose
from friday.intelligence.ingestion import reject_secrets
from friday.intelligence.repository import scope_ids
from friday.intelligence.embeddings import normalized_vector
from friday.intelligence.index import check_backends, VectorCandidate


class RetrievalService:
    def __init__(self,repository,provider,index,authorization,*,candidate_limit=8,evidence_limit=3,evidence_bytes=2048):
        if (type(candidate_limit) is not int or not 1<=candidate_limit<=8 or
                type(evidence_limit) is not int or not 1<=evidence_limit<=3 or
                type(evidence_bytes) is not int or not 2<=evidence_bytes<=2048):
            raise KnowledgeError('Invalid retrieval budgets.')
        self.repository=repository;self.provider=provider;self.index=index;self.authorization=authorization
        self.candidate_limit=candidate_limit;self.evidence_limit=evidence_limit;self.evidence_bytes=evidence_bytes

    def retrieve(self,query,scope):
        bounded_text(query,2048);reject_secrets(query)
        scope=scope_ids(scope);manifest=check_backends(self.provider,self.index)
        snapshot=self.repository.snapshot(scope)
        request=AuthorizationRequest(KnowledgePurpose.RETRIEVE,scope,fingerprint([snapshot,manifest.generation_id,query]))
        self.authorization.require(request)
        if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during retrieval approval.')
        if not self.repository.has_indexed(scope,manifest):return EvidenceBundle(empty_reason='no_indexed_sources')
        try:
            vector=normalized_vector(self.provider.embed_query(query),manifest.dimensions)
            candidates=self.index.query(vector,scope,self.candidate_limit)
        except KnowledgeError:raise
        except Exception:raise KnowledgeError('Knowledge retrieval failed safely.') from None
        if type(candidates) not in (tuple,list) or len(candidates)>self.candidate_limit:
            raise KnowledgeError('Index exceeded its candidate contract.')
        evidence=[];seen=set()
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
            item=RetrievalEvidence('S'+str(len(evidence)+1),chunk,revision.source,revision.document_revision,
                revision.content_sha256,revision.ingestion_timestamp)
            if len(EvidenceBundle(tuple(evidence+[item])).serialize().encode('utf-8'))>self.evidence_bytes:continue
            evidence.append(item)
            if len(evidence)>=self.evidence_limit:break
        if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during retrieval.')
        return EvidenceBundle(tuple(evidence),None if evidence else 'no_evidence_within_budget')
