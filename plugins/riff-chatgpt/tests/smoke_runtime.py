#!/usr/bin/env python3
"""Acceptance check of a complete, unmodified platform package over real MCP.

This is not a neural fixture. --no-render checks startup and persistent state;
--models or --download-models additionally runs a short real YuE2 inference.
Use a fresh workspace. Evidence contains identities and measurements, not media
bytes, absolute build paths or provider credentials.
"""
from __future__ import annotations

import argparse
import array
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import wave

PROTOCOL = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": PROTOCOL,
        "io.modelcontextprotocol/clientCapabilities": {}}
RECIPE = {"title": "Riff packaged MCP acceptance", "mode": "instrumental",
          "style": "Instrumental music, no vocals", "lyrics": "", "abc": "",
          "seed": "1234", "max_seconds": 1, "steps": 2, "solver": "midpoint",
          "cot": "off", "cfg_scale": 1, "temperature": 1}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


class Client:
    def __init__(self, package, workspace, log):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("RIFF_", "PYTHON"))}
        environment["PATH"] = "/nonexistent"
        self.process = subprocess.Popen([
            str(package / "runtime/python/bin/python3"), "-I", "-B",
            str(package / "server/launch.py"), "--workspace", str(workspace)],
            cwd=package, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, env=environment)
        self.messages, self.next_id = queue.Queue(), 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except Exception as error:
            self.messages.put(error)
        finally:
            self.messages.put(EOFError("Packaged MCP closed its protocol stream."))

    def rpc(self, method, params=None, timeout=120):
        self.next_id += 1
        request = {"jsonrpc": "2.0", "id": self.next_id, "method": method,
                   "params": {**(params or {}), "_meta": META}}
        self.process.stdin.write((json.dumps(request) + "\n").encode())
        self.process.stdin.flush()
        try:
            response = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("Packaged MCP timed out: " + method) from error
        if isinstance(response, Exception):
            raise response
        check(response.get("id") == self.next_id, "MCP response identity mismatch.")
        check("error" not in response, "MCP error: " + str(response.get("error")))
        result = response["result"]
        check(result.get("resultType") == "complete", "Missing modern result type.")
        return result

    def tool(self, name, arguments=None, *, allow_error=False):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if not allow_error:
            check(not result.get("isError"), "Riff tool failed: " + json.dumps(result))
        return result

    def body(self, name, arguments=None):
        return self.tool(name, arguments)["structuredContent"]["body"]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
                raise RuntimeError("The packaged MCP process did not exit on disconnect.")
        self.reader.join(timeout=5)
        check(self.process.returncode == 0,
              "The packaged MCP process exited unsuccessfully; inspect its private log.")


def seed_models(source, workspace, manifest):
    target = workspace / "models" / manifest["revision"]
    for name, expected in manifest["files"].items():
        file = source / name
        check(file.is_file() and not file.is_symlink(), "Missing regular model file: " + name)
        check(file.stat().st_size == expected["bytes"] and digest(file) == expected["sha256"],
              "Input model does not match the repository pin: " + name)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, destination)


def prepare_models(client, timeout):
    client.body("riff_setup", {"action": "setup", "options": {"accept_model_terms": True}})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        system = client.body("riff_read", {"path": "/api/system"})
        task = system["task"]
        if task["status"] == "done":
            check(system["engine"]["ready"], "Verified setup did not make the engine ready.")
            return task
        check(task["status"] not in ("failed", "cancelled"), "Model setup failed: " + str(task))
        time.sleep(1)
    client.tool("riff_setup", {"action": "cancel"}, allow_error=True)
    raise TimeoutError("Pinned model setup exceeded the acceptance deadline.")


def render(client, timeout):
    client.body("riff_ui_request", {"path": "/api/system/engine", "method": "POST",
                                  "body": {"threads": 2, "warm_engine": False}})
    start = time.monotonic()
    submitted = client.body("riff_generate", {"recipe": RECIPE})
    job_id = submitted["id"]
    deadline = time.monotonic() + timeout
    states = [submitted["status"]]
    while time.monotonic() < deadline:
        job = client.body("riff_read", {"path": "/api/jobs/" + job_id})
        if job["status"] != states[-1]:
            states.append(job["status"])
        if job["status"] == "done":
            break
        check(job["status"] not in ("failed", "interrupted", "cancelled", "planned", "performed", "synthesized"),
              "Real music render did not complete: " + str(job.get("error") or job["status"]))
        time.sleep(1)
    else:
        client.tool("riff_edit", {"path": "/api/jobs/" + job_id + "/cancel",
                                 "method": "POST", "body": {}}, allow_error=True)
        raise TimeoutError("Real render exceeded its acceptance deadline.")
    elapsed = time.monotonic() - start
    track_id = job["track_id"]
    track = client.body("riff_read", {"path": "/api/tracks/" + track_id})
    raw, chunks = bytearray(), 0
    while True:
        result = client.tool("riff_audio_chunk", {"track_id": track_id,
                             "offset": len(raw), "length": 64 * 1024})
        check(result["content"] == [], "Audio bytes leaked into conversation content.")
        data = result["structuredContent"]
        blob = base64.b64decode(result["_meta"]["riff/audio"]["base64"], validate=True)
        check(data["offset"] == len(raw) and data["bytes"] == len(blob), "Invalid media range.")
        check(data["total"] <= 1024 * 1024, "Unexpectedly large one-second smoke audio.")
        raw.extend(blob)
        chunks += 1
        if data["eof"]:
            check(len(raw) == data["total"], "The audio transfer is incomplete.")
            break
    with wave.open(io.BytesIO(raw)) as audio:
        rate, channels, width, frames = audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()
        check((rate, channels, width) == (48000, 2, 2), "Unexpected native output format.")
        check(0.8 <= frames / rate <= 1.2, "Unexpected native output duration.")
        pcm = array.array("h", audio.readframes(frames))
        if sys.byteorder != "little":
            pcm.byteswap()
        peak = max(abs(value) for value in pcm)
        check(peak > 0, "Real inference produced silent PCM.")
    check(track["recipe"]["seed"] == RECIPE["seed"], "The saved recipe lost its fixed seed.")
    return {"job_id": job_id, "track_id": track_id, "states": states,
            "wall_seconds_through_poll_completion": round(elapsed, 3), "recipe": RECIPE,
            "audio": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                      "channels": channels, "sample_rate": rate, "sample_width": width,
                      "frames": frames, "duration": frames / rate, "absolute_pcm_peak": peak / 32768,
                      "full_scale_samples": sum(value in (-32768, 32767) for value in pcm),
                      "chunks_transferred": chunks},
            "performance_saved": bool(track["recipe"].get("performance")),
            "acoustic_saved": bool(track["recipe"].get("acoustic"))}


def run(args):
    package, workspace, output = args.package.resolve(), args.workspace.resolve(), args.output.resolve()
    check(not workspace.exists(), "Choose a new acceptance workspace; existing user data is never reused.")
    check(not workspace.is_relative_to(package), "Acceptance workspace must be outside the package.")
    output.mkdir(parents=True, exist_ok=True)
    check(not (output / "runtime-smoke.json").exists(), "Choose a fresh acceptance output directory.")
    config = json.loads((package / "runtime/runtime.json").read_text())
    manifest = json.loads((package / "riff/sources.json").read_text())["model"]
    if args.models:
        seed_models(args.models.resolve(), workspace, manifest)
    evidence = {"schema": "riff.chatgpt.acceptance.v1", "checked_at": datetime.now(timezone.utc).isoformat(),
                "platform": config["platform"], "backend": config["backend"],
                "plugin_version": config["plugin_version"], "riff_version": config["riff_version"],
                "package_manifest_sha256": digest(package / "bundle-manifest.json"),
                "native_binary_sha256": digest(package / "runtime/engine/audiocpp_cli"),
                "protocol": PROTOCOL, "real_inference": not args.no_render,
                "host": "stdio acceptance client; no production ChatGPT host registration"}
    with (output / "runtime-smoke.log").open("wb") as log:
        client = Client(package, workspace, log)
        try:
            discovered = client.rpc("server/discover")
            check(PROTOCOL in discovered["supportedVersions"], "Current protocol was not discovered.")
            tools = client.rpc("tools/list")["tools"]
            check(len(tools) >= 18, "Full plugin tools are missing.")
            resource = client.rpc("resources/read", {"uri": "ui://riff/studio/adapter-v0.2.0.html"})["contents"][0]
            check('id="lyrics"' in resource["text"] and "RiffHost" in resource["text"], "Original UI/host bridge is missing.")
            evidence["tool_count"] = len(tools)
            evidence["ui_bytes"] = len(resource["text"].encode())
            state = client.body("riff_open_studio")["state"]
            check(state["maintenance"]["plugin_managed"], "The native runtime is not plugin managed.")
            check(state["engine"]["binary_ready"], "The package has no native binary.")
            saved = client.body("riff_save_draft", {"recipe": RECIPE, "expected_revision": 0})
            client.tool("riff_settings_update", {"set": {"default_view": "library"}})
            if args.no_render:
                check(not state["engine"]["ready"], "Fresh model-free workspace unexpectedly reports ready.")
                failed = client.tool("riff_generate", {"recipe": RECIPE}, allow_error=True)
                check(failed.get("isError"), "Missing models did not produce an honest generation error.")
                evidence["missing_models_reported"] = True
            else:
                setup = prepare_models(client, args.setup_timeout)
                evidence["models"] = {"repo": manifest["repo"], "revision": manifest["revision"],
                                      "files": manifest["files"], "verified_bytes": setup["received_bytes"]}
                evidence["render"] = render(client, args.render_timeout)
        finally:
            client.close()
        # A second fresh process must retain the user state and release the lock.
        restarted = Client(package, workspace, log)
        try:
            restored = restarted.body("riff_get_draft")
            check(restored == saved, "The shared draft did not survive process replacement.")
            settings = restarted.tool("riff_settings_read")["structuredContent"]["values"]
            check(settings["default_view"] == "library", "Settings did not survive process replacement.")
            if evidence.get("render"):
                check(restarted.body("riff_read", {"path": "/api/tracks/" + evidence["render"]["track_id"]}),
                      "The completed recording did not survive process replacement.")
            evidence["persistent_draft_and_settings"] = True
        finally:
            restarted.close()
    evidence["status"] = "passed"
    (output / "runtime-smoke.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--no-render", action="store_true")
    mode.add_argument("--models", type=Path, help="Copy already pinned model files, then verify through real setup")
    mode.add_argument("--download-models", action="store_true", help="Download the repository's pinned models through MCP")
    parser.add_argument("--setup-timeout", type=float, default=1800)
    parser.add_argument("--render-timeout", type=float, default=600)
    run(parser.parse_args())
