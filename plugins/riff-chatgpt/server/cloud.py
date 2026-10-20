#!/usr/bin/env python3
"""Run Riff inside the current user's ChatGPT Work cloud computer.

A private Unix socket keeps native jobs alive between cloud tool calls. There
is no external backend, public listener, account credential, or local computer.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import stat
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from launch import ROOT, validate_bundle, environment, workspace_default
from adapter import Adapter, DraftStore, LoopbackBackend, MAX_INPUT
from main import RPC, CURRENT_PROTOCOL, PROTOCOL_KEY, CLIENT_CAPABILITIES_KEY
from runtime import ManagedRiff


def socket_path(workspace):
    # Linux pathname sockets have a 108-byte physical limit. User workspaces
    # and plugin caches can be much longer, so use a short private directory.
    directory=Path('/tmp')/('riff-cloud-'+str(os.getuid()))
    directory.mkdir(mode=0o700,exist_ok=True)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError('The cloud socket directory must be private and owned by this user.')
    return directory/hashlib.sha256(str(workspace).encode()).hexdigest()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_INPUT + 4097)
        if len(raw) > MAX_INPUT + 4096:
            self.wfile.write((json.dumps(RPC.error(None,-32600,'Cloud request exceeds the transfer limit.'))+'\n').encode())
            return
        message = json.loads(raw)
        if message.get('method') == 'cloud/stop':
            result = {'jsonrpc':'2.0','id':message.get('id'),'result':{'stopping':True}}
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            result = RPC(self.server.adapter).handle(message)
        self.wfile.write((json.dumps(result, allow_nan=False)+'\n').encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def serve(workspace):
    validate_bundle(ROOT, host_python=True)
    environment(ROOT, workspace)
    os.umask(0o077)
    path = socket_path(workspace)
    def stop(*_):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    # ManagedRiff holds its exclusive workspace lock before touching the socket.
    with ManagedRiff(ROOT/'riff', workspace) as port:
        path.unlink(missing_ok=True)
        adapter = Adapter(LoopbackBackend(port), DraftStore(workspace/'adapter-draft.sqlite3'), ROOT/'dist/studio.html')
        try:
            with Server(str(path), Handler) as server:
                server.adapter = adapter
                (workspace/'cloud-process.json').write_text(json.dumps({'pid':os.getpid(),'bundle':str(ROOT)}))
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        finally:
            adapter.close()
            path.unlink(missing_ok=True)
            (workspace/'cloud-process.json').unlink(missing_ok=True)


def exchange(workspace, message):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path(workspace)))
        client.sendall((json.dumps(message, allow_nan=False)+'\n').encode())
        with client.makefile('rb') as stream:
            return json.loads(stream.readline())


def ensure(workspace, startup_seconds):
    workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    if workspace.is_relative_to(ROOT):
        raise ValueError('Keep the cloud workspace outside the replaceable plugin package.')
    with (workspace/'cloud-start.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if socket_path(workspace).exists():
            try:
                exchange(workspace,{'jsonrpc':'2.0','id':0,'method':'ping'})
                current=json.loads((workspace/'cloud-process.json').read_text())
                if current['bundle'] != str(ROOT):
                    raise ValueError('Another Riff package owns this workspace. Stop it before switching packages.')
                return
            except (ConnectionError,FileNotFoundError):
                pass
        with (workspace/'cloud.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-B',str(ROOT/'server/cloud.py'),'--workspace',str(workspace),'_serve'],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        deadline=time.monotonic()+startup_seconds
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('Riff cloud startup failed. Inspect '+str(workspace/'cloud.log'))
            if socket_path(workspace).exists():
                try:
                    exchange(workspace,{'jsonrpc':'2.0','id':0,'method':'ping'})
                    return
                except (ConnectionError,FileNotFoundError):
                    pass
            time.sleep(.1)
        raise TimeoutError('Riff startup exceeded the configured transport deadline. Inspect cloud.log before retrying.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=workspace_default())
    parser.add_argument('--startup-seconds',type=float,default=120,help='Cloud process startup deadline')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('_serve')
    sub.add_parser('start')
    sub.add_parser('stop')
    call=sub.add_parser('call')
    call.add_argument('tool')
    call.add_argument('--arguments',default='{}',help='JSON tool arguments, or @/path/to/arguments.json')
    call.add_argument('--output-file',type=Path,help='Write the complete result privately; stdout omits app-only metadata')
    args=parser.parse_args()
    workspace=args.workspace.expanduser().resolve()
    if args.command=='_serve':
        serve(workspace);return
    if args.command=='stop':
        print(json.dumps(exchange(workspace,{'jsonrpc':'2.0','id':1,'method':'cloud/stop'})));return
    ensure(workspace,args.startup_seconds)
    if args.command=='start':
        print(json.dumps({'status':'ready','workspace':str(workspace),'bundle':str(ROOT),'pid':json.loads((workspace/'cloud-process.json').read_text())['pid']}));return
    value=args.arguments
    value=Path(value[1:]).read_text() if value.startswith('@') else value
    parameters=json.loads(value)
    result=exchange(workspace,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':args.tool,'arguments':parameters,
        '_meta':{PROTOCOL_KEY:CURRENT_PROTOCOL,CLIENT_CAPABILITIES_KEY:{}}}})
    if args.output_file:
        args.output_file.parent.mkdir(parents=True,exist_ok=True)
        with args.output_file.open('w',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
            json.dump(result,stream,allow_nan=False)
    # Do not copy app-only binary chunks or provider keys into model context.
    if isinstance(result.get('result'),dict):
        result['result'].pop('_meta',None)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    if 'error' in result or result.get('result',{}).get('isError'):
        raise SystemExit(1)


if __name__=='__main__':
    main()
