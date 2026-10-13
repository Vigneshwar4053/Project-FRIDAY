"""Offline review only. No retention, embeddings, index, transport or runtime hooks."""
import json
from dataclasses import asdict
import unicodedata

from scripts import phase1d_dataset as dataset
from friday.intelligence.chunking import TextChunker
from friday.intelligence.ingestion import normalize_text, _SECRET
from friday.intelligence.models import IndexManifest, KnowledgeError, KnowledgeSource, TrustClassification, fingerprint
from friday.tools.sensitive import SensitivePaths, _PRIVATE_KEY, _PRIVATE_JSON

COMMITS = {
    'wstg': '74a854b2635316b63b53f1e4e2e8d482a59d2f71',
    'cheatsheets': 'cb9fe01e5ddf17b42513d2c53c4b86196c665c45',
    'mitre': '6cda5ad8462c79e14fbb872f4e09059b18e0cfc4',
}
ARCHIVES = {'wstg-7a1e7d6157efc92b', 'cheatsheets-86ddfbe1de52c357'}
REPORTS = {'ATTRIBUTION.txt', 'SHA256SUMS.txt', 'download-ledger.json',
           'inventory.json', 'rag-readiness.json', 'source-review.json', 'validation.json'}


def require(condition):
    if not condition:
        raise ValueError('Phase 1E corpus evidence mismatch; no indexing authorized.')


def review(root):
    # Refuse private filenames before the older validator reads any corpus file.
    sensitive = SensitivePaths()
    for path in root.rglob('*'):
        dataset.safe_path(root, str(path.relative_to(root)))
        require(not sensitive.excluded(path))
    validation = dataset.validate(root)
    manifest_bytes = dataset.read_file(root, 'manifest.json')
    manifest = json.loads(manifest_bytes)
    source_review = json.loads(dataset.read_file(root, 'reports/source-review.json'))
    ledger = json.loads(dataset.read_file(root, 'reports/download-ledger.json'))
    allowed_files = {'manifest.json'} | {'reports/' + name for name in REPORTS}
    all_documents = manifest['documents'] + manifest['excluded_documents']
    require(len(manifest['documents']) == 22 and not manifest['rejected_documents'])
    require({d['id'] for d in manifest['excluded_documents']} == ARCHIVES)
    require(len({d['id'] for d in all_documents}) == len(all_documents) == 24)
    require(set(source_review['sources']) == set(COMMITS))
    require(manifest['downloaded_document_count'] == 24)
    require(manifest['additional_sources'] == source_review['additional_sources'])
    require(all(manifest['security'][k] is False for k in
                ('execute_contents', 'follow_document_links', 'personal_memory_accessed', 'embeddings_created', 'indexed')))
    require(manifest['security']['documents_are_untrusted'] is True)
    for key, commit in COMMITS.items():
        source = source_review['sources'][key]
        require(source['commit'] == commit)
        for kind, transfer in zip(('commit', 'tree'), source['metadata_transfers'], strict=True):
            relative = f'sources/{key}-{kind}.json'
            allowed_files.add(relative)
            data = dataset.read_file(root, relative)
            require(dataset.sha(data) == transfer['sha256'] and len(data) == transfer['bytes'])
            require(transfer in ledger['requests'])
        commit_data = json.loads(dataset.read_file(root, f'sources/{key}-commit.json'))
        tree = json.loads(dataset.read_file(root, f'sources/{key}-tree.json'))
        # GitHub's recursive endpoint reports the requested commit in its sha field.
        require(commit_data['sha'] == tree['sha'] == commit and not tree['truncated'])
        require(commit_data['commit']['committer']['date'] == source['commit_date'])
        entries = {entry['path']: entry for entry in tree['tree'] if entry['type'] == 'blob'}
        selected = [d for d in manifest['documents'] if d['id'].split('-')[0] == key]
        require({d['upstream_path'] for d in selected} == {c['path'] for c in source['candidates']})
        for document in (d for d in all_documents if d['id'].split('-')[0] == key):
            raw = dataset.read_file(root, document['original_path'])
            processed = dataset.read_file(root, document['processed_path'])
            license_bytes = dataset.read_file(root, document['license']['path'])
            require(document['document_version'] == commit)
            require(document['repository_url'] == 'https://github.com/' + source['repo'])
            require(document['publisher'] == source['publisher'])
            require(document['license'] == {'name': source['license'], 'url': source['license_url'],
                    'path': source['license_path'], 'sha256': source['license_sha256']})
            require(document['id'] == key + '-' + dataset.sha(raw)[:16])
            blob = entries[document['upstream_path']]
            require(blob['sha'] == dataset.hashlib.sha1(('blob ' + str(len(raw)) + '\0').encode() + raw).hexdigest())
            require(blob['size'] == len(raw))
            require(document['source_url'] == dataset.raw_url(source['repo'], commit, document['upstream_path']))
            require(any(t['url'] == document['source_url'] and t['sha256'] == dataset.sha(raw)
                        and t['bytes'] == len(raw) and t['status'] == 200 for t in ledger['requests']))
            require(any(t['url'] == source['license_url'] and t['sha256'] == dataset.sha(license_bytes)
                        and t['bytes'] == len(license_bytes) for t in ledger['requests']))
            require(document['untrusted_document_text'] is True and document['trust'] == 'verified_official_publisher')
            require(not document['indexed'] and not document['embedded'])
            require(document['publication_date'] is None and document['repository_commit_date'] == source['commit_date'])
            require(document['attribution'] == source['publisher'] + '; original source and license retained. No publisher endorsement.')
            if document in selected:
                choice = next(c for c in source['candidates'] if c['path'] == document['upstream_path'])
                require(document['topics'] == choice['topics'])
            allowed_files.update((document['original_path'], document['processed_path'], document['license']['path']))
            if 'subset_path' in document:
                subset, body, count = dataset.mitre_subset(raw, license_bytes.decode())
                require(json.loads(dataset.read_file(root, document['subset_path'])) == subset)
                require(count == document['selected_technique_and_mitigation_count'] == 20)
                require(document['original_bundle_is_archival_only'] is True)
                require(document['changes'] == 'Bounded STIX selection and text rendering; source objects and MITRE license retained.')
                allowed_files.add(document['subset_path'])
            else:
                require(document['changes'] == 'UTF-8 BOM/newlines/Unicode NFC normalized; attribution prepended; original bytes retained.')
                body = unicodedata.normalize('NFC', raw.decode().removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n'))
                title = next((line.lstrip('# ').strip() for line in body.splitlines() if line.startswith('# ')),
                             document['upstream_path'].rsplit('/', 1)[-1][:-3].replace('_', ' '))
                require(document['title'] == title)
            attribution = ('# Source attribution\n\n' + document['attribution'] + '\nSource: ' + document['source_url']
                           + '\nLicense: ' + source['license'] + ' (' + source['license_url'] + ')\nVersion: '
                           + commit + '\nChanges: ' + document['changes'] + '\n\n')
            require(processed == (attribution + body).encode())
    require({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()} == allowed_files)
    require(len({d['sha256'] for d in all_documents}) == 24)
    require(len({d['processed_sha256'] for d in all_documents}) == 24)
    sums = ''.join(d['sha256'] + '  ' + d['original_path'] + '\n' + d['processed_sha256']
                   + '  ' + d['processed_path'] + '\n' for d in all_documents)
    require(dataset.read_file(root, 'reports/SHA256SUMS.txt').decode() == sums)
    inventory = json.loads(dataset.read_file(root, 'reports/inventory.json'))
    require(all(inventory[k] == manifest[k] for k in inventory))
    eligible, blocked = [], []
    for document in manifest['documents']:
        text = dataset.read_file(root, document['processed_path']).decode()
        try:
            normalized = normalize_text(text)
        except KnowledgeError:
            candidate = _SECRET.sub('[CREDENTIAL-LIKE EXAMPLE REMOVED]', text)
            try:
                normalize_text(candidate)
                redaction_compatible = True
            except KnowledgeError:
                redaction_compatible = False
            blocked.append({'id': document['id'], 'title': document['title'], 'publisher': document['publisher'],
                            'categories': {'credential_assignment': len(list(_SECRET.finditer(text))),
                                           'private_key_marker': len(list(_PRIVATE_KEY.finditer(text.encode()))),
                                           'private_json': len(list(_PRIVATE_JSON.finditer(text.encode())))},
                            'in_memory_redaction_policy_compatible': redaction_compatible,
                            'decision': 'exclude; formatting normalization cannot resolve; separately reviewed redacted derivative possible'})
            continue
        require(normalized == text)
        source = KnowledgeSource(document['source_url'], document['title'], document['publisher'],
                                 TrustClassification.VERIFIED_PUBLISHER, tuple(document['topics']), document['publication_date'])
        chunks = TextChunker().chunks(source.source_id, 'review-only', text)
        require(all(normalize_text(c.text) == c.text for c in chunks))
        eligible.append({**document, 'knowledge_source_id': source.source_id, 'chunks': len(chunks)})
    readiness = json.loads(dataset.read_file(root, 'reports/rag-readiness.json'))
    require({d['id'] for d in readiness['documents'] if d['phase1b_text_policy_compatible']} == {d['id'] for d in eligible})
    approval_scope = {'manifest_sha256': dataset.sha(manifest_bytes), 'documents': eligible,
                      'chunker': TextChunker().version, 'model': 'nomic-embed-text:v1.5',
                      'model_revision': '0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f',
                      'dimensions': 768}
    approval_scope['index_manifest'] = asdict(IndexManifest(approval_scope['model'],
        approval_scope['model_revision'], 768, 'search_document: ', 'search_query: '))
    chunks = sum(d['chunks'] for d in eligible)
    return {'validation': validation, 'eligible_count': len(eligible), 'blocked': blocked,
            'approval_scope': approval_scope, 'approval_sha256': fingerprint(approval_scope),
            'workload': {'chunks': chunks, 'processed_bytes': sum(d['processed_size_bytes'] for d in eligible),
                         'batches_at_most_four': (chunks + 3) // 4, 'float32_vector_bytes': chunks * 768 * 4},
            'indexing_performed': False, 'embeddings_created': False,
            'provenance_limit': 'Offline consistency against retained Phase 1D HTTPS evidence; no independent remote reauthentication.'}


if __name__ == '__main__':
    # Write only the review artifact, outside the preserved corpus.
    result = review(dataset.DATASET)
    destination = dataset.ROOT / 'docs/FRIDAY_PHASE1E_CORPUS.json'
    with destination.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, ensure_ascii=False)
        output.write('\n')
    print(json.dumps({k: result[k] for k in ('eligible_count', 'blocked', 'workload', 'approval_sha256')}, indent=2))
