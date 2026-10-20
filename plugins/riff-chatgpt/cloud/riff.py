#!/usr/bin/env python3
"""Verify/unpack the bundled Linux runtime, then execute it in Work Cloud."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile


def bootstrap(skill):
    pin=json.loads((skill/'runtime.json').read_text())
    archive=skill/'runtime.tar.gz'
    with archive.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=pin['sha256'] or archive.stat().st_size!=pin['bytes']:
        raise ValueError('The bundled cloud runtime failed its integrity check.')
    cache=Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'riff-chatgpt'/digest
    cache.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (cache.parent/(digest+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not cache.exists():
            with tempfile.TemporaryDirectory(dir=cache.parent,prefix='.unpack-') as temporary:
                temporary=Path(temporary)
                with tarfile.open(archive) as tar:
                    for member in tar.getmembers():
                        if not (member.isfile() or member.isdir()) or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                            raise ValueError('The cloud archive contains an unsafe member.')
                    tar.extractall(temporary,filter='data')
                (temporary/'riff-chatgpt').replace(cache)
    return cache


if __name__=='__main__':
    if sys.version_info<(3,12):
        raise SystemExit('Riff Cloud requires Python 3.12 or newer in this cloud computer.')
    bundle=bootstrap(Path(__file__).resolve().parents[1])
    os.execv(sys.executable,[sys.executable,'-B',str(bundle/'server/cloud.py'),*sys.argv[1:]])
