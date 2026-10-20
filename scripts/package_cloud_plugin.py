#!/usr/bin/env python3
"""Package verified Riff native components for execution in ChatGPT Work Cloud.

The cloud host supplies Python 3.12+. Native inference, ERTS/control and media
executables are carried in the archive; no MCP endpoint or homelab is used.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'plugins/riff-chatgpt'
sys.path.insert(0,str(PLUGIN/'scripts'))
from riff_dependency import riff_root


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def package(source,destination):
    source=source.resolve()
    config=json.loads((source/'runtime/runtime.json').read_text())
    lock=json.loads((ROOT/'upstream.lock.json').read_text())
    if config.get('riff_commit')!=lock['revision'] or config.get('platform')!='linux-x86_64' or config.get('backend')!='cpu':
        raise ValueError('Cloud packaging requires the verified Linux CPU package of the pinned Riff revision.')
    # Validate every input byte before deriving the cloud distribution.
    manifest=json.loads((source/'bundle-manifest.json').read_text())
    for entry in manifest['files']:
        path=source/entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(source) or path.stat().st_size!=entry['bytes'] or sha(path)!=entry['sha256']:
            raise ValueError('Invalid platform component: '+entry['path'])
    destination=destination.resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        folder=Path(folder)
        bundle=folder/'riff-chatgpt'
        shutil.copytree(source,bundle,ignore=lambda directory,names: [n for n in names if (Path(directory)/n)==source/'runtime/python'])
        # Desktop connection metadata never enters the cloud package.
        (bundle/'mcp.json').unlink(missing_ok=True)
        config['execution']='chatgpt-cloud'
        config['plugin_version']='0.3.0'
        config['host_python_minimum']='3.12'
        (bundle/'runtime/runtime.json').write_text(json.dumps(config,indent=2)+'\n')
        records=[{'path':p.relative_to(bundle).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p),'executable':os.access(p,os.X_OK)}
                 for p in sorted(bundle.rglob('*')) if p.is_file() and p.name!='bundle-manifest.json']
        (bundle/'bundle-manifest.json').write_text(json.dumps({'schema':'riff.chatgpt.bundle.v1','files':records},indent=2)+'\n')
        archive=folder/'runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            tar.add(bundle,arcname='riff-chatgpt')
        metadata=json.loads((PLUGIN/'plugin.json').read_text())
        metadata['version']='0.3.0'
        metadata['description']='Compose and generate music with Riff inside your ChatGPT Work cloud computer.'
        interface=metadata['extensions']['com.openai']['interface']
        interface['shortDescription']='Make music in ChatGPT Work'
        interface['longDescription']='Compose music, generate YuE2 recordings and scores, and manage LoRAs inside your ChatGPT Work cloud computer. The plugin bundles the native Riff engine, score runtime and media tools. Music models download separately into your cloud workspace; no local computer or developer server is required.'
        interface.pop('capabilities',None)
        skill='riff-chatgpt/skills/riff-studio/'
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as zip:
            zip.writestr('riff-chatgpt/plugin.json',json.dumps(metadata,indent=2)+'\n')
            zip.write(PLUGIN/'cloud/SKILL.md',skill+'SKILL.md')
            zip.write(PLUGIN/'cloud/riff.py',skill+'scripts/riff.py')
            zip.writestr(skill+'runtime.json',json.dumps({'sha256':sha(archive),'bytes':archive.stat().st_size,'riff_revision':lock['revision'],'platform':'linux-x86_64'}))
            zip.write(archive,skill+'runtime.tar.gz',compress_type=zipfile.ZIP_STORED)
            for path in sorted((PLUGIN/'assets').rglob('*')):
                if path.is_file():zip.write(path,'riff-chatgpt/'+path.relative_to(PLUGIN).as_posix())
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    riff_root()
    print(package(args.runtime_package,args.output))
