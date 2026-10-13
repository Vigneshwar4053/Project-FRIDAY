# Phase 1B: dependency-free local knowledge foundation

Implemented on 2026-10-12 under the owner's latest instruction. This checkpoint
implements isolated library contracts and synthetic tests. It does not perform
the earlier proposed public-document collection: no documentation or model was
downloaded, no license-dependent corpus was copied, and no real ingestion ran.
LangChain, ChromaDB, Ollama embeddings and answer generation are not connected.

The existing uncommitted 3L/3M work is preserved. No existing runtime, routing,
configuration, authentication, permission, voice, desktop or memory module was
modified. No project `.env`, owner credentials, personal documents or existing
database records were accessed. No package install, browser navigation, network
scan, commit or push occurred.

## Files and lifecycle

New modules under `friday/intelligence/`:

| File | Responsibility |
| --- | --- |
| `__init__.py` | Optional package with no eager composition or storage |
| `models.py` | Immutable source/revision/chunk/evidence/index records, IDs and budgets |
| `permissions.py` | Separate exact-purpose approval contracts; deny by default |
| `ingestion.py` | Bounded inert UTF-8 `.txt`/`.md` reading, normalization and secret exclusions |
| `chunking.py` | Deterministic paragraph-aware UTF-8 byte bounds and character spans |
| `repository.py` | Separate private SQLite repository, provenance, revisions and index acknowledgements |
| `embeddings.py` | Embedding protocol and finite, nonzero vector validation/normalization |
| `index.py` | Vector protocol, four-chunk indexing batches and idempotent acknowledgement |
| `retrieval.py` | Exact-scope, current-revision evidence with runtime-issued citations |

`tests/test_intelligence_foundation.py` contains original synthetic networking,
TCP/UDP, authorized scanning/Nmap concepts, defensive assessment and OWASP text.
All selected files and SQLite databases are temporary test fixtures. This report
is the only new documentation file. Existing `data/*` ignore rules already cover
the proposed database and sidecars; `.gitignore` did not need modification.

An explicit caller may construct `KnowledgeRepository` at
`data/intelligence/knowledge.sqlite3` later. No default path is opened on import,
and that real repository was not created in this checkpoint. Current operations
are synchronous and intended for one trusted host thread, without watchers,
background workers, model loading or automatic composition.

## Knowledge schema

Application ID `0x46524B31`, schema version 1, foreign keys enabled. Existing
foreign databases or unknown schema versions are refused without migrations.
The separate repository cannot be constructed with `friday.db` as its filename.

| Table | Stored data |
| --- | --- |
| `sources` | Deterministic source ID, unique opaque identifier/HTTPS provenance, active revision, active/revoked state |
| `revisions` | Immutable revision ID, source provenance snapshot, optional supplied document version, canonical content SHA-256, UTC ingestion timestamp, approved text, chunker version |
| `chunks` | Deterministic chunk ID, source/revision, ordinal, start/end character offsets, exact text and chunk SHA-256 |
| `manifests` | Generation ID and exact model/artifact/dimension/prefix/normalization/distance/chunker configuration |
| `indexed_chunks` | Generation/chunk/hash acknowledgements after successful vector upsert |
| `approvals` | Purpose, exact scope fingerprint and approval timestamp; no query or document bodies |

KnowledgeSource contains title, publisher, HTTPS URL or opaque `local:`/`synthetic:`
identifier, trust classification, topic tags and nullable publication date.
Retention consent does not promote an unverified reference to a verified
publisher. Document versions/dates are not inferred. The SHA-256 refers to the
approved normalized UTF-8 text, not a downloaded file or original binary.

Source IDs derive from identifiers. Revision IDs bind source metadata, supplied
document revision, canonical content hash and chunker version. Chunk IDs bind
revision, chunker policy, ordinal, offsets and chunk hash. Identical ingestion
keeps the original revision and ingestion timestamp while requiring fresh
retention approval; a changed text or provenance snapshot creates a new revision.
Identical text in different sources keeps separate provenance.

Storage creation requires an owner-controlled 0700 directory and regular 0600
database files, with no symlink/hardlink substitution. The parent remains pinned
through the repository lifecycle. Existing SQLite journals/WAL/SHM are checked
before SQLite opens the path; newly created sidecars use a temporary 0077 umask.
Private file checks run again around transactions. Insecure existing storage is
refused, not silently chmodded. This is plaintext storage and does not isolate
malicious processes running under the same UID. A future host must protect the
entire intelligence directory through the existing tool SensitivePaths boundary
before real corpus use; current runtime integration is intentionally untouched.

## Authorization and ingestion

`KnowledgeAuthorization` receives a trusted host callback. Only the typed
`KnowledgeDecision.ALLOW_ONCE` authorizes a request; Boolean/string equivalents,
missing callbacks, denied decisions and callback errors fail closed. Each
operation asks afresh. A future CLI must implement the actual reviewed owner
interaction; this callback is not a model-configurable setting or an owner-auth
bypass.

Purposes remain distinct:

- Document reading: exact selected pathname and pinned device/inode/size/time identity.
- Knowledge retention: source and exact new revision/content fingerprint.
- Embedding/indexing: exact sources, current revisions and index-generation fingerprint.
- Retrieval: exact source scope, current revisions, generation and query fingerprint.
- Revocation: exact source/current-revision scope.

File reading pins a supported regular file without reading content, then obtains
read approval, revalidates identity, reads at most 1 MiB and checks identity again.
It rejects sensitive filenames/components, system roots, symlinks, hardlinks,
special files, unsupported extensions, invalid UTF-8 and unsupported controls.
The returned text conveys no retention or embedding permission. Only explicitly
selected files are supported; there is no directory crawling or URL fetch.

Text normalization removes a leading BOM, canonicalizes newlines and applies
Unicode NFC. Known private-key/token structures and common credential assignments
are rejected before retention or embeddings, including metadata and queries.
This conservative filter is not an exhaustive detector of arbitrary secrets;
real source selection and private owner review remain provisioning prerequisites.

Chunking defaults to 1,536 UTF-8 bytes with at most 192 bytes overlap, preferring
paragraph boundaries. Offsets are end-exclusive character offsets in canonical
text. Unicode characters are never split. There is a 10,000-active-chunk corpus
limit and a per-document chunk-count limit. Original headings remain in the text.

## Indexing, retrieval and citations

EmbeddingProvider and VectorIndex are protocols only; tests inject mocks.
No transport, SDK or default embedding function exists. Manifests must match;
vectors must have the exact dimension and finite nonzero values and are L2
normalized for cosine indexing. A later provider must honor its declared prefix
policy and pinned artifact. Chroma must receive vectors explicitly.

Each indexing call approves the current scope and processes at most four chunks,
with at most 6,144 document-text bytes. Source/chunk integrity is verified before
embedding. After vector upsert, SQLite acknowledges only still-current sources.
If upsert or acknowledgement fails, retry uses the same chunk IDs. Unacknowledged
vectors have no retrieval authority; there is no claim of a transaction spanning
SQLite and the vector store. Changed revisions immediately exclude old IDs.

Retrieval permits at most eight candidates and three evidence chunks, a 2,048-byte
query and a 2,048-byte serialized evidence block including citation metadata.
Current scope is checked around approval and again before returning evidence.
Unknown, duplicate, stale, foreign-scope or revoked IDs cannot supply text.
Cross-source current pointers, modified provenance/chunks and changed stored
index manifests fail closed or produce no eligible evidence. Oversized chunks
are omitted intact rather than silently shortened to fit the evidence budget.

Runtime-issued `S1`/`S2`/`S3` labels bind source, publisher, title, source URL/opaque
identifier, revision, document hash, ingestion/publication metadata, trust,
chunk ID and exact offsets. Citation lookup rejects labels outside that exact
bundle. EvidenceBundle hides its document body from its repr and is marked
`persist=False`, `speech_eligible=False`. There is no model generation, tool,
ordinary memory or speech dependency that can consume document instructions.
These markers are contracts, not an implemented assistant persistence policy;
future integration must explicitly preserve the existing context limits and
scrub private generation jobs/history. A valid citation is not a faithfulness
proof, and mock rankings are not a semantic retrieval-quality benchmark.

No ready source or no eligible evidence returns an explicit empty bundle with a
fixed reason. It performs no query embedding when no indexed source is eligible.
No ungrounded generated answer or fabricated citation is substituted.

Revocation marks the source revoked and removes SQLite index acknowledgements
transactionally. Retained revision text and stale vectors remain physically
present but cannot be retrieved, including after restart. Re-ingestion cannot
silently reactivate a revoked source. Physical deletion, vector cleanup and
explicit reenrollment are later, separately reviewed contracts.

## Validation and next checkpoint

All tests use synthetic data. Coverage includes approved/denied operations,
duplicate and modified revisions, revocation/reopen, deterministic Unicode
chunk spans, exact citations, foreign/stale IDs, tampered provenance/manifests,
file substitution and malformed input, offline execution, no crawling, no shell,
no memory construction/persistence, no speech, private storage and crash replay.

Final results: **39 new foundation tests passed; 354 targeted tests passed;
1,599 full regression tests passed outside the sandbox; `git diff --check`
passed.** The initial sandbox full suite hit the four existing headless IPC
permission errors and their four cleanup failures; all passed outside it.
Current Git status still contains the pre-existing browser changes plus the
new package, test module and this report. No commits or pushes were made.

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest test_intelligence_foundation test_memory test_workload test_core test_model_runtime test_filesystem_permissions test_tool_routing test_voice_automatic
.venv/bin/python -B -m unittest discover -s tests
git diff --check
git status --short
```

The next proposed implementation checkpoint is **1C: reviewed offline adapters
and real synthetic retrieval benchmark**. First present a compatible pinned
LangChain/Chroma dependency lock and exact Ollama embedding artifact for separate
approval; this checkpoint authorizes no installation or model download. Then
implement local-only adapters with explicit vectors, no implicit downloads,
disabled telemetry, finite-vector checks, transport/time/resource bounds,
cancellation and network-denied persistence/reopen tests. Add explicit physical
deletion/rebuild jobs and corpus storage protection before real documents.

Only after real retrieval quality/privacy checks should a separately reviewed
explicit assistant command assemble bounded untrusted evidence for Qwen3:4b,
validate citations, prevent chat/job retention and keep automatic speech off.
LangChain should compose that reviewed flow rather than create an autonomous
tool agent. No actual document collection or ingestion is enabled here.
