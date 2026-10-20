"""Resolve the exact upstream Riff dependency; never use a sibling checkout."""
import json
from pathlib import Path
import subprocess

PROJECT = Path(__file__).resolve().parents[3]


def riff_root():
    lock = json.loads((PROJECT / "upstream.lock.json").read_text())
    root = PROJECT / lock["path"]
    if not (root / "studio.py").is_file():
        raise RuntimeError("Initialize pinned Riff: git submodule update --init --recursive")
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != lock["revision"]:
        raise RuntimeError("Riff dependency differs from upstream.lock.json; review and update both pins together")
    if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"]).returncode:
        raise RuntimeError("Riff dependency has tracked modifications; restore the pinned source before building")
    return root
