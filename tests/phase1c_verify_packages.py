"""Offline revalidation of the approved wheels and installed distributions."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    proposal = json.loads((root / 'docs/FRIDAY_PHASE1C_ARTIFACTS.json').read_text())
    lock = (root / 'requirements-rag-phase1c.lock').read_text()
    records = []
    for artifact in proposal['artifacts']:
        path = root / 'data/intelligence/provisioning/wheels' / artifact['filename']
        data = path.read_bytes()
        assert len(data) == artifact['size_bytes']
        assert hashlib.sha256(data).hexdigest() == artifact['sha256']
        assert artifact['sha256'] in lock
        assert importlib.metadata.version(artifact['name']) == artifact['version']
        with zipfile.ZipFile(path) as wheel:
            assert wheel.testzip() is None
            assert not any(name.endswith('.pth') for name in wheel.namelist())
            notices = [name for name in wheel.namelist() if '.dist-info/' in name
                       and any(part in name.lower() for part in ('license', 'copying', 'notice'))]
        records.append({'name': artifact['name'], 'version': artifact['version'],
                        'url': artifact['url'], 'sha256': artifact['sha256'],
                        'size_bytes': len(data), 'bundled_notice_paths': notices,
                        'declared_license': artifact.get('license'),
                        'classifiers': artifact.get('classifiers', [])})
    assert len(records) == 84
    assert not any(dist.metadata['Name'].lower().startswith('langchain')
                   for dist in importlib.metadata.distributions())
    report = {'verified_wheels': len(records), 'total_wheel_bytes': sum(r['size_bytes'] for r in records),
              'installed_versions_match': True, 'zip_integrity_verified': True,
              'langchain_installed': False, 'artifacts': records}
    destination = root / 'data/intelligence/provisioning/package-verification.json'
    with destination.open('x') as stream:
        json.dump(report, stream, indent=2)
    destination.chmod(0o600)
    print('Verified 84 installed distributions, pinned wheel hashes, sizes and ZIP integrity.')


if __name__ == '__main__':
    main()
