"""Verify the exact owner approval and platform controls before any indexing.

This preflight performs local metadata requests and artifact hashing only.
It cannot pull models, create embeddings or open a knowledge/vector store.
"""
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import stat
from time import monotonic
import zipfile

from friday.intelligence.models import IndexManifest, fingerprint
from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
from friday.sync import create_synchronization
from friday.tools.grants import directory_descriptor
from scripts import phase1d_dataset as dataset
from scripts.phase1e_review import review
from scripts.phase1e_admission import (AdmissionDenied, ResourceSample, admit,
    available_ram, private_storage_size, require_enforced_bounds)

APPROVED = 'ad18870e8af3c30ee4b8bb11f018dba9a92a2352e7c2d7a9363a8801d3c5cdb4'
QWEN = '359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7'


def require(condition):
    if not condition:
        raise AdmissionDenied('Approved corpus or installed artifact verification failed.')


def approved_corpus(root=dataset.ROOT):
    artifact = json.loads((root / 'docs/FRIDAY_PHASE1E_CORPUS.json').read_text())
    require(fingerprint(artifact['approval_scope']) == artifact['approval_sha256'] == APPROVED)
    current = review(root / 'knowledge/cybersecurity')
    require(current['approval_sha256'] == APPROVED and current['approval_scope'] == artifact['approval_scope'])
    require(current['eligible_count'] == 20 and current['workload']['chunks'] == 312)
    require({b['id'] for b in current['blocked']} ==
            {'wstg-345317d8a05797f6', 'cheatsheets-92f7483b28548679'})
    return current


def hash_file(path, expected_size=None):
    """Pin no-follow regular file identity and hash with a 1 MiB buffer."""
    with directory_descriptor(path.parent) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1)
            if expected_size is not None:
                require(before.st_size == expected_size)
            digest = hashlib.sha256()
            total = 0
            while True:
                block = os.read(descriptor, 1024 * 1024)
                if not block:
                    break
                total += len(block)
                require(total <= before.st_size)
                digest.update(block)
            identity = lambda i: (i.st_dev, i.st_ino, i.st_size, i.st_mtime_ns, i.st_ctime_ns)
            require(total == before.st_size and identity(before) == identity(os.fstat(descriptor)) ==
                    identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)))
            return digest.hexdigest()
        finally:
            os.close(descriptor)


def verify_packages(root):
    proposal = json.loads((root / 'docs/FRIDAY_PHASE1C_ARTIFACTS.json').read_text())
    lock = (root / 'requirements-rag-phase1c.lock').read_text()
    checked_files = 0
    for artifact in proposal['artifacts']:
        path = root / 'data/intelligence/provisioning/wheels' / artifact['filename']
        require(hash_file(path, artifact['size_bytes']) == artifact['sha256'])
        require(artifact['sha256'] in lock)
        distribution = importlib.metadata.distribution(artifact['name'])
        require(distribution.version == artifact['version'])
        with zipfile.ZipFile(path) as wheel:
            require(wheel.testzip() is None)
            require(not any(name.endswith('.pth') for name in wheel.namelist()))
            for entry in wheel.infolist():
                if entry.is_dir() or entry.filename.endswith('.dist-info/RECORD') or '.data/' in entry.filename:
                    continue  # pip rewrites RECORD and script installation metadata.
                expected = hashlib.sha256()
                with wheel.open(entry) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        expected.update(block)
                require(hash_file(Path(distribution.locate_file(entry.filename)), entry.file_size) == expected.hexdigest())
                checked_files += 1
    require(len(proposal['artifacts']) == 84 and importlib.metadata.version('chromadb') == '1.5.9')
    return {'verified_wheels': 84, 'installed_payload_files_verified': checked_files,
            'chroma_version': '1.5.9', 'new_packages_installed': False}


def verify_local_manifest(model_root, name, tag, expected_digest, expected_manifest=None):
    """Ollama retains the registry manifest as a final descriptor/blob.

    Verify that blob, every wrapper field and its exact appended descriptor;
    never mistake the wrapper's different byte hash for the registry digest.
    """
    path = model_root / 'manifests/registry.ollama.ai/library' / name / tag
    wrapper_sha = hash_file(path)
    require(path.stat().st_size <= 65536)
    wrapper_bytes = path.read_bytes()
    require(hashlib.sha256(wrapper_bytes).hexdigest() == wrapper_sha)
    wrapper = json.loads(wrapper_bytes)
    blob_path = model_root / 'blobs' / ('sha256-' + expected_digest)
    require(blob_path.stat().st_size <= 65536)
    require(hash_file(blob_path) == expected_digest)
    registry_bytes = blob_path.read_bytes()
    require(hashlib.sha256(registry_bytes).hexdigest() == expected_digest)
    registry = json.loads(registry_bytes)
    if expected_manifest is not None:
        require(registry == expected_manifest)
    descriptor = {'mediaType': registry['mediaType'], 'digest': 'sha256:' + expected_digest,
                  'size': len(registry_bytes)}
    require(wrapper == {**registry, 'layers': [*registry['layers'], descriptor]})
    return {'registry_manifest_sha256': expected_digest, 'local_wrapper_sha256': wrapper_sha,
            'registry_manifest_bytes': len(registry_bytes), 'wrapper_descriptor_verified': True}


def verify_models(root, manifest):
    proposal = json.loads((root / 'docs/FRIDAY_PHASE1C_ARTIFACTS.json').read_text())['model']
    require(proposal['manifest_sha256'] == manifest.model_revision)
    gate = create_synchronization()
    try:
        provider = OllamaEmbeddingProvider(manifest, gate, timeout=10)
        deadline = monotonic() + 10
        provider._verify(deadline)  # Existing pinned digest/capability checks; no inference.
        tags = provider._request('/api/tags', deadline)['models']
        require(len([m for m in tags if m.get('name') == 'qwen3:4b' and m.get('digest') == QWEN]) == 1)
        resident = provider._request('/api/ps', deadline)['models']
        if resident:
            raise AdmissionDenied('Ollama workload is resident; stop without eviction.')
        show = provider._request('/api/show', deadline, {'model': manifest.model, 'verbose': False})
        paths = [line[5:].strip().strip('"') for line in show['modelfile'].splitlines() if line.startswith('FROM ')]
        require(len(paths) == 1)
        weights = Path(paths[0])
        require(weights.is_absolute() and weights.name == proposal['manifest']['layers'][0]['digest'].replace(':', '-'))
        layers = []
        for layer in [proposal['manifest']['config'], *proposal['manifest']['layers']]:
            digest = hash_file(weights.parent / layer['digest'].replace(':', '-'), layer['size'])
            require(digest == layer['digest'].split(':')[1])
            layers.append({'sha256': digest, 'size_bytes': layer['size']})
        model_root = weights.parent.parent
        manifests = {}
        for name, tag, digest in ((manifest.model.split(':')[0], 'v1.5', manifest.model_revision), ('qwen3', '4b', QWEN)):
            manifests[name] = verify_local_manifest(model_root, name, tag, digest,
                                                    proposal['manifest'] if name == 'nomic-embed-text' else None)
        require(provider._request('/api/ps', monotonic() + 10)['models'] == [])
        return {'model': manifest.model, 'model_revision': manifest.model_revision, 'dimensions': 768,
                'verified_layers': layers, 'qwen_manifest_sha256': QWEN, 'resident_models': [],
                'manifest_storage': manifests,
                'inference_requests': 0, 'model_downloads': 0, 'model_evictions': 0}
    finally:
        gate.close()


def platform_evidence(storage_parent):
    lines = Path('/proc/self/cgroup').read_text().splitlines()
    current = next(line[3:] for line in lines if line.startswith('0::'))
    group = Path('/sys/fs/cgroup') / current.lstrip('/')
    mounted = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        mount = Path(fields[4].replace('\\040', ' '))
        if storage_parent == mount or mount in storage_parent.parents:
            mounted.append((len(mount.parts), {'mountpoint': str(mount),
                'filesystem': fields[fields.index('-') + 1],
                'options': fields[5].split(',') + fields[-1].split(',')}))
    require(bool(mounted))
    storage_mount = max(mounted, key=lambda value: value[0])[1]
    # Observed quota options are evidence of facility configuration only; they
    # would still require an exact owned-project quota verification before use.
    quota_options = {'quota', 'usrquota', 'grpquota', 'prjquota', 'pquota'} & set(storage_mount['options'])
    return {'memory_cgroup': str(group), 'memory_max': (group / 'memory.max').read_text().strip(),
            'memory_control_writable': os.access(group / 'memory.max', os.W_OK),
            'storage_mount': storage_mount, 'quota_mount_options': sorted(quota_options),
            'aggregate_storage_quota_verified': False,
            'isolated_embedding_memory_limit_verified': False,
            'reason': 'No dedicated aggregate storage quota or owned memory domain including Ollama has been established. '
                      'Polling and per-file RLIMIT_FSIZE cannot guarantee these aggregate maxima.'}


def main():
    root = dataset.ROOT
    current = approved_corpus(root)
    manifest = IndexManifest(**current['approval_scope']['index_manifest'])
    report = {'corpus_sha256': APPROVED, 'eligible_documents': 20, 'eligible_chunks': 312,
              'index_manifest': asdict(manifest), 'embedding_generation_id': manifest.generation_id,
              'indexed_documents': 0, 'indexed_chunks': 0, 'retained_documents': 0,
              'real_embeddings_created': False}
    report['packages'] = verify_packages(root)
    report['models'] = verify_models(root, manifest)
    storage_parent = root / 'data/intelligence'
    parent_info = storage_parent.lstat()
    require(stat.S_ISDIR(parent_info.st_mode) and parent_info.st_uid == os.getuid()
            and stat.S_IMODE(parent_info.st_mode) == 0o700)
    available = available_ram()
    admit(ResourceSample(0, 0, available), reserved_storage=100 * 1024 ** 2, reserved_rss=2 * 1024 ** 3)
    report['available_ram_bytes'] = available
    report['private_storage_parent_verified'] = True
    report['resource_controls'] = platform_evidence(storage_parent)
    try:
        require_enforced_bounds(aggregate_storage_quota_verified=report['resource_controls']['aggregate_storage_quota_verified'],
                                isolated_embedding_memory_limit_verified=report['resource_controls']['isolated_embedding_memory_limit_verified'])
    except AdmissionDenied as error:
        report['status'] = 'stopped_before_indexing'
        report['stop_reason'] = str(error)
    else:
        raise AdmissionDenied('Index activation is not implemented in this preflight.')
    destination = storage_parent / 'phase1e-owner-preflight.json'
    with directory_descriptor(destination.parent) as directory:
        descriptor = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
    print(json.dumps(report, indent=2))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
