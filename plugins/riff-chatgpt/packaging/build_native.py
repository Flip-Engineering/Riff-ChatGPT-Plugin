#!/usr/bin/env python3
"""Compile the exact Riff native source and complete patch set on a release host."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from riff_dependency import riff_root

REPO = riff_root()


def build(destination, backend, jobs):
    if destination.exists():
        raise ValueError("Choose a fresh native build directory.")
    if backend == "metal" and (sys.platform != "darwin" or platform.machine() != "arm64"):
        raise ValueError("Build the Metal package on an Apple Silicon Mac.")
    pins = json.loads((REPO / "sources.json").read_text())
    cmake = shutil.which("cmake")
    if not cmake or subprocess.check_output([cmake, "--version"], text=True).splitlines()[0] != "cmake version " + pins["cmake"]:
        raise ValueError("Install the pinned CMake " + pins["cmake"] + " on the release build host.")
    destination.mkdir(parents=True)
    os.environ["RIFF_HOME"] = str(destination)
    sys.path.insert(0, str(REPO))
    import setup_engine
    result = setup_engine.prepare(backend, source=REPO, download_models=False, jobs=jobs,
                                  activate=False, probe=False)
    native = Path(result["binary"]).parents[1]
    (destination / "build.json").write_text(json.dumps({"schema": "riff.chatgpt.native-build.v1",
        "backend": backend, "build_directory": str(native), "runtime_commit": pins["runtime_commit"],
        "configuration": setup_engine.cmake_command(Path(str(native.parent / "audio.cpp")), native, backend)}, indent=2) + "\n")
    print("RIFF_NATIVE_BUILD=" + str(native))
    if os.environ.get("GITHUB_ENV"):
        with Path(os.environ["GITHUB_ENV"]).open("a") as stream:
            stream.write("RIFF_NATIVE_BUILD=" + str(native) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=["cpu", "metal"], required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("jobs must be positive")
    build(args.output.resolve(), args.backend, args.jobs)
