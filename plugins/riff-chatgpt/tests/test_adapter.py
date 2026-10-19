"""Adapter tests use explicit backend doubles, never a fake YuE2 success claim."""
import base64
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "scripts")]
from adapter import Adapter, AdapterError, DraftStore, LoopbackBackend, MAX_CHUNK, TOOLS, UI_URI, route
from main import RPC, serve
from build_ui import build, patch_app, asset

ID = "a" * 32

def wav_fixture():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 80)
    return out.getvalue()

class FakeBackend:
    def __init__(self): self.calls, self.audio = [], wav_fixture()
    def json_request(self, path, method="GET", body=None):
        self.calls.append((path, method, body))
        if path in ("/api/generations", "/api/plans"):
            # Test-only backend deliberately reports missing engine, not success.
            return 400, {"error": "Engine is not installed in this test."}
        return 200, {"engine": {"ready": False}, "tracks": [], "jobs": []}
    def audio_chunk(self, tid, offset, length): return self.audio[offset:offset+length], len(self.audio)

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = FakeBackend()
        self.drafts = DraftStore(self.root / "draft.sqlite3")
        self.ui = self.root / "studio.html"; self.ui.write_text("<!doctype html><p>TEST FIXTURE</p>")
        self.adapter = Adapter(self.backend, self.drafts, self.ui)
    def test_open_attaches_ui_only_to_render_tool(self):
        tools = {t["name"]: t for t in TOOLS}
        self.assertEqual(tools["riff_open_studio"]["_meta"]["ui"]["resourceUri"], UI_URI)
        self.assertNotIn("_meta", tools["riff_generate"])
        self.assertEqual(tools["riff_open_studio"]["_meta"]["openai/ui"]["entrypoints"], [{"type": "global"}])
        self.assertEqual(tools["riff_open_project"]["_meta"]["openai/ui"]["entrypoints"], [{"type": "thread"}])
    def test_read_is_read_only(self):
        self.adapter.call("riff_read", {"path": "/api/state"})
        self.assertEqual(self.backend.calls, [("/api/state", "GET", None)])
    def test_read_cannot_generate(self):
        with self.assertRaises(AdapterError): self.adapter.call("riff_read", {"path": "/api/generations"})
        self.assertFalse(self.backend.calls)
    def test_generation_uses_native_queue_and_propagates_missing_engine(self):
        result = self.adapter.call("riff_generate", {"recipe": {"lyrics": "test", "seed": "1"}})
        self.assertTrue(result["isError"])
        self.assertEqual(self.backend.calls[0][0:2], ("/api/generations", "POST"))
    def test_plan_uses_distinct_route(self):
        self.adapter.call("riff_generate", {"recipe": {}, "plan_only": True})
        self.assertEqual(self.backend.calls[0][0], "/api/plans")
    def test_plan_type_enforced(self):
        with self.assertRaises(AdapterError): self.adapter.call("riff_generate", {"recipe": {}, "plan_only": "false"})
    def test_unknown_and_extraneous_arguments_rejected(self):
        for name, args in [("shell", {}), ("riff_read", {"path": "/api/state", "url": "http://evil"}), ("riff_read", {})]:
            with self.subTest(name=name, args=args), self.assertRaises(AdapterError): self.adapter.call(name, args)
    def test_unsafe_routes_blocked(self):
        for path in ["https://evil.invalid", "/api/../state", "/api/%73tate", "/api/state?url=x", "/api/state#x", "/api/state\r\nX:1", "/api//state"]:
            with self.subTest(path=path), self.assertRaises(AdapterError): route(path, "GET")
    def test_admin_and_credentials_not_exposed(self):
        for path in ["/api/system/setup", "/api/system/update", "/api/review/settings", "/api/composition/revise", "/api/inspiration"]:
            with self.subTest(path=path), self.assertRaises(AdapterError): route(path, "POST")
    def test_track_delete_not_exposed(self):
        with self.assertRaises(AdapterError): route(f"/api/tracks/{ID}", "DELETE")
    def test_track_fields_limited(self):
        with self.assertRaises(AdapterError): self.adapter.call("riff_edit", {"path": f"/api/tracks/{ID}", "method": "PATCH", "body": {"file": "/tmp/x"}})
        self.adapter.call("riff_edit", {"path": f"/api/tracks/{ID}", "method": "PATCH", "body": {"notes": "listen again"}})
    def test_cancel_route(self):
        self.adapter.call("riff_edit", {"path": f"/api/jobs/{ID}/cancel", "method": "POST", "body": {}})
        self.assertEqual(self.backend.calls[0][0], f"/api/jobs/{ID}/cancel")
    def test_draft_persists_and_rejects_stale_writes(self):
        self.drafts.save({"lyrics": "first"}, 0)
        again = DraftStore(self.root / "draft.sqlite3")
        self.assertEqual(again.load(), {"revision": 1, "recipe": {"lyrics": "first"}})
        with self.assertRaises(AdapterError): again.save({"lyrics": "stale"}, 0)
        self.assertEqual(self.drafts.load()["recipe"]["lyrics"], "first")
    def test_nan_rejected(self):
        with self.assertRaises(AdapterError): self.adapter.call("riff_generate", {"recipe": {"steps": float("nan")}})
    def test_audio_bytes_not_in_conversation_fields(self):
        result = self.adapter.call("riff_audio_chunk", {"track_id": ID, "offset": 0, "length": MAX_CHUNK})
        self.assertEqual(result["content"], [])
        self.assertEqual(base64.b64decode(result["_meta"]["riff/audio"]["base64"]), self.backend.audio)
        self.assertNotIn("base64", json.dumps(result["structuredContent"]))
    def test_audio_is_app_only(self):
        audio = next(t for t in TOOLS if t["name"] == "riff_audio_chunk")
        self.assertEqual(audio["_meta"]["ui"]["visibility"], ["app"])
    def test_audio_input_limits(self):
        for offset, length in [(-1, 4), (True, 4), (0, 0), (0, MAX_CHUNK+1)]:
            with self.subTest(offset=offset, length=length), self.assertRaises(AdapterError):
                self.adapter.call("riff_audio_chunk", {"track_id": ID, "offset": offset, "length": length})
    def test_resource_and_network_allowlist(self):
        resource = self.adapter.resource(UI_URI)["contents"][0]
        self.assertEqual(resource["mimeType"], "text/html;profile=mcp-app")
        self.assertEqual(resource["_meta"]["ui"]["csp"]["connectDomains"], [])
    def test_unknown_resource_rejected(self):
        with self.assertRaises(AdapterError): self.adapter.resource("file:///etc/passwd")
    def test_missing_ui_fails_explicitly(self):
        self.ui.unlink()
        with self.assertRaisesRegex(AdapterError, "resource is missing"): self.adapter.resource(UI_URI)
    def test_rpc_initialize_and_listing(self):
        rpc = RPC(self.adapter)
        self.assertIn("error", rpc.handle({"jsonrpc": "2.0", "id": 0, "method": "tools/list"}))
        response = rpc.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
        self.assertEqual(response["id"], 0)
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(rpc.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"], TOOLS)
    def test_rpc_notification_has_no_response(self):
        self.assertIsNone(RPC(self.adapter).handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    def test_rpc_parse_errors_do_not_crash(self):
        sink = io.StringIO()
        serve(self.adapter, io.BytesIO(b"not-json\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode() + b"\n"), sink)
        rows = [json.loads(s) for s in sink.getvalue().splitlines()]
        self.assertEqual(rows[0]["error"]["code"], -32700)
        self.assertEqual(rows[1]["result"], {})

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wav = wav_fixture()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302); self.send_header("Location", "http://invalid.invalid"); self.end_headers(); return
                if self.path.endswith("/audio"):
                    begin, end = map(int, self.headers["Range"][6:].split("-")); end = min(end, len(cls.wav)-1)
                    raw = cls.wav[begin:end+1]
                    self.send_response(206); self.send_header("Content-Range", f"bytes {begin}-{end}/{len(cls.wav)}")
                else:
                    raw = b'{"ok":true}'; self.send_response(200)
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.backend = LoopbackBackend(cls.server.server_port)
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def test_real_private_http_json(self): self.assertEqual(self.backend.json_request("/api/state"), (200, {"ok": True}))
    def test_real_private_http_byte_range(self):
        raw, total = self.backend.audio_chunk(ID, 4, 8)
        self.assertEqual(raw, self.wav[4:12]); self.assertEqual(total, len(self.wav))
    def test_redirects_refused(self):
        with self.assertRaises(AdapterError): self.backend.json_request("/redirect")

class BundlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.web = self.root / "web"
        # Exercise the complete real studio, including its video worker and
        # LoRA assets. This replaces the old hand-written patch-point fixture.
        source = ROOT.parents[1]
        shutil.copytree(source / "web", self.web)
        shutil.copy2(source / "VERSION", self.root / "VERSION")
        self.app = (self.web / "app.js").read_text()
    def test_preserves_markup_and_patches_transport(self):
        output = self.root / "out.html"; html = build(self.web, output)
        self.assertIn('id="lyrics"', html)
        self.assertIn("window.RiffHost.fetch(path, options)", html)
        self.assertIn("await window.RiffHost.audioUrl(id)", html)
        self.assertNotIn("__RIFF_STUDIO_BUILD__", html)
        self.assertEqual((self.web / "app.js").read_text(), self.app)
        self.assertTrue(output.with_suffix(".receipt.json").is_file())
    def test_defer_order_kept_after_document_markup(self):
        html = build(self.web, self.root / "out.html")
        self.assertLess(html.index('id="lyrics"'), html.index("async function api"))
        self.assertLess(html.index("async function api"), html.index("/* Host actions run after every ORIGINAL Riff module."))
    def test_changed_upstream_adapter_point_refused(self):
        with self.assertRaises(ValueError): patch_app("different source")
    def test_external_asset_refused(self):
        with self.assertRaises(ValueError): asset(self.web, "https://external.invalid/a.js")
    def test_path_escape_refused(self):
        with self.assertRaises(ValueError): asset(self.web, "../VERSION")
    def test_symlink_escape_refused(self):
        (self.web / "outside.js").symlink_to(self.root / "VERSION")
        with self.assertRaises(ValueError): asset(self.web, "outside.js")

if __name__ == "__main__": unittest.main(verbosity=2)
