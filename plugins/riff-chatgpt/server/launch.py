"""Entrypoint executed by the interpreter carried in a Riff plugin package."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


def workspace_default():
    if os.environ.get("RIFF_PLUGIN_WORKSPACE"):
        return Path(os.environ["RIFF_PLUGIN_WORKSPACE"]).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Riff ChatGPT"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "riff-chatgpt"


def validate_bundle(root, *, host_python=False):
    from runtime import file_hash
    config_path, manifest_path = root / "runtime/runtime.json", root / "bundle-manifest.json"
    if not config_path.is_file() or not manifest_path.is_file():
        raise ValueError("Incomplete Riff plugin package: build a platform distribution before installing it.")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "riff.chatgpt.bundle.v1" or not isinstance(manifest.get("files"), list):
        raise ValueError("Unsupported Riff bundle manifest.")
    seen = set()
    for record in manifest["files"]:
        relative = record["path"]
        file = root / relative
        if relative in seen or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Invalid Riff bundle path.")
        seen.add(relative)
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()) or not file.is_file():
            raise ValueError("Missing or unsafe Riff component: " + relative)
        if file.stat().st_size != record["bytes"] or file_hash(file) != record["sha256"]:
            raise ValueError("Riff component integrity check failed: " + relative)
        if record.get("executable") and not os.access(file, os.X_OK):
            raise ValueError("Riff component is not executable: " + relative)
    required = {"runtime/runtime.json", "server/launch.py", "server/main.py", "server/adapter.py",
                "server/runtime.py", "riff/studio.py", "riff/sources.json", "dist/studio.html",
                "runtime/engine/audiocpp_cli",
                "runtime/media/ffmpeg", "runtime/media/ffprobe", "runtime/control/bin/riff_installer"}
    if not host_python:
        required.add("runtime/python/bin/python3")
    else:
        required.update({"server/cloud.py", "server/inprocess.py"})
    if not required.issubset(seen):
        raise ValueError("The plugin bundle is missing required runtime components.")
    config = json.loads(config_path.read_text())
    machine = {"AMD64": "x86_64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    actual = ("macos" if sys.platform == "darwin" else sys.platform) + "-" + machine
    if config.get("platform") != actual:
        raise ValueError(f"This Riff package is for {config.get('platform')}; this host is {actual}.")
    if host_python and (config.get("execution") != "chatgpt-cloud" or sys.version_info < (3, 12)):
        raise ValueError("Cloud execution requires a cloud package and Python 3.12 or newer.")
    if not host_python and Path(sys.executable).resolve() != (root / "runtime/python/bin/python3").resolve():
        raise ValueError("Launch Riff with the Python interpreter included in its plugin package.")
    if sys.platform == "linux":
        expected = tuple(int(part) for part in config["glibc_build_host"].split(".")[:2])
        name, version = platform.libc_ver()
        current = tuple(int(part) for part in version.split(".")[:2]) if version else ()
        if name != "glibc" or current < expected:
            raise ValueError("This Linux Riff package requires glibc " + config["glibc_build_host"] + " or later.")
        required_features = set(config.get("cpu_features", []))
        if required_features:
            flag_sets = [set(line.split(":", 1)[1].split()) for line in Path("/proc/cpuinfo").read_text().splitlines()
                         if line.startswith("flags") and ":" in line]
            available = set.intersection(*flag_sets) if flag_sets else set()
            if not required_features.issubset(available):
                raise ValueError("This Riff package requires CPU features: " + ", ".join(sorted(required_features)) + ".")
    if sys.platform == "darwin":
        current = tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
        minimum = tuple(int(part) for part in config["minimum_macos"].split(".")[:2])
        if current < minimum:
            raise ValueError("This Riff package requires macOS " + config["minimum_macos"] + " or later.")
    return config


def environment(root, workspace):
    os.environ["RIFF_PLUGIN_BUNDLE_ROOT"] = str(root)
    os.environ["RIFF_HOME"] = str(workspace)
    os.environ["RIFF_RUNTIME_CONTROL"] = str(root / "runtime/control/bin/riff_installer")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    for name in ("PYTHONPATH", "PYTHONHOME", "RIFF_INSTALL_ROOT", "RIFF_WRITER_PYTHON", "RIFF_WRITER_MODEL"):
        os.environ.pop(name, None)
    # Only bundled media/interpreters are selected. Basic OS shell utilities are
    # needed by the packaged ERTS launcher; no language runtime is looked up.
    os.environ["PATH"] = os.pathsep.join([str(root / "runtime/media"), str(root / "runtime/python/bin"), "/usr/bin", "/bin"])
    if sys.platform == "linux":
        os.environ["LD_LIBRARY_PATH"] = str(root / "runtime/lib")
    if (root / "runtime/certificates.pem").is_file():
        os.environ.setdefault("SSL_CERT_FILE", str(root / "runtime/certificates.pem"))
    # Keep host-configured trust (for example a managed HTTPS proxy) and the
    # standard OS certificate directory. Private CAs never enter the package,
    # and hosts without an OS store still have the bundled public roots.
    if sys.platform == "linux" and "SSL_CERT_DIR" not in os.environ and Path("/etc/ssl/certs").is_dir():
        os.environ["SSL_CERT_DIR"] = "/etc/ssl/certs"
    os.environ["RELEASE_DISTRIBUTION"] = "none"
    # Distribution is disabled. Do not ship or reuse a build-machine Erlang
    # cookie; provide a fresh process-only value to the release shell launcher.
    os.environ["RELEASE_COOKIE"] = secrets.token_hex(32)
    os.environ.setdefault("ERL_FLAGS", "+S 2:2 +SDcpu 1 +SDio 1")


def check_media(root):
    """Exercise the codecs used by real video exports and audio reviews."""
    import array
    import importlib.util
    import math
    import struct
    import tempfile
    import wave
    import zlib
    spec = importlib.util.spec_from_file_location("riff_media_acceptance", root / "riff/video.py")
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)
    ffmpeg, ffprobe = (str(root / "runtime/media" / name) for name in ("ffmpeg", "ffprobe"))
    with tempfile.TemporaryDirectory(prefix="riff-media-check-") as folder:
        directory = Path(folder)
        samples = array.array("h", [round(3000 * math.sin(2 * math.pi * 440 * index / 48000)) for index in range(48000)])
        if sys.byteorder != "little":
            samples.byteswap()
        audio = directory / "source.wav"
        with wave.open(str(audio), "wb") as output:
            output.setparams((1, 2, 48000, 48000, "NONE", "not compressed"))
            output.writeframes(samples.tobytes())

        def chunk(name, value):
            return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xffffffff)

        frame = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) +
                 chunk(b"IDAT", zlib.compress((b"\0" + bytes((30, 150, 100)) * 32) * 32)) + chunk(b"IEND", b""))
        movie = directory / "recording.mp4"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-f", "image2pipe", "-framerate", "2", "-i", "pipe:0",
                        "-ss", "0", "-t", "1", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                        *video.VIDEO_CODEC, "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(movie)],
                       input=frame * 2, capture_output=True, check=True, timeout=30)
        mp3 = directory / "recording.mp3"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(audio),
                        "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)],
                       capture_output=True, check=True, timeout=30)
        records = {}
        for name, file, expected in (("video", movie, {"h264", "aac"}), ("review_audio", mp3, {"mp3"})):
            output = subprocess.check_output([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(file)], text=True, timeout=30)
            info = json.loads(output)
            codecs = {stream["codec_name"] for stream in info["streams"]}
            if codecs != expected or not .95 <= float(info["format"]["duration"]) <= 1.2:
                raise ValueError("Bundled media codec acceptance failed: " + name)
            records[name] = {"codecs": sorted(codecs), "bytes": file.stat().st_size,
                             "duration_seconds": float(info["format"]["duration"])}
        return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=workspace_default())
    parser.add_argument("--check", action="store_true", help="Check packaged components without opening a studio workspace")
    args = parser.parse_args()
    config = validate_bundle(ROOT)
    workspace = args.workspace.expanduser().resolve()
    if workspace.is_relative_to(ROOT):
        raise ValueError("Riff's persistent workspace must be separate from its replaceable plugin package.")
    environment(ROOT, workspace)
    if args.check:
        import sqlite3, ssl
        sqlite3.connect(":memory:").close()
        checks = {}
        for name in ("ffmpeg", "ffprobe"):
            result = subprocess.run([str(ROOT / "runtime/media" / name), "-version"], capture_output=True, text=True, check=True)
            checks[name] = result.stdout.splitlines()[0]
        checks["media"] = check_media(ROOT)
        result = subprocess.run([str(ROOT / "runtime/control/bin/riff_installer"), "eval", "Riff.Runtime.SchedulerPort.main()"],
                                input='{"op":"capabilities"}\n', capture_output=True, text=True, check=True, timeout=30)
        checks["control"] = json.loads(result.stdout)
        if checks["control"].get("state") != "capabilities":
            raise ValueError("The packaged score runtime did not respond.")
        print(json.dumps({"status": "ready", "platform": config["platform"], "backend": config["backend"],
                          "python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION, "checks": checks}))
        return
    from main import main as serve_main
    sys.argv = [sys.argv[0], "--riff-root", str(ROOT / "riff"), "--workspace", str(workspace),
                "--ui-file", str(ROOT / "dist/studio.html")]
    serve_main()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Riff could not start: {error}", file=sys.stderr)
        raise SystemExit(1)
