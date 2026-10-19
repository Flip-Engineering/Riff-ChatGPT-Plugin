#!/usr/bin/env python3
"""Fetch the checksum-pinned standalone CPython runtime for the release target."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from build_media import fetch, sha


def build(destination, target):
    if destination.exists():
        raise ValueError("Choose a fresh Python runtime directory.")
    destination.mkdir(parents=True)
    pins = json.loads((Path(__file__).parent / "components.json").read_text())["python"]
    pin = pins[target]
    archive = destination / pin["archive"]
    fetch(pin, archive)
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
    python = destination / "python"
    executable = python / "bin/python3"
    output = subprocess.check_output([str(executable), "-I", "-B", "-c",
        "import json,sys,ssl,sqlite3; print(json.dumps({'python':sys.version,'openssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version}))"], text=True)
    (destination / "build.json").write_text(json.dumps({"schema": "riff.chatgpt.python.v1",
        "platform": target, "component": pin, "startup": json.loads(output)}, indent=2) + "\n")
    print(python)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=["linux-x86_64", "macos-arm64"], required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.platform)
