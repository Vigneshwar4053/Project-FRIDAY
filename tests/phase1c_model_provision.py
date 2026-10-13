"""Explicit pinned model provisioning; no generation, unrelated pulls or unloads."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def local(path, payload=None, timeout=30):
    connection = http.client.HTTPConnection('127.0.0.1', 11434, timeout=timeout)
    try:
        connection.request('POST' if payload is not None else 'GET', path,
                           body=json.dumps(payload) if payload is not None else None,
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('Local Ollama metadata unavailable')
        data = response.read(1048577)
        if len(data) > 1048576:
            raise RuntimeError('Metadata exceeds bound')
        return json.loads(data)
    finally:
        connection.close()


def main():
    proposal = json.loads((ROOT / 'docs/FRIDAY_PHASE1C_ARTIFACTS.json').read_text())['model']
    before = local('/api/tags')['models']
    if local('/api/ps')['models']:
        raise RuntimeError('Resident Ollama workload; stop without eviction')
    parsed = urlsplit(proposal['manifest_url'])
    if parsed.scheme != 'https' or parsed.hostname != 'registry.ollama.ai':
        raise RuntimeError('Unapproved registry')
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=30,
                                             context=ssl.create_default_context())
    try:
        connection.request('GET', parsed.path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('Registry response failed; redirects forbidden')
        manifest = response.read(65537)
        if len(manifest) > 65536 or hashlib.sha256(manifest).hexdigest() != proposal['manifest_sha256']:
            raise RuntimeError('Remote manifest differs from approved fingerprint')
        if json.loads(manifest) != proposal['manifest']:
            raise RuntimeError('Remote manifest content mismatch')
    finally:
        connection.close()
    pulled = local('/api/pull', {'model': proposal['name'], 'stream': False}, timeout=600)
    if pulled.get('status') != 'success':
        raise RuntimeError('Pinned model pull failed')
    after = local('/api/tags')['models']
    pinned = [m for m in after if m['name'] == proposal['name']]
    if len(pinned) != 1 or pinned[0]['digest'] != proposal['manifest_sha256']:
        raise RuntimeError('Installed model digest mismatch')
    for model in before:
        if model['name'] != proposal['name'] and not any(
                m['name'] == model['name'] and m['digest'] == model['digest'] for m in after):
            raise RuntimeError('Existing model identity changed')
    show = local('/api/show', {'model': proposal['name']})
    if 'embedding' not in show['capabilities'] or show['model_info'].get('nomic-bert.embedding_length') != 768:
        raise RuntimeError('Embedding identity mismatch')
    match = re.search(r'^FROM (.+)$', show['modelfile'], re.MULTILINE)
    if not match:
        raise RuntimeError('Exact installed weight pathname unavailable')
    weight_path = Path(match[1].strip().strip('"'))
    if weight_path.name != 'sha256-' + proposal['manifest']['layers'][0]['digest'].split(':')[1]:
        raise RuntimeError('Installed weight name mismatch')
    verified = []
    for layer in [proposal['manifest']['config'], *proposal['manifest']['layers']]:
        path = weight_path.parent / layer['digest'].replace(':', '-')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != layer['size']:
            raise RuntimeError('Installed model layer size or type mismatch')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1048576), b''):
                digest.update(block)
        if digest.hexdigest() != layer['digest'].split(':')[1]:
            raise RuntimeError('Installed layer fingerprint mismatch')
        verified.append({'sha256': digest.hexdigest(), 'size_bytes': info.st_size})
    report = {'model': proposal['name'], 'manifest_sha256': proposal['manifest_sha256'],
              'layers': verified, 'dimensions': 768, 'existing_models_unchanged': True,
              'registry_url': proposal['manifest_url']}
    destination = ROOT / 'data/intelligence/provisioning/model-verification.json'
    with destination.open('x') as stream:
        json.dump(report, stream, indent=2)
    destination.chmod(0o600)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
