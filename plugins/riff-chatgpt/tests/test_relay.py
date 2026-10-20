import importlib.util
from pathlib import Path
import tempfile
import unittest
import urllib.error

path=Path(__file__).resolve().parents[1]/'cloud/relay.py'
spec=importlib.util.spec_from_file_location('riff_cloud_relay',path)
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)


class RelayTests(unittest.TestCase):
    def test_completed_and_acknowledged_mutations_are_not_replayed(self):
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'relay.sqlite3'
            command={'request_id':'a'*32,'tool':'riff_save_draft','arguments':{'expected_revision':0}}
            def execute(payload):
                calls.append(payload)
                return {'content':[],'_meta':{'base64':'AAEC'},'structuredContent':{'revision':1}}
            f=relay.Forwarder(db,execute)
            first=f.forward(command);self.assertEqual(f.forward(command),first);f.close()
            f=relay.Forwarder(db,execute)
            self.assertEqual(f.forward(command),first)
            f.acknowledge(command['request_id'])
            self.assertTrue(f.forward(command)['isError'])
            self.assertEqual(len(calls),1)
            self.assertIsNone(f.db.execute('SELECT result FROM forwarded').fetchone()[0]);f.close()

    def test_crash_after_claim_reports_uncertainty_instead_of_reexecution(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'relay.sqlite3';command={'request_id':'b'*32,'tool':'riff_generate','arguments':{}}
            def die(payload):raise KeyboardInterrupt()
            f=relay.Forwarder(db,die)
            with self.assertRaises(KeyboardInterrupt):f.forward(command)
            f.close()
            f=relay.Forwarder(db,lambda _:self.fail('Interrupted mutation replayed'))
            self.assertTrue(f.forward(command)['isError'])
            with self.assertRaisesRegex(ValueError,'identity'):
                f.forward({**command,'arguments':{'changed':True}})
            f.close()

    def test_transport_rejects_arbitrary_endpoints(self):
        with self.assertRaisesRegex(ValueError,'verified'):
            relay.Transport('http://localhost:9999')

    def test_poll_recovers_transient_storage_failure_without_replaying_commands(self):
        class Transport:
            def __init__(self): self.calls=0
            def post(self, route, body, credential):
                self.calls+=1
                self.assert_route=route
                if self.calls<3:
                    raise urllib.error.HTTPError('https://transport/runtime/poll',503,'Storage unavailable',None,None)
                return {'command':{'request_id':'new-command'}}
        transport=Transport()
        result=relay.poll_command(transport,'session','private',sleep=lambda _:None)
        self.assertEqual(result,{'request_id':'new-command'})
        self.assertEqual(transport.calls,3)
        self.assertEqual(transport.assert_route,'poll')

    def test_poll_does_not_retry_session_rejection(self):
        class Transport:
            def post(self, *args): raise RuntimeError('Riff transport rejected this session (401).')
        with self.assertRaisesRegex(RuntimeError,'401'):
            relay.poll_command(Transport(),'session','private',sleep=lambda _:self.fail('Auth retry'))
