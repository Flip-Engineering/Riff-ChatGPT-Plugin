import importlib.util
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock

path=Path(__file__).resolve().parents[1]/'cloud/relay.py'
spec=importlib.util.spec_from_file_location('riff_cloud_relay',path)
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)


class RelayTests(unittest.TestCase):
    def test_late_delivery_keeps_receipt_and_allows_the_next_command_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            f=relay.Forwarder(Path(tmp)/'relay.sqlite3',lambda payload:calls.append(payload) or {'content':[]})
            command={'request_id':'c'*32,'tool':'riff_save_draft','arguments':{},'claim':'private'}
            result=f.forward(command)
            transport=Mock()
            transport.post.side_effect=relay.ResultDeliveryRejected('Late response')
            self.assertFalse(relay.deliver_result(transport,'session','private',command,result,f))
            self.assertEqual(f.db.execute('SELECT state FROM forwarded').fetchone()[0],'complete')
            self.assertEqual(f.forward(command),result)
            next_command={**command,'request_id':'d'*32,'tool':'riff_get_draft'}
            transport.post.side_effect=None
            self.assertTrue(relay.deliver_result(transport,'session','private',next_command,f.forward(next_command),f))
            self.assertEqual(len(calls),2)
            self.assertEqual(f.db.execute('SELECT state FROM forwarded WHERE id=?',('d'*32,)).fetchone()[0],'acknowledged')
            f.close()

    def test_transport_distinguishes_late_response_from_session_authentication_rejection(self):
        transport=relay.Transport()
        transport.opener=Mock()
        def reject(*args, **kwargs):
            raise urllib.error.HTTPError('https://transport/runtime/complete',409,'Late',None,None)
        transport.opener.open.side_effect=reject
        with self.assertRaises(relay.ResultDeliveryRejected):
            transport.post('complete',{},'private')
        with self.assertRaises(RuntimeError) as raised:
            transport.post('poll',{},'private')
        self.assertNotIsInstance(raised.exception,relay.ResultDeliveryRejected)

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
