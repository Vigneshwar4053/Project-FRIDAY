"""Embedding protocol only. No SDK, transport, model load or automatic pull."""
import math
from typing import Protocol
from friday.intelligence.models import IndexManifest, KnowledgeError


class EmbeddingProvider(Protocol):
    manifest: IndexManifest
    def embed_documents(self,texts: tuple[str,...]) -> tuple[tuple[float,...],...]: ...
    def embed_query(self,text: str) -> tuple[float,...]: ...


def normalized_vector(vector,dimensions):
    if (type(vector) not in (tuple,list) or len(vector)!=dimensions or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in vector)):
        raise KnowledgeError('Embedding shape or values are invalid.')
    magnitude=math.hypot(*vector)
    if not math.isfinite(magnitude) or magnitude==0:raise KnowledgeError('Embedding vector is invalid.')
    return tuple(v/magnitude for v in vector)
