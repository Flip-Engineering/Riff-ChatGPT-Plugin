#!/usr/bin/env python3
"""Install a checksum-pinned CMake wheel into an isolated release-build venv."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
from build_media import fetch


def build(destination, target):
    if destination.exists():
        raise ValueError("Choose a fresh build-tool directory.")
    destination.mkdir(parents=True)
    pin = json.loads((Path(__file__).parent / "components.json").read_text())["cmake"][target]
    archive = destination / pin["archive"]
    fetch(pin, archive)
    environment = destination / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python3"
    subprocess.run([str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
                    "--no-deps", "--no-compile", str(archive)], check=True)
    (destination / "build.json").write_text(json.dumps(pin, indent=2) + "\n")
    executable_directory = environment / "bin"
    if os.environ.get("GITHUB_PATH"):
        with Path(os.environ["GITHUB_PATH"]).open("a") as stream:
            stream.write(str(executable_directory) + "\n")
    print(executable_directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=["linux-x86_64", "macos-arm64"], required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.platform)
