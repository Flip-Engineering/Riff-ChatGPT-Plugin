"""Cloud archive trust boundary; native execution is tested on real Linux."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('riff_cloud_bootstrap',Path(__file__).parents[1]/'cloud/riff.py')
cloud=importlib.util.module_from_spec(spec);spec.loader.exec_module(cloud)

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.skill=self.root/'skill';self.skill.mkdir()
        self.env=patch.dict(os.environ,{'XDG_CACHE_HOME':str(self.root/'cache')});self.env.start();self.addCleanup(self.env.stop)
    def archive(self,name='riff-chatgpt/server/cloud.py',link=None):
        path=self.skill/'runtime.tar.gz'
        with tarfile.open(path,'w:gz') as tar:
            member=tarfile.TarInfo(name)
            if link:
                member.type=tarfile.SYMTYPE;member.linkname=link;tar.addfile(member)
            else:
                body=b'# cloud runtime fixture\n';member.size=len(body);tar.addfile(member,io.BytesIO(body))
        (self.skill/'runtime.json').write_text(json.dumps({'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
        return path
    def test_verified_archive_reuses_same_cache(self):
        self.archive()
        first=cloud.bootstrap(self.skill)
        self.assertTrue((first/'server/cloud.py').is_file())
        self.assertEqual(first,cloud.bootstrap(self.skill))
    def test_altered_archive_rejected_before_extraction(self):
        path=self.archive();path.write_bytes(path.read_bytes()+b'corrupt')
        with self.assertRaises(ValueError):cloud.bootstrap(self.skill)
    def test_traversal_and_symlink_rejected(self):
        for name,link in [('../escape',None),('/tmp/escape',None),('riff-chatgpt/server/cloud.py','/etc/passwd')]:
            self.archive(name,link)
            with self.assertRaises(ValueError):cloud.bootstrap(self.skill)
        self.assertFalse((self.root/'escape').exists())

class ChatRuntimeTests(unittest.TestCase):
    def load_worker(self):
        import sys
        server=Path(__file__).parents[1]/'server'
        sys.path.insert(0,str(server))
        self.addCleanup(lambda:sys.path.remove(str(server)))
        spec=importlib.util.spec_from_file_location('riff_cloud_liveness_test',server/'cloud.py')
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        return worker

    def test_worker_lease_ignores_stale_or_namespace_local_pid(self):
        import subprocess
        import sys
        worker=self.load_worker()
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)
            # Even the caller's valid PID must not be mistaken for a worker.
            (workspace/'cloud-process.json').write_text(json.dumps({'pid':os.getpid(),'bundle':'/unrelated','liveness':'flock'}))
            self.assertFalse(worker.worker_running(workspace))
            process=subprocess.Popen([sys.executable,'-c',
                "import fcntl,sys; lease=open(sys.argv[1],'a'); fcntl.flock(lease,fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read()",
                str(workspace/'cloud-worker.lock')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(),'ready')
                self.assertTrue(worker.worker_running(workspace))
            finally:
                process.communicate('')
            self.assertFalse(worker.worker_running(workspace))

    def test_worker_loss_fails_promptly_without_replaying_mutation(self):
        worker=self.load_worker()
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)
            with self.assertRaisesRegex(RuntimeError,'worker stopped during request'):
                worker.exchange(workspace,{'method':'tools/call','params':{'name':'riff_generate'}})
            with worker.mailbox(workspace) as db:
                rows=db.execute('SELECT state,payload FROM requests').fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][0],'pending')
            self.assertEqual(json.loads(rows[0][1])['params']['name'],'riff_generate')

    def test_native_handlers_and_drafts_work_when_all_sockets_are_denied(self):
        import subprocess
        import sys
        repo=Path(__file__).resolve().parents[3]
        code=r'''
import json,os,sys
from pathlib import Path
from unittest.mock import patch
repo,workspace=map(Path,sys.argv[1:])
os.environ['RIFF_HOME']=str(workspace)
sys.path.insert(0,str(repo/'plugins/riff-chatgpt/server'))
from runtime import ManagedRiff
from inprocess import InProcessBackend
from adapter import Adapter,DraftStore
from routes import AdapterError
with patch('socket.socket',side_effect=PermissionError(1,'Operation not permitted')):
    with ManagedRiff(repo/'riff',workspace,server_factory=InProcessBackend) as backend:
        status,capabilities=backend.json_request('/api/capabilities')
        assert status==200 and capabilities['model']=='YuE2'
        status,state=backend.json_request('/api/state')
        assert status==200 and state['tracks']==[]
        adapter=Adapter(backend,DraftStore(workspace/'draft.sqlite3'),repo/'plugins/riff-chatgpt/dist/studio.html')
        recipe={'title':'No sockets','seed':'1234','max_seconds':1,'steps':2}
        saved=adapter.call('riff_save_draft',{'recipe':recipe,'expected_revision':0})
        assert saved['structuredContent']['body']=={'revision':1,'recipe':recipe}
        assert adapter.call('riff_get_draft',{})['structuredContent']['body']=={'revision':1,'recipe':recipe}
        try:
            adapter.call('riff_save_draft',{'recipe':{},'expected_revision':0})
            raise AssertionError('stale write accepted')
        except AdapterError as error:
            assert 'conflict' in str(error).lower()
        adapter.close()
print('native routes and draft persistence passed with socket creation denied')
'''
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([sys.executable,'-B','-c',code,str(repo),tmp],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('socket creation denied',result.stdout)

    def test_cli_writes_full_result_to_private_output_file(self):
        import contextlib
        import sys
        server=Path(__file__).parents[1]/'server'
        sys.path.insert(0,str(server))
        self.addCleanup(lambda:sys.path.remove(str(server)))
        spec=importlib.util.spec_from_file_location('riff_cloud_worker_test',server/'cloud.py')
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'result.json'
            payload={'result':{'structuredContent':{'status':200},'_meta':{'private':'bytes'}}}
            args=['riff','--workspace',tmp,'call','riff_get_draft','--output-file',str(output)]
            stdout=io.StringIO()
            with patch.object(sys,'argv',args),patch.object(worker,'ensure'),patch.object(worker,'exchange',return_value=payload),contextlib.redirect_stdout(stdout):
                worker.main()
            self.assertEqual(json.loads(output.read_text())['result']['_meta'],{'private':'bytes'})
            self.assertEqual(output.stat().st_mode & 0o777,0o600)
            self.assertNotIn('_meta',json.loads(stdout.getvalue())['result'])
