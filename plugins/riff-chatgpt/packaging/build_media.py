#!/usr/bin/env python3
"""Build Riff's small FFmpeg/media dependency set from existing desktop pins.

Runs on the target Linux or macOS release host. Artifacts carry the exact source
archives, build commands, receipts and copyright notices for redistribution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from riff_dependency import riff_root

REPO = riff_root()


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(pin, target):
    temporary = target.with_suffix(target.suffix + ".part")
    for attempt in range(4):
        if target.is_file():
            break
        received = temporary.stat().st_size if temporary.is_file() else 0
        if received > pin["bytes"]:
            raise ValueError("Component partial download exceeds its pinned size.")
        request = urllib.request.Request(pin["url"], headers={"Range": f"bytes={received}-"} if received else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            if received and response.status == 200:
                received = 0
            elif received and (response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {received}-")):
                raise ValueError("Component server returned an invalid resume range.")
            with temporary.open("ab" if received else "wb") as stream:
                shutil.copyfileobj(response, stream, 1024 * 1024)
        if temporary.stat().st_size == pin["bytes"]:
            temporary.replace(target)
            break
    if not target.is_file():
        raise ValueError("Component download was interrupted; its partial file has been retained.")
    if target.stat().st_size != pin["bytes"] or sha(target) != pin["sha256"]:
        raise ValueError("Component download failed pinned integrity checks: " + target.name)


def build(destination, jobs, resume=False):
    if destination.exists() and not resume:
        raise ValueError("Choose a fresh media build destination.")
    if not shutil.which("pkg-config"):
        raise ValueError("The release builder needs pkg-config. Install it on the build host before compiling media.")
    destination.mkdir(parents=True, exist_ok=resume)
    archives = destination / "sources"
    archives.mkdir(exist_ok=resume)
    prefix = destination / "install"
    prefix.mkdir(exist_ok=resume)
    components = json.loads((REPO / "desktop/components.json").read_text())
    flags = f"-O2 -ffile-prefix-map={destination}=riff-media -fdebug-prefix-map={destination}=riff-media"
    env = {**os.environ, "CFLAGS": flags, "CPPFLAGS": "-I" + str(prefix / "include"),
           "LDFLAGS": "-L" + str(prefix / "lib"), "PKG_CONFIG_PATH": str(prefix / "lib/pkgconfig")}
    commands = []
    for name in ("lame", "x264", "ffmpeg"):
        print("Building pinned " + name, flush=True)
        pin = components[name]
        archive = archives / pin["archive"]
        fetch(pin, archive)
        parent = destination / name
        if not parent.exists():
            parent.mkdir()
            with tarfile.open(archive) as tar:
                tar.extractall(parent, filter="data")
        roots = list(parent.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError("Unexpected media source layout.")
        source = roots[0]
        if name == "lame":
            arguments = ["--prefix=" + str(prefix), "--disable-shared", "--enable-static",
                         "--disable-frontend", "--disable-dependency-tracking"]
        elif name == "x264":
            arguments = ["--prefix=" + str(prefix), "--enable-static", "--disable-cli",
                         "--disable-opencl", "--extra-cflags=" + flags]
            if not shutil.which("nasm"):
                arguments.append("--disable-asm")
        else:
            arguments = ["--prefix=" + str(prefix), "--disable-shared", "--enable-static",
                         "--disable-debug", "--disable-doc", "--disable-ffplay", "--disable-network",
                         "--disable-autodetect", "--enable-gpl", "--enable-libx264", "--enable-libmp3lame",
                         "--enable-zlib", "--disable-everything", "--enable-protocol=file,pipe",
                         "--enable-demuxer=wav,image2pipe,image_png_pipe,mp3,mov,h264",
                         "--enable-muxer=mp4,mp3,wav,h264",
                         "--enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,png,mjpeg,mp3,aac,h264",
                         "--enable-encoder=libx264,aac,libmp3lame,pcm_s16le,pcm_f32le",
                         "--enable-parser=png,mjpeg,mpegaudio,aac,h264",
                         "--enable-filter=aresample,format,scale,anull,null", "--enable-swscale", "--enable-swresample",
                         "--extra-cflags=" + flags + " -I" + str(prefix / "include"),
                         "--extra-ldflags=-L" + str(prefix / "lib"), "--pkg-config-flags=--static"]
            if platform.system() == "Linux" and not shutil.which("nasm"):
                arguments.append("--disable-x86asm")
        for phase, command in (("configure", [str(source / "configure"), *arguments]),
                               ("build", ["make", f"-j{jobs}"]), ("install", ["make", "install"])):
            commands.append({"component": name, "phase": phase,
                             "command": [arg.replace(str(destination), "<build>") for arg in command]})
            with (destination / f"{name}-{phase}.log").open("w") as log:
                subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            if phase == "configure" and name == "ffmpeg":
                header = source / "config.h"
                header.write_text(header.read_text().replace(str(destination), "riff-media"))
        for file in source.iterdir():
            if file.is_file() and file.name.lower().startswith(("copying", "license")):
                shutil.copyfile(file, archives / (name + "-" + file.name))
    media = destination / "media"
    media.mkdir(exist_ok=resume)
    records = []
    for name in ("ffmpeg", "ffprobe"):
        target = media / name
        shutil.copy2(prefix / "bin" / name, target)
        subprocess.run(["strip", *(["-x"] if platform.system() == "Darwin" else []), str(target)], check=True)
        if platform.system() == "Darwin":
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(target)], check=True)
        records.append({"path": name, "bytes": target.stat().st_size, "sha256": sha(target)})
        subprocess.run([str(target), "-version"], check=True, stdout=subprocess.DEVNULL)
    receipt = {"schema": "riff.chatgpt.media.v1", "platform": platform.platform(),
               "components": {name: components[name] for name in ("ffmpeg", "x264", "lame")},
               "commands": commands, "files": records,
               "reproduction": "Run packaging/build_media.py on the target release host with desktop/components.json."}
    (destination / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(media, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--resume", action="store_true", help="Resume this builder's own interrupted output directory")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("jobs must be positive")
    build(args.output.resolve(), args.jobs, args.resume)
