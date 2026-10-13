"""Immutable provenance and evidence. Document text never carries authority."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from enum import StrEnum
import hashlib
import json
import re
from urllib.parse import urlsplit

MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_ACTIVE_CHUNKS = 10_000
TOPICS = frozenset({'networking','network_scanning','nmap','web_security','ethical_hacking',
    'penetration_testing','linux_security','cryptography','vulnerability_management',
    'threat_intelligence','incident_response','network_monitoring','security_tools','defensive_security'})


class KnowledgeError(RuntimeError):
    """Only fixed diagnostics cross the application boundary."""


class TrustClassification(StrEnum):
    UNVERIFIED = 'unverified_reference'
    OWNER_APPROVED = 'owner_approved_reference'
    VERIFIED_PUBLISHER = 'verified_publisher'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')))


def bounded_text(value, limit=512):
    try:
        valid=(type(value) is str and value.strip() and len(value.encode('utf-8'))<=limit and
               not any(ord(c)<32 or 127<=ord(c)<=159 for c in value))
    except UnicodeError:valid=False
    if not valid:
        raise KnowledgeError('Invalid knowledge metadata.')
    return value


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):
        raise KnowledgeError('Invalid knowledge fingerprint.')


@dataclass(frozen=True)
class KnowledgeSource:
    identifier: str
    title: str
    publisher: str
    trust: TrustClassification = TrustClassification.UNVERIFIED
    topics: tuple[str,...] = ()
    publication_date: str | None = None

    def __post_init__(self):
        for value in (self.identifier,self.title,self.publisher):bounded_text(value)
        if self.identifier.startswith('https://'):
            parsed=urlsplit(self.identifier)
            if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise KnowledgeError('Invalid knowledge source URL.')
            if parsed.port not in (None,443):raise KnowledgeError('Invalid knowledge source URL.')
        elif not re.fullmatch(r'(?:synthetic|local):[a-zA-Z0-9_.-]{1,100}',self.identifier):
            raise KnowledgeError('Use an HTTPS source or opaque local identifier.')
        if type(self.trust) is not TrustClassification:
            raise KnowledgeError('Invalid trust classification.')
        if (type(self.topics) is not tuple or len(self.topics)>len(TOPICS) or
                any(type(tag) is not str for tag in self.topics) or not set(self.topics)<=TOPICS):
            raise KnowledgeError('Invalid knowledge topics.')
        if self.publication_date is not None:
            try:date.fromisoformat(self.publication_date)
            except (TypeError,ValueError):raise KnowledgeError('Invalid source date.') from None

    @property
    def source_id(self):
        return 'src_'+digest(self.identifier)


@dataclass(frozen=True)
class SourceRevision:
    revision_id: str
    source: KnowledgeSource
    content_sha256: str
    ingestion_timestamp: str
    document_revision: str | None
    text: str = field(repr=False)


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    revision_id: str
    ordinal: int
    start: int
    end: int
    content_sha256: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class IndexManifest:
    model: str
    model_revision: str
    dimensions: int
    document_prefix: str = ''
    query_prefix: str = ''
    chunker_version: str = 'utf8-paragraph-v1:1536:192'
    normalization: str = 'l2'
    distance: str = 'cosine'

    def __post_init__(self):
        bounded_text(self.model,128);check_hash(self.model_revision)
        bounded_text(self.chunker_version,128)
        if type(self.dimensions) is not int or not 1<=self.dimensions<=4096:
            raise KnowledgeError('Invalid embedding dimensions.')
        if self.normalization!='l2' or self.distance!='cosine':
            raise KnowledgeError('Unsupported vector configuration.')
        for prefix in (self.document_prefix,self.query_prefix):
            if type(prefix) is not str or len(prefix.encode('utf-8'))>128 or any(ord(c)<32 for c in prefix):
                raise KnowledgeError('Invalid embedding prefix.')

    @property
    def generation_id(self):
        return 'idx_'+fingerprint(asdict(self))


@dataclass(frozen=True)
class RetrievalEvidence:
    citation_id: str
    chunk: KnowledgeChunk = field(repr=False)
    source: KnowledgeSource
    document_revision: str | None
    document_sha256: str
    ingestion_timestamp: str

    def payload(self):
        return {'citation':self.citation_id,'source_id':self.chunk.source_id,
            'revision_id':self.chunk.revision_id,'chunk_id':self.chunk.chunk_id,
            'title':self.source.title,'publisher':self.source.publisher,
            'source':self.source.identifier,'publication_date':self.source.publication_date,
            'document_revision':self.document_revision,'content_sha256':self.document_sha256,
            'ingestion_timestamp':self.ingestion_timestamp,'trust':self.source.trust.value,
            'start':self.chunk.start,'end':self.chunk.end,'text':self.chunk.text}


@dataclass(frozen=True)
class EvidenceBundle:
    evidence: tuple[RetrievalEvidence,...] = field(default=(),repr=False)
    empty_reason: str | None = None
    persist: bool = field(default=False,init=False)
    speech_eligible: bool = field(default=False,init=False)

    def serialize(self):
        return json.dumps([e.payload() for e in self.evidence],ensure_ascii=False,separators=(',',':'))

    def citation(self,label):
        for evidence in self.evidence:
            if evidence.citation_id==label:return evidence.payload()
        raise KnowledgeError('Citation is not in the supplied evidence map.')
