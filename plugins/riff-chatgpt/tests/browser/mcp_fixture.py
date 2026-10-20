"""Run production ManagedRiff + MCP with explicit engine and remote-provider doubles.

The original UI, runtime ownership, HTTP gateway, database, LoRA validation, media
transport, and FFmpeg exports are real. Tiny fixtures replace model inference and
remote Hub/review services; this test must not be reported as a neural-audio test.
"""
import argparse
import array
import base64
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import wave

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "scripts"))
from riff_dependency import riff_root
SOURCE = riff_root()
sys.path.insert(0, str(PLUGIN / "server"))
from adapter import Adapter, DraftStore, LoopbackBackend
from main import serve
from runtime import ManagedRiff

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--ui-file", type=Path, required=True)
args = parser.parse_args()

runtime = ManagedRiff(SOURCE, args.workspace)
with runtime as port:
    sys.path.insert(0, str(SOURCE / "tests"))
    from test_loras import FakeHub, REPO, COMMIT, adapter_bytes
    from test_studio import recipe
    from test_reviews import fake_listener
    from admission_fixture import FixtureAdmission
    from paths import MODELS
    import platform_support
    import run

    store = runtime.server.store
    audio = store.outputs / "fixture.wav"
    samples = array.array("h")
    for i in range(4 * 48000):
        value = int(900 * math.sin(i * 2 * math.pi * 220 / 48000))
        samples.extend((value, value))
    if sys.byteorder != "little": samples.byteswap()
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(samples.tobytes())
    track_id = store.add_track(audio, recipe(title="Reedlight", seed="15961", max_seconds=4), {})
    second = store.outputs / "comparison.wav"
    shutil.copyfile(audio, second)
    second_id = store.add_track(second, recipe(title="Warm room", seed="15962", max_seconds=4, parent_track_id=track_id), {})
    codes = audio.with_suffix(".codes.i32"); codes.write_bytes(bytes([7, 0, 0, 0]) * 100)
    saved = store.track(track_id)["recipe"]
    saved["performance"] = {"frames": 100, "sha256": hashlib.sha256(codes.read_bytes()).hexdigest(), "truncated": False}
    with store.db() as db:
        db.execute("UPDATE tracks SET recipe=? WHERE id=?", (json.dumps(saved), track_id))

    class BrowserHub(FakeHub):
        def search(self, query="", limit=20, sort="downloads", genre="", page=0):
            if query == "offline": raise ValueError("Fixture Hub is offline")
            rows = [] if query and query not in "folk musician yue2" else [{
                "repo": REPO, "name": "Folk study", "tags": ["lora", "folk"], "license": "apache-2.0",
                "likes": 12, "downloads": 245, "updated_at": "2026-10-18T12:00:00Z"}]
            return {"models": rows if page == 0 else [], "page": page, "limit": limit,
                    "has_more": False, "query": query, "genre": genre, "sort": sort}
    store.loras.hub = BrowserHub({
        "folk_pair.safetensors": adapter_bytes(style="comfyui", combined=True),
        "unrelated.safetensors": b"not a safetensors header",
        "demos/folk.wav": audio.read_bytes(),
        "prompts/folk.txt": b"Fingerpicked folk, warm room, gentle reeds.",
        "README.md": b"# Folk study\nA test fixture, not a trained model.\n<script>window.loraXSS=true</script>\n[unsafe](javascript:alert(1))\n![tracking](https://example.invalid/tracker.png)\n[Source](https://huggingface.co/musician/yue2-test-lora)\n[Pinned prompt](prompts/folk.txt)\n",
    })
    upload = args.workspace / "local-study.safetensors"
    # Slightly over one transport chunk; exercise real staging, not only one-shot import.
    upload.write_bytes(adapter_bytes(stage="ar", value=.3, rank=64))
    nar = args.workspace / "room.safetensors"; nar.write_bytes(adapter_bytes(stage="nar", value=.2))
    installed = store.loras.import_local([nar], metadata={"name": "Room study", "trigger_words": ["warm room"]})
    score = "X:1\nT:A small motif\nM:4/4\nL:1/8\nQ:1/4=108\nK:Dm\nD2 F2 A2 G2|F2 E2 D4|\n"
    vocabulary = MODELS / "sidecars/yue2-qwen.tiktoken"
    vocabulary.parent.mkdir(parents=True, exist_ok=True)
    vocabulary.write_text(base64.b64encode(score.encode()).decode() + " 42\n")
    def command(values, output):
        if values.get("style") == "queue fixture hold":
            return [sys.executable, "-c", "import time\nwhile True: time.sleep(1)"]
        if values.get("render_mode") == "performance":
            return [sys.executable, "-c", "import pathlib,sys,json;p=pathlib.Path(sys.argv[1]);p.write_bytes(bytes([7,0,0,0])*100);p.with_suffix('.i32.json').write_text(json.dumps(dict(frames=100,truncated=False)))", str(output.with_suffix(".codes.i32"))]
        if values.get("render_mode") == "plan":
            return [sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('{\"tokens\":[42],\"truncated\":false}')", str(output.with_suffix(".plan.json"))]
        return [sys.executable, "-c", "import shutil,sys;shutil.copyfile(sys.argv[1],sys.argv[2])", str(audio), str(output)]
    runtime.generator.command_builder = command
    runtime.generator.admission.close()
    runtime.generator.admission = FixtureAdmission()
    readiness = platform_support.readiness
    platform_support.readiness = lambda: {**readiness(), "ready": True, "binary_ready": True, "missing_models": []}
    run.engine_capabilities = lambda *a, **kw: {"lora": True, "warm_engine": False,
        "exact_score_replay": False, "acoustic_checkpoint": False}
    def downstream_listener(output):
        command = fake_listener(output)
        # The upstream fixture uses python -c; its imports need the pinned
        # dependency explicitly now that the process cwd is the plugin repo.
        command[2] = "import sys\nsys.path.insert(0, " + repr(str(SOURCE)) + ")\n" + command[2]
        return command

    runtime.reviews.command_builder = downstream_listener
    runtime.reviews.models_cache = [{"id": "fixture/audio-model", "name": "Fixture listener"}]
    runtime.reviews.models = lambda refresh=False: runtime.reviews.models_cache
    adapter = Adapter(LoopbackBackend(port), DraftStore(args.workspace / "adapter-draft.sqlite3"), args.ui_file)
    print(json.dumps({"url": f"http://127.0.0.1:{port}", "track_id": track_id, "second_track_id": second_id,
        "loras": {"upload": str(upload), "nar_id": installed["id"], "hub_repo": REPO, "revision": COMMIT},
        "test_doubles": ["neural inference", "model admission", "Hugging Face", "review provider"]}), flush=True)
    try:
        serve(adapter, concurrent=True, on_disconnect=runtime.stop_work)
    finally:
        adapter.close()
