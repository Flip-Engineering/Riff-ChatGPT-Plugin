#!/usr/bin/env python3
"""Bundle the complete original Riff studio as one MCP Apps HTML resource.

Upstream HTML, CSS, JavaScript, notation vendor, images and video worker are read
unchanged. Explicit, counted build-time patches replace browser HTTP transports,
file downloads and history writes with the host bridge. The receipt records every
source hash, the source Git commit, applied patches and final bundle hash.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
from html.parser import HTMLParser
from html import escape
import json
import mimetypes
from pathlib import Path
import re
import subprocess

BASE = Path(__file__).resolve().parents[1]


def asset(root: Path, reference: str) -> Path:
    if not reference or any(x in reference for x in (":", "?", "#", "%", "\\")) or ".." in reference.split("/"):
        raise ValueError(f"Unsupported asset reference: {reference!r}")
    path = (root / reference.lstrip("/")).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or escaping asset: {reference!r}")
    return path


def script_tag(text: str) -> str:
    return "<script>" + re.sub(r"</script", r"<\\/script", text, flags=re.I) + "</script>"


def replace_once(text: str, before: str, after: str, name: str) -> str:
    if text.count(before) != 1:
        raise ValueError(f"Riff {name} adapter point changed; review before rebundling.")
    return text.replace(before, after)


def patch_app(text: str) -> str:
    text = replace_once(text, "const response = await fetch(path, options);",
                        "const response = await window.RiffHost.fetch(path, options);", "JSON API")
    text = replace_once(text, "selected = track;\n      audio.src = `/api/tracks/${id}/audio`;",
                        "const pluginAudioUrl = await window.RiffHost.audioUrl(id);\n"
                        "      if (request !== selectionRequest) return;\n"
                        "      selected = track;\n"
                        "      window.RiffHost.assignMedia(audio, pluginAudioUrl, `/api/tracks/${id}/audio`);", "audio playback")
    text = replace_once(text, "let preferred = window.RiffUpdate?.preferredTrack() || new URL(location.href).searchParams.get(\"recording\");",
                        "let preferred = window.RiffHost.preferredTrack() || window.RiffUpdate?.preferredTrack() || new URL(location.href).searchParams.get(\"recording\");", "initial recording")
    text = replace_once(text, "function listeningLink(id) {\n  const url = new URL(location.href);\n  url.searchParams.set(\"recording\", id);\n  url.hash = \"studio\";\n  return url.href;\n}",
                        "function listeningLink(id) { return window.RiffHost.recordingReference(id); }", "recording reference")
    text = text.replace('notify("Listening link copied.");', 'notify("Recording reference copied.");')
    if text.count('history.replaceState(null, "", ') != 3:
        raise ValueError("Riff history adapter points changed; review before rebundling.")
    text = text.replace('history.replaceState(null, "", ', 'window.RiffHost.replaceHistory(')
    text = replace_once(text, '["phrases", "openrouter"].includes(recipe.idea_engine) ? recipe.idea_engine : "ai"',
                        '["phrases", "chatgpt"].includes(recipe.idea_engine) ? recipe.idea_engine : "chatgpt"', "ChatGPT writer selection")
    text = replace_once(text, '$("#idea-engine").value !== "openrouter"', '$("#idea-engine").value !== "chatgpt"', "ChatGPT writer hint")
    return text


class Bundler(HTMLParser):
    def __init__(self, root: Path, *, enforce_app=True):
        super().__init__(convert_charrefs=False)
        self.root, self.out, self.skip_script = root, [], False
        self.patched_app, self.enforce_app, self.assets = False, enforce_app, {}
        self.deferred_scripts, self.patches = [], []

    def read_bytes(self, reference):
        file = asset(self.root, reference)
        data = file.read_bytes()
        self.assets[file.relative_to(self.root).as_posix()] = hashlib.sha256(data).hexdigest()
        return data

    def read(self, reference):
        return self.read_bytes(reference).decode("utf-8")

    def data_url(self, reference):
        mime = mimetypes.guess_type(reference)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise ValueError(f"Non-image asset needs an explicit bundling policy: {reference}")
        return f"data:{mime};base64," + base64.b64encode(self.read_bytes(reference)).decode()

    def patch_script(self, path, code):
        filename = path.lstrip("/")
        if filename == "app.js":
            code = patch_app(code); self.patched_app = True
            self.patches.extend(["JSON gateway", "WAV/A-B playback", "recording deep link", "sandbox history"])
        elif filename == "video.js":
            if len(re.findall(r"(?<![\w.])fetch\(", code)) != 2:
                raise ValueError("Riff video transport adapter points changed.")
            code = re.sub(r"(?<![\w.])fetch\(", "window.RiffHost.fetch(", code)
            code = replace_once(code, 'new Worker("/video-encoder.js")',
                                'window.RiffHost.createWorker("video-encoder.js")', "video worker")
            code = replace_once(code, "download.click();", "window.RiffHost.downloadLink(download).catch(error => notify(error.message));", "MP4 download")
            self.patches.extend(["video frame uploads", "bundled video worker", "MP4 download"])
        elif filename == "loras.js":
            if len(re.findall(r"(?<![\w.])fetch\(", code)) != 1:
                raise ValueError("Riff LoRA import adapter point changed.")
            code = re.sub(r"(?<![\w.])fetch\(", "window.RiffHost.fetch(", code)
            code = replace_once(code, 'src="${escape(mediaURL(detail, fileName(file)))}"',
                                'data-riff-media-path="${escape(mediaURL(detail, fileName(file)))}"', "LoRA preview")
            self.patches.extend(["LoRA binary import", "LoRA media preview"])
        elif filename == "controls.js":
            code = replace_once(code, "Object.fromEntries(Object.entries(engineFields).map(",
                                "Object.fromEntries(Object.entries(engineFields).filter(([key]) => key === \"threads\").map(",
                                "managed engine tuning")
            self.patches.append("managed engine tuning")
        elif filename == "review.js":
            code = replace_once(code, 'notify("Key removed from macOS Keychain.");',
                                'notify("Review key removed.");', "credential removal wording")
        if filename in ("app.js", "controls.js", "review.js", "score.js"):
            code = replace_once(code, "link.click();", "window.RiffHost.downloadLink(link).catch(error => notify(error.message));", filename + " export")
            code = replace_once(code, "URL.createObjectURL(", "window.RiffHost.createObjectURL(", filename + " local Blob")
            code = replace_once(code, "URL.revokeObjectURL(", "window.RiffHost.revokeObjectURL(", filename + " Blob cleanup")
            self.patches.append(filename + " local file export")
        return code

    def handle_decl(self, decl): self.out.append("<!" + decl + ">")
    def handle_comment(self, data): self.out.append("<!--" + data + "-->")
    def handle_entityref(self, name): self.out.append("&" + name + ";")
    def handle_charref(self, name): self.out.append("&#" + name + ";")
    def handle_data(self, data):
        if not self.skip_script: self.out.append(data)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "base": raise ValueError("Base URLs are not permitted in a bundled Riff UI.")
        if tag == "script" and values.get("src"):
            if values.get("type") == "module": raise ValueError("Module script needs a module-aware build.")
            code = self.patch_script(values["src"], self.read(values["src"]))
            script = script_tag(code)
            if "defer" in values:
                self.deferred_scripts.append(script)
            elif "async" in values:
                raise ValueError("Async scripts need explicit order review.")
            else:
                self.out.append(script)
            self.skip_script = True
            return
        if tag == "link" and values.get("rel") == "stylesheet":
            css = self.read(values["href"])
            if "@import" in css: raise ValueError("CSS imports need explicit bundling.")
            def replace_url(match):
                ref = match[1].strip().strip("\"'")
                if ref.startswith("data:") or ref.startswith("#"): return match.group(0)
                return 'url("' + self.data_url(ref) + '")'
            css = re.sub(r"url\(([^)]+)\)", replace_url, css)
            self.out.append("<style>" + css.replace("</style", "<\\/style") + "</style>")
            return
        if tag == "link" and values.get("rel") in ("manifest", "preload", "prefetch", "preconnect", "dns-prefetch"):
            return
        if tag in ("iframe", "object", "embed"):
            raise ValueError("Nested embedded content needs explicit review.")
        converted = []
        for key, value in attrs:
            if key.lower().startswith("on"):
                raise ValueError("Inline event handler needs explicit review.")
            if key in ("src", "href") and value and ((tag == "img" and key == "src") or (tag == "link" and "icon" in (values.get("rel") or ""))):
                value = self.data_url(value)
            converted.append(key if value is None else key + '="' + escape(value, quote=True) + '"')
        self.out.append("<" + tag + (" " + " ".join(converted) if converted else "") + ">")
        if tag == "head":
            bridge = (BASE / "web/host.js").read_text()
            worker = {}
            if (self.root / "video-encoder.js").is_file():
                worker["video-encoder.js"] = base64.b64encode(self.read_bytes("video-encoder.js")).decode()
            self.out.append(script_tag(bridge + "\nwindow.RiffHost = new window.RiffBridge(window);\nwindow.RiffHost.assets = " + json.dumps(worker) + ";"))

    def handle_endtag(self, tag):
        if tag == "script" and self.skip_script:
            self.skip_script = False
            return
        if tag == "body":
            self.out.extend(self.deferred_scripts)
            self.deferred_scripts = []
            if self.enforce_app:
                self.out.append(script_tag((BASE / "web/attach.js").read_text()))
        self.out.append("</" + tag + ">")


def source_identity(root, assets):
    try:
        commit = subprocess.check_output(["git", "-C", str(root.parent), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
        verified = all(hashlib.sha256(subprocess.check_output(["git", "-C", str(root.parent), "show", f"{commit}:web/{name}"], stderr=subprocess.DEVNULL)).hexdigest() == digest for name, digest in assets.items())
        return commit, verified
    except (subprocess.CalledProcessError, OSError):
        return None, False


def build(root: Path, output: Path, *, enforce_app=True):
    root = root.resolve()
    parser = Bundler(root, enforce_app=enforce_app)
    index = (root / "index.html").read_text()
    original_index = index
    if "__RIFF_STUDIO_BUILD__" in index:
        version = (root.parent / "VERSION").read_text().strip()
        digest = hashlib.sha256(version.encode())
        for file in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(file.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(file.read_bytes()).digest())
        index = index.replace("__RIFF_STUDIO_BUILD__", digest.hexdigest())
    parser.feed(index); parser.close()
    if enforce_app and not parser.patched_app:
        raise ValueError("The original Riff app.js was not found; refusing a replacement UI.")
    html = "".join(parser.out)
    if len(html.encode()) > 8 * 1024 * 1024:
        raise ValueError("UI bundle exceeds the 8 MiB resource limit.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    hashes = {**parser.assets, "index.html": hashlib.sha256(original_index.encode()).hexdigest()}
    commit, verified = source_identity(root, hashes)
    receipt = {"upstream_reference": commit, "upstream_commit_verified": verified,
               "assets_sha256": hashes, "patches": parser.patches,
               "integration_sha256": {name: hashlib.sha256((BASE / "web" / name).read_bytes()).hexdigest() for name in ("host.js", "attach.js")},
               "bundle_sha256": hashlib.sha256(html.encode()).hexdigest()}
    output.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--riff-web", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=BASE / "dist/studio.html")
    args = parser.parse_args()
    build(args.riff_web, args.output)
    print(args.output)
