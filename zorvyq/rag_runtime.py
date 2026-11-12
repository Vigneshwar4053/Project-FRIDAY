"""Read-only environment metadata. Never imports Chroma or opens a vector client."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.5.9'
EXECUTABLE = ROOT/'data/intelligence/rag-env/bin/python'
ENTRYPOINT = ROOT/'scripts/zorvyq_chroma_worker.py'

def approved_scope():
    import json
    from friday.intelligence.models import fingerprint,KnowledgeError
    from scripts.phase1e_index_preflight import APPROVED
    path=ROOT/'docs/FRIDAY_PHASE1E_CORPUS.json'
    if path.is_symlink():raise KnowledgeError('Approved metadata path changed.')
    with path.open('rb') as stream:raw=stream.read(1048577)
    if len(raw)>1048576:raise KnowledgeError('Approved metadata exceeded its bound.')
    value=json.loads(raw)
    if fingerprint(value['approval_scope'])!=value['approval_sha256'] or value['approval_sha256']!=APPROVED:
        raise KnowledgeError('Approved corpus metadata changed.')
    return value['approval_scope']

def approved_manifest():
    from friday.intelligence.models import IndexManifest
    return IndexManifest(**approved_scope()['index_manifest'])

def runtime_status(root=ROOT):
    root=Path(root)
    python=root/'data/intelligence/rag-env/bin/python'
    site=root/f'data/intelligence/rag-env/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    metadata=site/f'chromadb-{VERSION}.dist-info/METADATA'
    try:
        # Metadata only, bounded and no optional-package import side effects.
        if python.is_symlink() or metadata.is_symlink() or not os.access(python,os.X_OK):raise ValueError()
        with metadata.open('rb') as stream:header=stream.read(8192).decode('utf-8')
        if f'\nVersion: {VERSION}\n' not in '\n'+header or '\nName: chromadb\n' not in '\n'+header:
            raise ValueError()
        if not (site/'chromadb/__init__.py').is_file():raise ValueError()
        return {'available':True,'mode':'isolated-existing-environment','version':VERSION,
                'verification':'Installed metadata verified; vector open/live retrieval requires acceptance'}
    except (OSError,ValueError,UnicodeError):
        return {'available':False,'mode':'isolated-existing-environment','version':None,
                'verification':'Existing compatible RAG runtime missing or incompatible; no installation attempted'}
