#!/usr/bin/env python3
"""Assemble a self-contained Riff MCP plugin from verified platform components.

The resulting package has an actual interpreter/engine/control/media entrypoint.
Music models are separately downloaded into the persistent managed workspace.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
PLUGIN = PROJECT / "plugins/riff-chatgpt"
sys.path.insert(0, str(PLUGIN / "scripts"))
from riff_dependency import riff_root
ROOT = riff_root()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755 if os.access(source, os.X_OK) else 0o644)


def copy_tree(source, target, omit=()):
    source = source.resolve()
    for file in sorted(source.rglob("*")):
        relative = file.relative_to(source)
        if any(part in {"__pycache__", ".git", ".DS_Store", *omit} for part in relative.parts):
            continue
        if file.is_dir():
            continue
        if not file.resolve().is_relative_to(source) or not file.is_file():
            raise ValueError("Escaping or nonregular component file: " + str(file))
        copy_file(file, target / relative)


def records(root):
    return [{"path": file.relative_to(root).as_posix(), "bytes": file.stat().st_size,
             "sha256": sha(file), "executable": os.access(file, os.X_OK)}
            for file in sorted(root.rglob("*")) if file.is_file() and file.name != "bundle-manifest.json"]


def native_proof(build, destination):
    helper = module(ROOT / "scripts/check_native_lora.py", "riff_native_plugin_proof")
    source = Path(helper.cache(build, "CMAKE_HOME_DIRECTORY"))
    pins = json.loads((ROOT / "sources.json").read_text())
    with tempfile.TemporaryDirectory(prefix="riff-plugin-native-") as directory:
        temporary = Path(directory)
        patches, environment = helper.verify_source(source, pins, temporary)
        fixture = temporary / "metadata"
        helper.metadata_fixture(fixture)
        helper.verify_capabilities(build / "bin/audiocpp_cli", fixture, pins["native_capabilities"])
        tree = subprocess.check_output(["git", "-C", str(source), "write-tree"], env=environment, text=True).strip()
    cache = (build / "CMakeCache.txt").read_text()
    if "GGML_NATIVE:BOOL=ON" in cache:
        raise ValueError("A distributable engine must be built without host-native CPU specialization.")
    features = [flag for key, flag in (("GGML_AVX2", "avx2"), ("GGML_FMA", "fma"),
                                     ("GGML_BMI2", "bmi2"), ("GGML_F16C", "f16c"))
                if key + ":BOOL=ON" in cache]
    receipt = {"schema": "riff.chatgpt.native.v1", "runtime_commit": pins["runtime_commit"],
               "patched_tree": tree, "sources_sha256": sha(ROOT / "sources.json"),
               "binary_sha256": sha(build / "bin/audiocpp_cli"),
               "capabilities": pins["native_capabilities"], "cpu_features": features,
               "cmake_cache_sha256": sha(build / "CMakeCache.txt")}
    (destination / "native.json").write_text(json.dumps(receipt, indent=2) + "\n")
    for file in source.rglob("*"):
        if file.is_file() and file.name.lower() in {"license", "license.md", "license.txt", "copying", "notice", "notice.md", "copyright"} and ".git" not in file.parts:
            copy_file(file, destination / "native-notices" / file.relative_to(source))
    return receipt


def linux_dependencies(package):
    """Carry non-libc ELF dependencies; the documented host glibc remains an OS ABI."""
    libraries = package / "runtime/lib"
    libraries.mkdir(exist_ok=True)
    excluded = re.compile(r"^(?:ld-linux|libc\.|libm\.|libpthread\.|libdl\.|librt\.|libutil\.|libresolv\.|libnss_)")
    dependencies = {}
    candidates = []
    for file in (package / "runtime").rglob("*"):
        if file.is_file():
            with file.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    candidates.append(file)
    for file in candidates:
        result = subprocess.run(["ldd", str(file)], capture_output=True, text=True)
        if "not found" in result.stdout:
            raise ValueError("An input binary has unresolved libraries: " + str(file))
        for name, path in re.findall(r"^\s*(\S+)\s+=>\s+(/\S+)", result.stdout, re.M):
            dependency = Path(path).resolve()
            if excluded.match(name) or dependency.is_relative_to(package.resolve()):
                continue
            target = libraries / name
            if target.exists() and sha(target) != sha(dependency):
                raise ValueError("Conflicting runtime library: " + name)
            if not target.exists():
                copy_file(dependency, target)
            dependencies[name] = {"source_name": dependency.name, "sha256": sha(target)}
            # These runtime libraries are typically zlib, OpenSSL, ncurses and
            # GNU runtime-exception libraries; retain installed copyright notices.
            owner = subprocess.run(["dpkg-query", "-S", str(dependency)], capture_output=True, text=True)
            if owner.returncode == 0:
                owner_name = owner.stdout.split(": ", 1)[0].split(":", 1)[0]
                notice = Path("/usr/share/doc") / owner_name / "copyright"
                if notice.is_file():
                    copy_file(notice, package / "notices/system-libraries" / (owner_name + ".txt"))
    return dependencies


def macos_dependencies(package):
    """Close every Mach-O dependency inside the package, then sign ad hoc."""
    libraries = package / "runtime/lib"
    libraries.mkdir(exist_ok=True)
    dependencies, inspected, original_hashes = {}, set(), {}
    magic = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
             b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
    candidates = []
    for file in (package / "runtime").rglob("*"):
        if file.is_file():
            with file.open("rb") as stream:
                if stream.read(4) in magic:
                    candidates.append(file)

    def listing(file, option):
        return subprocess.check_output(["/usr/bin/otool", option, str(file)], text=True)

    def expand(value, owner):
        if value == "@loader_path" or value == "@executable_path":
            return owner
        for token in ("@loader_path/", "@executable_path/"):
            if value.startswith(token):
                return (owner / value[len(token):]).resolve()
        return Path(value).resolve() if value.startswith("/") else None

    for file in candidates:
        if file in inspected:
            continue
        inspected.add(file)
        architectures = subprocess.check_output(["/usr/bin/lipo", "-archs", str(file)], text=True).split()
        if "arm64" not in architectures:
            raise ValueError("The macOS runtime contains a non-ARM64 binary: " + str(file))
        identities = {line.strip() for line in listing(file, "-D").splitlines()[1:]}
        rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", listing(file, "-l"), re.S)
        for line in listing(file, "-L").splitlines()[1:]:
            old = line.strip().split(" (", 1)[0]
            if old in identities or old.startswith(("/usr/lib/", "/System/Library/")):
                continue
            possible = []
            if old.startswith("@rpath/"):
                for rpath in rpaths:
                    directory = expand(rpath, file.parent)
                    if directory:
                        possible.append(directory / old[len("@rpath/"):])
            else:
                possible = [expand(old, file.parent)]
            existing = [path.resolve() for path in possible if path and path.is_file()]
            if not existing and old.startswith("@"):
                # An executable's rpath can serve an extension module. Resolve
                # only a unique already-bundled library, then make it explicit.
                matches = list((package / "runtime").rglob(Path(old).name))
                existing = [matches[0].resolve()] if len(matches) == 1 else []
            if not existing:
                raise ValueError("Missing Mach-O dependency: " + old)
            dependency = existing[0]
            if dependency.is_relative_to(package):
                target = dependency
            else:
                target = libraries / dependency.name
                digest = sha(dependency)
                if target.name in original_hashes and original_hashes[target.name] != digest:
                    raise ValueError("Conflicting Mach-O dependency: " + dependency.name)
                if not target.exists():
                    copy_file(dependency, target)
                    original_hashes[target.name] = digest
                    candidates.append(target)
                dependencies[target.name] = {"source_name": dependency.name, "input_sha256": digest}
            replacement = "@loader_path/" + os.path.relpath(target, file.parent)
            if old != replacement:
                subprocess.run(["/usr/bin/install_name_tool", "-change", old, replacement, str(file)], check=True)
        if identities:
            subprocess.run(["/usr/bin/install_name_tool", "-id", "@loader_path/" + file.name, str(file)], check=True)
        for rpath in rpaths:
            if rpath.startswith("/") and not Path(rpath).is_relative_to(package):
                subprocess.run(["/usr/bin/install_name_tool", "-delete_rpath", rpath, str(file)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(file)], check=True, capture_output=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(file)], check=True, capture_output=True)
    for file in inspected:
        identities = {line.strip() for line in listing(file, "-D").splitlines()[1:]}
        for line in listing(file, "-L").splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if dependency in identities or dependency.startswith(("/usr/lib/", "/System/Library/")):
                continue
            resolved = expand(dependency, file.parent)
            if not resolved or not resolved.is_relative_to(package) or not resolved.is_file():
                raise ValueError("A relocated Mach-O dependency escaped its package: " + dependency)
    for name, record in dependencies.items():
        record["sha256"] = sha(libraries / name)
    return dependencies


def build(args):
    target = args.platform
    # Input components are built on the target host, not cross-copied.
    actual = ("macos" if sys.platform == "darwin" else sys.platform) + "-" + {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    if target != actual:
        raise ValueError(f"Build {target} packages on a {target} host, not {actual}.")
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError("Choose a fresh package output directory.")
    package = destination / "riff-chatgpt"
    package.mkdir(parents=True)
    notices = package / "notices"
    notices.mkdir()
    for name in ("plugin.json", "mcp.json"):
        copy_file(PLUGIN / name, package / name)
    for name in ("server", "skills", "assets"):
        copy_tree(PLUGIN / name, package / name)
    sys.path.insert(0, str(ROOT))
    release = module(ROOT / "scripts/package_release.py", "riff_curated_release")
    source_files = release.public_files()
    for file in source_files:
        # Runtime clients need the source application, web assets and provenance;
        # tests/build scripts stay in the repository and component source receipts.
        relative = file.relative_to(ROOT)
        if relative.parts[0] not in {"tests", ".github", "site", "desktop"}:
            copy_file(file, package / "riff" / relative)
    ui_builder = module(PLUGIN / "scripts/build_ui.py", "riff_ui_bundle")
    ui_builder.build(ROOT / "web", package / "dist/studio.html")
    copy_tree(args.python_build / "python", package / "runtime/python")
    # Riff serves a web studio. The unused Tk extension requires an X11/Tk
    # desktop installation on Linux, which is not part of this local MCP app.
    for standard_library in (package / "runtime/python/lib").glob("python3.*"):
        for name in ("tkinter", "idlelib"):
            shutil.rmtree(standard_library / name, ignore_errors=True)
        for file in (standard_library / "lib-dynload").glob("_tkinter*"):
            file.unlink()
    # Do not ship generated pip shebang commands that reference the build host.
    for file in (package / "runtime/python/bin").iterdir():
        if file.is_file() and file.name != "python3":
            file.unlink()
    copy_file(args.engine_build / "bin/audiocpp_cli", package / "runtime/engine/audiocpp_cli")
    copy_tree(args.media_build / "media", package / "runtime/media")
    copy_tree(args.control_build / "control", package / "runtime/control")
    (package / "runtime/control/releases/COOKIE").unlink(missing_ok=True)
    copy_tree(args.media_build / "sources", notices / "media-sources")
    copy_file(ROOT / "LICENSE", package / "LICENSE")
    copy_file(ROOT / "NOTICE.md", notices / "Riff-NOTICE.md")
    (package / "README.md").write_text(
        "# Riff for ChatGPT\n\n"
        "This platform package includes the Riff studio, native YuE2 engine, Python, audio/video tools and score runtime. "
        "Install it in a host that supports local stdio MCP plugins and MCP Apps UI resources, using plugin.json and mcp.json. "
        "The public ChatGPT browser alone cannot execute this local native runtime.\n\n"
        "Open Riff and choose Download music models to fetch the pinned, separately licensed YuE2 files into your private workspace. "
        "Downloads show progress, support cancellation/resume, and activate only after size and SHA-256 verification. "
        "The model card is https://huggingface.co/m-a-p/YuE2-3B. No compiler or language runtime installation is required.\n\n"
        "Writing can use ChatGPT, phrases, or an OpenRouter provider configured in the studio. This package does not include the MLX writer. "
        "On Linux, credentials remain in memory for the session when an OS keyring is unavailable. "
        "On macOS they use a separate Riff ChatGPT Keychain service.\n\n"
        "Documentation and validation status: https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin\n"
        "Runtime build and support details: https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/blob/main/docs/chatgpt-plugin-runtime.md\n\n"
        "The bundle-manifest.json and notices/ receipts describe these exact package bytes. "
        "Actual host registration and native performance are separate from package and protocol validation.\n"
    )
    for component, directory in (("python", args.python_build), ("media", args.media_build), ("control", args.control_build)):
        copy_file(directory / "build.json", notices / (component + ".json"))
    # The pinned standalone Python includes pip's vendored Mozilla trust store.
    certificates = list((package / "runtime/python").rglob("cacert.pem"))
    if not certificates:
        raise ValueError("The pinned Python runtime did not include a public CA trust store.")
    copy_file(certificates[0], package / "runtime/certificates.pem")
    proof = native_proof(args.engine_build, notices)
    libraries = linux_dependencies(package) if sys.platform == "linux" else macos_dependencies(package)
    version = json.loads((package / "plugin.json").read_text())["version"]
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    changed = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    config = {"schema": "riff.chatgpt.runtime.v1", "platform": target,
              "backend": "metal" if target == "macos-arm64" else "cpu",
              "plugin_version": version, "riff_version": (ROOT / "VERSION").read_text().strip(),
              "base_commit": current, "riff_commit": current,
              "plugin_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip(),
              "source_has_local_changes": changed,
              "cpu_features": proof["cpu_features"] if sys.platform == "linux" else [],
              "system_libraries": libraries, "native": proof,
              "glibc_build_host": platform.libc_ver()[1] if sys.platform == "linux" else None,
              "minimum_macos": "15.0" if sys.platform == "darwin" else None,
              "models_included": False}
    (package / "runtime/runtime.json").write_text(json.dumps(config, indent=2) + "\n")
    contents = records(package)
    (package / "bundle-manifest.json").write_text(json.dumps({"schema": "riff.chatgpt.bundle.v1",
        "platform": target, "plugin_version": version, "files": contents}, indent=2) + "\n")
    environment = {**os.environ, "PATH": "/nonexistent", "PYTHONPATH": "", "PYTHONHOME": ""}
    result = subprocess.run([str(package / "runtime/python/bin/python3"), "-I", "-B", str(package / "server/launch.py"), "--check"],
                            text=True, capture_output=True, env=environment, check=True, timeout=120)
    check = json.loads(result.stdout)
    (destination / "acceptance.json").write_text(json.dumps(check, indent=2) + "\n")
    if not args.no_archive:
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT))
        archive = destination / f"riff-chatgpt-{version}-{target}.tar.gz"
        with archive.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=epoch) as compressed, tarfile.open(fileobj=compressed, mode="w") as tar:
            for file in sorted(package.rglob("*")):
                if not file.is_file():
                    continue
                item = tar.gettarinfo(str(file), arcname="riff-chatgpt/" + file.relative_to(package).as_posix())
                item.mtime, item.uid, item.gid, item.uname, item.gname = epoch, 0, 0, "", ""
                item.mode = 0o755 if os.access(file, os.X_OK) else 0o644
                with file.open("rb") as stream:
                    tar.addfile(item, stream)
        (destination / "SHA256SUMS").write_text(sha(archive) + "  " + archive.name + "\n")
        print(archive)
    print(json.dumps({"package": str(package), "files": len(contents), "acceptance": check}))
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["linux-x86_64", "macos-arm64"], required=True)
    parser.add_argument("--engine-build", type=Path, required=True)
    parser.add_argument("--python-build", type=Path, required=True)
    parser.add_argument("--media-build", type=Path, required=True)
    parser.add_argument("--control-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-archive", action="store_true")
    build(parser.parse_args())
