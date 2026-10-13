"""Explicit provisioning helper. Run only after exact artifact owner approval.

Reads the reviewed manifest, saves hash-checked wheels, and installs offline into
an isolated environment. Does not pull models or modify the current .venv.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
from time import monotonic
from urllib.parse import urlsplit
import venv
import zipfile

from friday.tools.grants import directory_descriptor
from friday.intelligence.repository import private_creation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-approved-artifacts',action='store_true',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    proposal=json.loads((root/'docs/FRIDAY_PHASE1C_ARTIFACTS.json').read_text())
    if sys.version.split()[0]!=proposal['python']:raise RuntimeError('Interpreter differs from the reviewed lock.')
    wheels=root/'data/intelligence/provisioning/wheels';environment=root/'data/intelligence/rag-env'
    with directory_descriptor(wheels,create=True):pass
    if sum(a['size_bytes'] for a in proposal['artifacts'])!=proposal['package_transfer_bytes']:
        raise RuntimeError('Artifact size manifest mismatch.')
    for artifact in proposal['artifacts']:
        path=wheels/artifact['filename'];parsed=urlsplit(artifact['url'])
        if (path.name!=artifact['filename'] or not path.name.endswith('.whl') or
                parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or
                parsed.username is not None or parsed.query or parsed.fragment):raise RuntimeError('Unapproved artifact URL.')
        if path.exists():data=path.read_bytes()
        else:
            connection=http.client.HTTPSConnection(parsed.hostname,timeout=30,context=ssl.create_default_context())
            try:
                deadline=monotonic()+120
                connection.request('GET',parsed.path)
                response=connection.getresponse()
                if response.status!=200:raise RuntimeError('Wheel response failed; no redirects followed.')
                if response.getheader('Content-Type','').split(';')[0].strip() not in {'application/octet-stream','binary/octet-stream','application/zip'}:
                    raise RuntimeError('Wheel content type is unsupported.')
                data=bytearray()
                while len(data)<=artifact['size_bytes']:
                    if monotonic()>=deadline:raise RuntimeError('Wheel deadline exceeded.')
                    if connection.sock:connection.sock.settimeout(min(30,max(.001,deadline-monotonic())))
                    chunk=response.read1(min(65536,artifact['size_bytes']+1-len(data)))
                    if not chunk:break
                    data.extend(chunk)
                if len(data)!=artifact['size_bytes']:raise RuntimeError('Wheel size differs from approval.')
                if hashlib.sha256(data).hexdigest()!=artifact['sha256']:raise RuntimeError('Wheel fingerprint differs from approval.')
                with private_creation(),path.open('xb') as output:output.write(data)
                print('verified',artifact['name'],artifact['version'],len(data),flush=True)
            finally:connection.close()
        if len(data)!=artifact['size_bytes'] or hashlib.sha256(data).hexdigest()!=artifact['sha256']:
            raise RuntimeError('Saved wheel fingerprint mismatch.')
        with zipfile.ZipFile(path) as archive:
            if any(name.endswith('.pth') for name in archive.namelist()):
                raise RuntimeError('Executable startup .pth content requires additional review.')
    if environment.exists():raise RuntimeError('Isolated environment already exists; no overwrite.')
    with private_creation():venv.EnvBuilder(with_pip=False).create(environment)
    python=environment/'bin/python'
    install_environment={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8',
        'HOME':str(environment),'PIP_CONFIG_FILE':os.devnull,'PIP_DISABLE_PIP_VERSION_CHECK':'1',
        'PYTHONDONTWRITEBYTECODE':'1'}
    subprocess.run([sys.executable,'-B','-m','pip','--python',str(python),'install','--no-index',
        '--no-cache-dir','--only-binary=:all:','--require-hashes','--find-links',str(wheels),'-r',str(root/'requirements-rag-phase1c.lock')],
        check=True,timeout=300,env=install_environment)
    subprocess.run([sys.executable,'-B','-m','pip','--python',str(python),'check'],check=True,timeout=30,env=install_environment)
    print('isolated_environment',environment)


if __name__=='__main__':main()
