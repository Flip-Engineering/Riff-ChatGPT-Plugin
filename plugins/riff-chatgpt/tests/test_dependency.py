"""The downstream must use its reviewed, immutable upstream source."""
import sys
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from riff_dependency import riff_root

class DependencyTests(unittest.TestCase):
    def test_real_pinned_source_has_lora_and_original_studio(self):
        root = riff_root()
        self.assertTrue((root / "loras.py").is_file())
        self.assertTrue((root / "web/loras.js").is_file())
        self.assertFalse((root / "plugins/riff-chatgpt").exists())

    def test_revision_mismatch_is_rejected(self):
        with patch("riff_dependency.subprocess.check_output", return_value="0" * 40):
            with self.assertRaisesRegex(RuntimeError, "differs from"):
                riff_root()

    def test_modified_upstream_is_rejected(self):
        revision = json.loads((Path(__file__).resolve().parents[3] / "upstream.lock.json").read_text())["revision"]
        with patch("riff_dependency.subprocess.check_output", return_value=revision), patch("riff_dependency.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, "tracked modifications"):
                riff_root()
