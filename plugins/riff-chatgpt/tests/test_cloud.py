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
