#!/usr/bin/env python3
"""Pair the user's native Chat runtime with the authenticated studio transport.

Run in a retained, network-enabled execution session. Only a pinned HTTPS
transport is accepted. No network listener, arbitrary shell command or public
file server is created. Interrupted commands are never re-executed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://riff-studio-transport.amusedcorgi5.chatgpt.site'


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, 'Transport redirects are not accepted.', headers, fp)


class Transport:
    def __init__(self, endpoint=ENDPOINT, service_access=None):
        if endpoint != ENDPOINT:
            raise ValueError('Only the verified Riff transport endpoint is accepted.')
        self.endpoint, self.service_access = endpoint, service_access
        self.opener = urllib.request.build_opener(NoRedirects)

    def post(self, route, payload, credential=None):
        headers = {'Content-Type': 'application/json'}
        if credential:
            headers['Authorization'] = 'Bearer ' + credential
        # Private owner acceptance only. Never bundled, shared or needed by a
        # public transport. This is a Sites access credential, not a worker key.
        if self.service_access:
            headers['OAI-Sites-Authorization'] = 'Bearer ' + self.service_access
        request = urllib.request.Request(self.endpoint + '/runtime/' + route,
                                        data=json.dumps(payload, allow_nan=False).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                data = response.read(1600001)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 409):
                raise RuntimeError('Riff transport rejected this session (' + str(exc.code) + '). Inspect pairing/native state before retrying.') from None
            raise
        if len(data) > 1600000:
            raise ValueError('Riff transport response exceeds the transfer limit.')
        return json.loads(data)


def poll_command(transport, session, credential, sleep=time.sleep):
    """Recover brief transport loss without resubmitting a native operation."""
    for attempt in range(3):
        try:
            return transport.post('poll', {'session_id': session}, credential).get('command')
        except urllib.error.HTTPError as exc:
            # Older transport deployments classified unexpected storage errors
            # as 400. Authorization/session rejections remain immediately fatal.
            if exc.code != 400 and exc.code < 500:
                raise
            exc.close()
            if attempt == 2:
                raise
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
        print(json.dumps({'status': 'poll_retry', 'attempt': attempt + 1}), flush=True)
        sleep(attempt + 1)


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(value, output, allow_nan=False)


class Forwarder:
    """Durably claim locally before executing; retain results on upload loss."""
    def __init__(self, path, execute):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS forwarded (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, result TEXT)')
        self.execute = execute

    def forward(self, command):
        rid = command['request_id']
        payload = {'name': command['tool'], 'arguments': command['arguments']}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        row = self.db.execute('SELECT digest,state,result FROM forwarded WHERE id=?', (rid,)).fetchone()
        if row:
            if row[0] != digest:
                raise ValueError('Command identity was reused for a different operation.')
            if row[1] == 'complete':
                return json.loads(row[2])
            return {'isError': True, 'content': [{'type': 'text', 'text':
                'This command was interrupted after local claim. Inspect native state before retrying; it was not replayed.'}]}
        with self.db:
            self.db.execute('INSERT INTO forwarded VALUES(?,?,?,NULL)', (rid, digest, 'claimed'))
        try:
            result = self.execute(payload)
        except Exception:
            # The mailbox may contain completed work even if exchange failed.
            result = {'isError': True, 'content': [{'type': 'text', 'text':
                'Native command exchange was interrupted. Inspect job and draft state before retrying; no mutation was replayed.'}]}
        with self.db:
            self.db.execute('UPDATE forwarded SET state=?,result=? WHERE id=?',
                            ('complete', json.dumps(result, allow_nan=False), rid))
        return result

    def acknowledge(self, rid):
        with self.db:
            self.db.execute("UPDATE forwarded SET state='acknowledged',result=NULL WHERE id=? AND state='complete'", (rid,))

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--enrollment-file', type=Path, help='Private JSON returned by riff_connect_runtime; consumed once')
    parser.add_argument('--service-access-file', type=Path, help='Private Sites service-access token file for owner-only acceptance')
    parser.add_argument('--seconds', type=int, default=3300)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    os.umask(0o077)
    skill = Path(__file__).resolve().parents[1]
    from riff import bootstrap
    bundle = bootstrap(skill)
    sys.path.insert(0, str(bundle/'server'))
    from cloud import ensure, exchange
    from main import CURRENT_PROTOCOL, PROTOCOL_KEY, CLIENT_CAPABILITIES_KEY
    from adapter import TOOL_MAP
    workspace = args.workspace.expanduser().resolve()
    ensure(workspace, 120)
    state_file = workspace/'studio-relay.json'
    service = args.service_access_file.read_text().strip() if args.service_access_file else None
    transport = Transport(service_access=service)
    if args.enrollment_file:
        enrollment = json.loads(args.enrollment_file.read_text())
        claimed = transport.post('claim', {'session_id': enrollment['session_id'],
                                         'enrollment_token': enrollment['enrollment_token']})
        state = {'session_id': enrollment['session_id'], **claimed}
        private_json(state_file, state)
        args.enrollment_file.unlink()
    else:
        state = json.loads(state_file.read_text())
    session, credential = state['session_id'], state['worker_token']

    def execute(payload):
        if payload['name'] not in TOOL_MAP:
            raise ValueError('Unknown native tool.')
        result = exchange(workspace, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {**payload, '_meta': {PROTOCOL_KEY: CURRENT_PROTOCOL, CLIENT_CAPABILITIES_KEY: {}}}}, timeout=40)
        if 'error' in result:
            return {'isError': True, 'content': [{'type': 'text', 'text': result['error']['message']}]}
        return result['result']

    forwarder = Forwarder(workspace/'studio-relay.sqlite3', execute)
    deadline = time.monotonic()+args.seconds
    try:
        print(json.dumps({'status': 'connected', 'transport': ENDPOINT, 'native_workspace': str(workspace)}), flush=True)
        while time.monotonic() < deadline and time.time()*1000 < state['expires']:
            command = poll_command(transport, session, credential)
            if not command:
                time.sleep(1)
                continue
            result = forwarder.forward(command)
            # Retry delivering a cached result, never its native operation.
            for attempt in range(3):
                try:
                    transport.post('complete', {'session_id': session, 'request_id': command['request_id'],
                        'claim': command['claim'], 'result': result}, credential)
                    forwarder.acknowledge(command['request_id'])
                    break
                except (OSError, urllib.error.URLError):
                    if attempt == 2:
                        raise
                    time.sleep(1)
    finally:
        forwarder.close()
        print(json.dumps({'status': 'disconnected', 'native_data_preserved': True}), flush=True)


if __name__ == '__main__':
    main()
