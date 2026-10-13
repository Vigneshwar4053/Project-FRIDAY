"""Explicit bounded indexing; vector implementations are constructor-injected."""
from dataclasses import dataclass
from typing import Protocol
from friday.intelligence.models import IndexManifest, KnowledgeError, fingerprint
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose
from friday.intelligence.repository import scope_ids
from friday.intelligence.embeddings import normalized_vector


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    source_id: str
    revision_id: str
    content_sha256: str
    vector: tuple[float,...]


@dataclass(frozen=True)
class VectorCandidate:
    chunk_id: str
    distance: float


class VectorIndex(Protocol):
    manifest: IndexManifest
    def upsert(self,records: tuple[VectorRecord,...]) -> None: ...
    def delete(self,chunk_ids: tuple[str,...]) -> None: ...
    def query(self,vector: tuple[float,...],scope: tuple[str,...],limit: int) -> tuple[VectorCandidate,...]: ...


def check_backends(provider,index):
    if type(provider.manifest) is not IndexManifest or provider.manifest!=index.manifest:
        raise KnowledgeError('Embedding and index manifests do not match.')
    return provider.manifest


class IndexingService:
    def __init__(self,repository,provider,index,authorization):
        self.repository=repository;self.provider=provider;self.index=index;self.authorization=authorization

    def index_batch(self,scope):
        scope=scope_ids(scope);manifest=check_backends(self.provider,self.index)
        snapshot=self.repository.snapshot(scope)
        request=AuthorizationRequest(KnowledgePurpose.INDEX,scope,fingerprint([snapshot,manifest.generation_id]))
        self.authorization.require(request)
        if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during indexing approval.')
        chunks=self.repository.pending_chunks(scope,manifest,4)
        if not chunks:return 0
        if sum(len(c.text.encode('utf-8')) for c in chunks)>6144:raise KnowledgeError('Embedding batch is oversized.')
        # Verify authoritative text/hash/provenance before any embedding call.
        for chunk in chunks:
            from friday.intelligence.models import digest
            if digest(chunk.text)!=chunk.content_sha256:raise KnowledgeError('Chunk integrity failed.')
        try:
            vectors=self.provider.embed_documents(tuple(c.text for c in chunks))
            if type(vectors) not in (tuple,list) or len(vectors)!=len(chunks):raise KnowledgeError('Embedding batch count is invalid.')
            records=tuple(VectorRecord(c.chunk_id,c.source_id,c.revision_id,c.content_sha256,
                normalized_vector(v,manifest.dimensions)) for c,v in zip(chunks,vectors))
            if self.repository.snapshot(scope)!=snapshot:raise KnowledgeError('Source changed during embedding.')
            self.repository.register_manifest(manifest)
            self.index.upsert(records)
            self.repository.acknowledge(chunks,manifest,request)
        except KnowledgeError:raise
        except Exception:raise KnowledgeError('Embedding or indexing failed safely.') from None
        return len(chunks)
