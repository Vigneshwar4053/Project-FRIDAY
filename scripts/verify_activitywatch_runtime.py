#!/usr/bin/env python3
"""Verify installed release; optionally smoke-test ONLY a disposable local server.
Never starts a watcher, ingests activity, reads browser data or runs a model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from zorvyq.awareness.runtime import ROOT, discover, session_type
from zorvyq.awareness.adapter import ActivityWatch, Unavailable


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-check',action='store_true')
    args=parser.parse_args()
    paths=discover()
    manifest=json.loads((ROOT/'third_party/activitywatch-manifest.json').read_text())
    archive=ROOT/'third_party/activitywatch-v0.14.1-linux-x86_64.zip'
    with archive.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['sha256']
    print('Official release archive and installed executable checksums: PASS')
    print('Desktop session:',session_type())
    for name,path in paths.items():
        result=subprocess.run([str(path),'--help'],capture_output=True,timeout=5,check=False)
        if result.returncode:raise RuntimeError('Executable compatibility failed: '+name)
        print(name,'executable compatibility: PASS')
    if not args.server_check:return
    adapter=ActivityWatch(timeout=.5)
    try:adapter.buckets()
    except Unavailable:pass
    else:
        print('Existing responsive server; disposable check refused to avoid a duplicate instance.')
        return
    with TemporaryDirectory(prefix='zorvyq-aw-health-') as directory:
        env={k:v for k,v in os.environ.items() if 'proxy' not in k.lower()}
        for key,leaf in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:
            env[key]=str(Path(directory)/leaf)
        process=subprocess.Popen([str(paths['server']),'--host','127.0.0.1','--port','5600'],env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,umask=0o077)
        try:
            deadline=monotonic()+8
            while monotonic()<deadline and process.poll() is None:
                try:
                    buckets=adapter.buckets()
                    if buckets:raise RuntimeError('Disposable server unexpectedly has buckets')
                    print('Server running: YES; real local /api/0/buckets/ response: HTTP 200, empty')
                    listeners=[]
                    for name in ('tcp','tcp6'):
                        for line in Path('/proc/net/'+name).read_text().splitlines()[1:]:
                            fields=line.split()
                            if fields[3]=='0A' and fields[1].endswith(':15E0'):listeners.append(fields[1])
                    assert listeners==['0100007F:15E0'], 'Loopback listener verification failed'
                    print('Listener: 127.0.0.1:5600 only; watchers started: NONE; real events observed: NONE')
                    break
                except Unavailable:sleep(.1)
            else:raise RuntimeError('Disposable server did not become responsive')
        finally:
            process.terminate()
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
    print('Disposable server stopped; temporary data removed.')


if __name__=='__main__':main()
