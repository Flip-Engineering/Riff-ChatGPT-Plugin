"""Offline recovery contracts for the managed model downloader."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("riff_managed_download_test", Path(__file__).parents[1] / "server/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Response(io.BytesIO):
    def __init__(self, value, status=200, headers=None):
        super().__init__(value)
        self.status = status
        self.headers = headers or {}


class Generator:
    def resume(self):
        pass


class Downloads(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="riff-model-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = b"verified model bytes"
        (self.root / "VERSION").write_text("0.6.20")
        (self.root / "sources.json").write_text(json.dumps({"model": {"repo": "example/model", "revision": "pinned",
            "files": {"model.gguf": {"bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}}}}))
        (self.root / "data").mkdir()
        self.manager = runtime.ManagedMaintenance(self.root, self.root, Generator(), None)
        self.manager.model_root.mkdir(parents=True)
        self.partial = self.manager.model_root / "model.gguf.part"
        self.target = self.manager.model_root / "model.gguf"

    def run_download(self, response):
        self.manager.task = {"status": "running", "total_bytes": len(self.data)}
        with patch.object(runtime.urllib.request, "urlopen", return_value=response) as request:
            self.manager._download()
        return request

    def assert_completed(self):
        self.assertEqual(self.manager.task["status"], "done")
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertFalse(self.partial.exists())

    def test_corrupt_full_partial_can_retry_without_manual_file_removal(self):
        self.partial.write_bytes(b"x" * len(self.data))
        request = self.run_download(Response(self.data))
        self.assertIsNone(request.call_args.args[0].get_header("Range"))
        self.assert_completed()

    def test_oversized_partial_can_retry_without_manual_file_removal(self):
        self.partial.write_bytes(self.data + b"invalid trailing data")
        self.run_download(Response(self.data))
        self.assert_completed()

    def test_incomplete_transfer_is_resumed_and_verified(self):
        prefix = self.data[:7]
        self.run_download(Response(prefix))
        self.assertEqual(self.manager.task["status"], "failed")
        self.assertFalse(self.target.exists())
        self.assertEqual(self.partial.read_bytes(), prefix)
        request = self.run_download(Response(self.data[7:], 206, {"Content-Range": f"bytes 7-{len(self.data)-1}/{len(self.data)}"}))
        self.assertEqual(request.call_args.args[0].get_header("Range"), "bytes=7-")
        self.assert_completed()

    def test_completed_invalid_transfer_never_activates_or_poisons_retry(self):
        self.run_download(Response(b"x" * len(self.data)))
        self.assertEqual(self.manager.task["status"], "failed")
        self.assertFalse(self.target.exists())
        self.assertFalse(self.partial.exists())
        self.run_download(Response(self.data))
        self.assert_completed()

    def test_cancel_preserves_incomplete_cache(self):
        self.partial.write_bytes(self.data[:7])
        self.manager.cancelled.set()
        request = self.run_download(Response(self.data))
        self.assertEqual(self.manager.task["status"], "cancelled")
        self.assertEqual(self.partial.read_bytes(), self.data[:7])
        self.assertFalse(self.target.exists())
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
