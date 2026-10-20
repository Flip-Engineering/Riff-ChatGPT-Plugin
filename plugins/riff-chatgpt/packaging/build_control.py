#!/usr/bin/env python3
"""Build a relocatable ERTS release from Riff's locked installer/runtime sources."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from riff_dependency import riff_root

REPO = riff_root()


def copy_notices(project, destination):
    notices = destination / "control/licenses"
    notices.mkdir(exist_ok=True)
    pins = json.loads((Path(__file__).parent / "components.json").read_text())
    for pin in pins["control_notices"]:
        source = Path(__file__).parent / "notices" / pin["file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != pin["sha256"]:
            raise ValueError("A pinned runtime notice has changed.")
        shutil.copyfile(source, notices / pin["file"])
    for dependency in (project / "installer/deps").iterdir():
        if not dependency.is_dir():
            continue
        found = False
        for file in dependency.rglob("*"):
            if file.is_file() and re.match(r"^(LICENSE|LICENCE|COPYING|COPYRIGHT|NOTICE)([.-].*)?$", file.name, re.I):
                found = True
                target = notices / "dependencies" / dependency.name / file.relative_to(dependency)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
        if not found and dependency.name == "nimble_pool":
            target = notices / "dependencies/nimble_pool"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dependency / "README.md", target / "README-NOTICE.md")
            shutil.copyfile(project / "installer/deps/telemetry/LICENSE", target / "Apache-2.0.txt")
        elif not found:
            raise ValueError("The release dependency has no license notice: " + dependency.name)


def install_crypto(destination, crypto_build):
    receipt = json.loads((crypto_build / "openssl.json").read_text())
    pins = json.loads((REPO / "desktop/components.json").read_text())
    if receipt["component"] != pins["openssl"] or receipt["otp_crypto"]["component"] != pins["otp_crypto"]:
        raise ValueError("Build the pinned private OpenSSL/OTP component for the macOS control runtime.")
    for record in receipt["files"]:
        file = crypto_build / record["path"]
        if not file.resolve().is_relative_to(crypto_build.resolve()) or file.stat().st_size != record["bytes"] or hashlib.sha256(file.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("A private crypto component failed its integrity check.")
    target = destination / "control/lib" / ("crypto-" + pins["otp_crypto"]["crypto_version"]) / "priv"
    if not (target / "lib/crypto.so").is_file():
        raise ValueError("The control release does not match the pinned OTP crypto version.")
    shutil.copyfile(crypto_build / "crypto/libcrypto.3.dylib", target / "libcrypto.3.dylib")
    for name in ("crypto.so", "crypto_callback.so", "otp_test_engine.so"):
        shutil.copyfile(crypto_build / "crypto/nif" / name, target / "lib" / name)
    shutil.copytree(crypto_build / "crypto/licenses", destination / "control/licenses/crypto", dirs_exist_ok=True)
    shutil.copyfile(crypto_build / "openssl.json", destination / "control/licenses/crypto-build.json")
    return receipt


def build(destination, dependencies=None, crypto_build=None):
    if destination.exists():
        raise ValueError("Choose a fresh control build directory.")
    if sys.platform == "darwin" and not crypto_build:
        raise ValueError("The macOS release requires --crypto-build from desktop/build_openssl.exs.")
    project = destination / "project"
    project.mkdir(parents=True)
    for name in ("sources.json", "VERSION"):
        shutil.copyfile(REPO / name, project / name)
    for name in ("installer", "runtime"):
        shutil.copytree(REPO / name, project / name,
                        ignore=shutil.ignore_patterns("_build", "deps", ".build", ".cache", "__pycache__", ".DS_Store"))
    if dependencies:
        shutil.copytree(dependencies, project / "installer/deps", symlinks=False,
                        ignore=shutil.ignore_patterns("_build", ".git", "__pycache__"))
    env = {**os.environ, "MIX_ENV": "prod", "RELEASE_DISTRIBUTION": "none", "LANG": "C.UTF-8",
           "ERL_FLAGS": "+S 2:2 +SDcpu 1 +SDio 1"}
    commands = []
    if not dependencies:
        commands.append(["mix", "deps.get", "--check-locked"])
    commands += [["mix", "deps.compile"], ["mix", "compile"],
                 ["mix", "release", "riff_installer", "--path", str(destination / "control")]]
    with (destination / "build.log").open("w") as log:
        for command in commands:
            subprocess.run(command, cwd=project / "installer", env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    copy_notices(project, destination)
    subprocess.run(["elixir", str(Path(__file__).parent / "prepare_control.exs"),
                    str(destination / "control"), str(project)], env=env, check=True)
    crypto = install_crypto(destination, crypto_build) if crypto_build else None
    executable = destination / "control/bin/riff_installer"
    result = subprocess.run([str(executable), "eval", "Riff.Runtime.SchedulerPort.main()"],
                            input='{"op":"capabilities"}\n', capture_output=True, text=True, env=env, check=True)
    capabilities = json.loads(result.stdout)
    if capabilities.get("artifacts", {}).get("acoustic") != "riff.yue2.acoustic.v1":
        raise ValueError("The control release did not advertise its artifact contract.")
    inputs = {}
    for name in ("installer", "runtime"):
        for file in sorted((REPO / name).rglob("*")):
            if file.is_file() and file.suffix in (".ex", ".exs", ".rs", ".eex", ".lock") and not any(part in {"deps", "_build", ".cache", ".build"} for part in file.parts):
                inputs[file.relative_to(REPO).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    versions = subprocess.check_output(["elixir", "--version"], env=env, text=True)
    receipt = {"schema": "riff.chatgpt.control.v1", "versions": versions,
               "rust": subprocess.check_output(["rustc", "--version"], env=env, text=True).strip(),
               "inputs_sha256": inputs, "capabilities": capabilities,
               "private_crypto": crypto,
               "mix_lock_sha256": hashlib.sha256((REPO / "installer/mix.lock").read_bytes()).hexdigest()}
    (destination / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(destination / "control")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, help="Existing locked dependency sources; otherwise download through Hex")
    parser.add_argument("--crypto-build", type=Path, help="Required on macOS: output of desktop/build_openssl.exs")
    args = parser.parse_args()
    build(args.output.resolve(), args.dependencies, args.crypto_build)
