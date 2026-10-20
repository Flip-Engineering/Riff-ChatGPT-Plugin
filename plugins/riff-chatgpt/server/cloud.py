#!/usr/bin/env python3
"""Run the bundled Riff runtime in Chat using a private disk-backed mailbox.

No listening or Unix sockets are required. The existing native studio handlers
run in the worker process; original jobs, validation and rendering are retained.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from launch import ROOT, validate_bundle, environment
from adapter import Adapter, DraftStore, MAX_INPUT
from main import RPC, CURRENT_PROTOCOL, PROTOCOL_KEY, CLIENT_CAPABILITIES_KEY
from runtime import ManagedRiff, write_json
from inprocess import InProcessBackend


@contextlib.contextmanager
def mailbox(workspace):
    db=sqlite3.connect(workspace/'cloud-mailbox.sqlite3',timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, response TEXT)')
    try:
        with db:
            yield db
    finally:
        db.close()


def exchange(workspace,message,timeout=300):
    raw=json.dumps(message,allow_nan=False)
    if len(raw.encode())>MAX_INPUT+4096:
        raise ValueError('Cloud request exceeds the transfer limit.')
    request_id=uuid.uuid4().hex
    with mailbox(workspace) as db:
        db.execute('INSERT INTO requests VALUES(?,?,?,NULL)',(request_id,raw,'pending'))
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        with mailbox(workspace) as db:
            row=db.execute('SELECT state,response FROM requests WHERE id=?',(request_id,)).fetchone()
            if row and row[0]=='complete':
                result=json.loads(row[1])
                db.execute('DELETE FROM requests WHERE id=?',(request_id,))
                return result
        time.sleep(.05)
    raise TimeoutError('Riff command timed out; request '+request_id+' remains in the mailbox. Inspect it before retrying a mutation.')


def serve(workspace):
    validate_bundle(ROOT,host_python=True)
    environment(ROOT,workspace)
    os.umask(0o077)
    def stop(*_):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,stop)
    with ManagedRiff(ROOT/'riff',workspace,server_factory=InProcessBackend) as backend:
        adapter=Adapter(backend,DraftStore(workspace/'adapter-draft.sqlite3'),ROOT/'dist/studio.html')
        record=workspace/'cloud-process.json'
        try:
            with mailbox(workspace) as db:
                # An interrupted mutation must never be replayed automatically.
                db.execute("UPDATE requests SET state='complete',response=? WHERE state='running'",
                           (json.dumps(RPC.error(None,-32603,'The previous Riff worker stopped during this request. Inspect job state before retrying.')),))
            write_json(record,{'pid':os.getpid(),'bundle':str(ROOT),'transport':'sqlite-inprocess'})
            while True:
                with mailbox(workspace) as db:
                    row=db.execute("SELECT id,payload FROM requests WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
                    if row:
                        db.execute("UPDATE requests SET state='running' WHERE id=?",(row[0],))
                if not row:
                    time.sleep(.05);continue
                message=json.loads(row[1])
                stopping=message.get('method')=='cloud/stop'
                result=({'jsonrpc':'2.0','id':message.get('id'),'result':{'stopping':True}}
                        if stopping else RPC(adapter).handle(message))
                with mailbox(workspace) as db:
                    db.execute("UPDATE requests SET state='complete',response=? WHERE id=?",(json.dumps(result,allow_nan=False),row[0]))
                if stopping:break
        except KeyboardInterrupt:
            pass
        finally:
            adapter.close()
            record.unlink(missing_ok=True)


def ensure(workspace,startup_seconds):
    workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    if workspace.is_relative_to(ROOT):
        raise ValueError('Keep the cloud workspace outside the replaceable plugin package.')
    with (workspace/'cloud-start.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        record=workspace/'cloud-process.json'
        if record.exists():
            current=json.loads(record.read_text())
            try:
                os.kill(current['pid'],0)
            except ProcessLookupError:
                record.unlink(missing_ok=True)
            else:
                if current['bundle']!=str(ROOT):
                    raise ValueError('Another Riff package owns this workspace. Stop it before switching packages.')
                exchange(workspace,{'jsonrpc':'2.0','id':0,'method':'ping'},timeout=startup_seconds)
                return
        with (workspace/'cloud.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-B',str(ROOT/'server/cloud.py'),'--workspace',str(workspace),'_serve'],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        deadline=time.monotonic()+startup_seconds
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('Riff cloud startup failed. Inspect '+str(workspace/'cloud.log'))
            if record.exists():
                exchange(workspace,{'jsonrpc':'2.0','id':0,'method':'ping'},timeout=max(.1,deadline-time.monotonic()))
                return
            time.sleep(.1)
        raise TimeoutError('Riff startup exceeded the configured transport deadline. Inspect cloud.log before retrying.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path.cwd()/"riff-workspace")
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
        with open(args.output_file,'w',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(result,stream,allow_nan=False)
    # Do not copy app-only binary chunks or provider keys into model context.
    if isinstance(result.get('result'),dict):
        result['result'].pop('_meta',None)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    if 'error' in result or result.get('result',{}).get('isError'):
        raise SystemExit(1)


if __name__=='__main__':
    main()
