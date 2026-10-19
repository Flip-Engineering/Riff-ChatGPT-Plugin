"""Independent wire-contract acceptance tests for the actual Riff MCP adapter.

Only the native HTTP backend is a double: RPC parsing, tool declarations,
argument validation, resources, media packaging, and SQLite persistence are
production code. These checks do not download models or claim an audio render.
Primary contracts and the remaining host acceptance gates are documented in
docs/chatgpt-plugin-protocol.md.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import wave

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "server"))
from adapter import Adapter, AdapterError, DraftStore, MAX_CHUNK, MAX_INPUT
from main import RPC, serve


CURRENT = "2026-07-28"
LEGACY = "2025-11-25"
PROTOCOL_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"
TRACK_ID = "b" * 32


def request(method, params=None, *, request_id=1, version=CURRENT):
    """Build the per-request metadata required by the modern MCP protocol."""
    parameters = dict(params or {})
    if version is not None:
        parameters["_meta"] = {
            PROTOCOL_KEY: version,
            CLIENT_CAPABILITIES_KEY: {},
        }
    return {"jsonrpc": "2.0", "id": request_id, "method": method,
            "params": parameters}


def audio_fixture():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


class RecordingBackend:
    """An explicit unavailable-engine double, never a synthetic render result."""

    def __init__(self):
        self.calls = []
        self.audio = audio_fixture()
        self.media_mime = "audio/wav"
        self.failure = None
        self.engine = {
            "ready": False,
            "backend": "cpu",
            "binary": "/packaged/riff/runtime/engine/audiocpp_cli",
            "model_root": "/owned/riff/models/pinned-revision",
            "model_file": "yue2-3b-q4_0.gguf",
            "vae_file": "yue2-vae-f16.gguf",
            "threads": 4,
            "device": 0,
            "warm_engine": False,
        }

    def json_request(self, path, method="GET", body=None):
        self.calls.append((path, method, body))
        if self.failure is not None:
            raise self.failure
        if path in ("/api/generations", "/api/plans"):
            return 503, {"error": "The native engine is unavailable in this contract test."}
        return 200, {"engine": dict(self.engine), "tracks": [], "jobs": []}

    def audio_chunk(self, track_id, offset, length):
        self.calls.append(("audio", track_id, offset, length))
        return self.audio[offset:offset + length], len(self.audio)

    def media_chunk(self, path, offset, length):
        self.calls.append(("media", path, offset, length))
        return self.audio[offset:offset + length], len(self.audio), self.media_mime, "take.wav"


class ProtocolContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.ui = self.directory / "studio.html"
        self.ui.write_text("<!doctype html><html><head><title>Riff contract fixture</title>"
                           "</head><body>Original studio asset fixture</body></html>",
                           encoding="utf-8")
        self.database = self.directory / "adapter.sqlite3"
        self.backend = RecordingBackend()
        self.drafts = DraftStore(self.database)
        self.adapter = Adapter(self.backend, self.drafts, self.ui)
        self.rpc = RPC(self.adapter)

    def completed(self, response):
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("jsonrpc"), "2.0")
        self.assertNotIn("error", response, response)
        self.assertIsInstance(response.get("result"), dict)
        result = response["result"]
        self.assertEqual(result.get("resultType"), "complete")
        return result

    def cached(self, result):
        self.assertIs(type(result.get("ttlMs")), int)
        self.assertGreaterEqual(result["ttlMs"], 0)
        self.assertIn(result.get("cacheScope"), ("public", "private"))

    def tools(self):
        result = self.completed(self.rpc.handle(request("tools/list")))
        return {item["name"]: item for item in result["tools"]}

    def call(self, name, arguments=None, *, rpc=None):
        active = rpc if rpc is not None else self.rpc
        return active.handle(request("tools/call", {"name": name, "arguments": arguments or {}}))

    def rejected(self, response):
        self.assertIsInstance(response, dict)
        self.assertTrue("error" in response or response.get("result", {}).get("isError") is True,
                        response)

    def settings(self, *, rpc=None):
        result = self.completed(self.call("riff_settings_read", rpc=rpc))
        self.assertIsNot(result.get("isError"), True, result)
        return result["structuredContent"]

    def test_modern_discovery_has_current_version_capabilities_and_cache_contract(self):
        result = self.completed(self.rpc.handle(request("server/discover")))
        self.assertIn(CURRENT, result["supportedVersions"])
        self.assertTrue(all(isinstance(item, str) and item for item in result["supportedVersions"]))
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])
        info = result["_meta"][SERVER_INFO_KEY]
        self.assertIsInstance(info.get("name"), str)
        self.assertTrue(info["name"])
        self.assertIsInstance(info.get("version"), str)
        self.assertTrue(info["version"])
        self.cached(result)
        self.assertFalse(self.backend.calls, "Discovery must not start or query an engine.")

    def test_modern_read_requests_are_independent_of_discovery_or_initialization(self):
        for method in ("tools/list", "resources/list"):
            with self.subTest(method=method):
                result = self.completed(RPC(self.adapter).handle(request(method)))
                self.cached(result)
        result = self.completed(self.call("riff_get_draft", rpc=RPC(self.adapter)))
        self.assertIsNot(result.get("isError"), True)
        self.assertFalse(self.backend.calls)

    def test_modern_version_is_checked_on_each_request(self):
        self.completed(self.rpc.handle(request("tools/list")))
        rejected = self.rpc.handle(request("tools/list", version="1900-01-01", request_id="future"))
        self.assertEqual(rejected["id"], "future")
        self.assertEqual(rejected["error"]["code"], -32022)
        self.assertEqual(rejected["error"]["data"]["requested"], "1900-01-01")
        self.assertIn(CURRENT, rejected["error"]["data"]["supported"])
        self.completed(self.rpc.handle(request("tools/list", request_id="recovered")))

    def test_modern_client_capabilities_are_required_objects(self):
        for capabilities in (None, [], "all", False):
            with self.subTest(capabilities=capabilities):
                incoming = request("tools/list")
                if capabilities is None:
                    del incoming["params"]["_meta"][CLIENT_CAPABILITIES_KEY]
                else:
                    incoming["params"]["_meta"][CLIENT_CAPABILITIES_KEY] = capabilities
                response = RPC(self.adapter).handle(incoming)
                self.assertEqual(response["error"]["code"], -32602)

    def test_legacy_initialize_and_current_requests_can_share_process(self):
        result = self.rpc.handle(request("initialize", {
            "protocolVersion": LEGACY, "capabilities": {},
            "clientInfo": {"name": "riff-contract", "version": "1.0"},
        }, version=None))["result"]
        self.assertEqual(result["protocolVersion"], LEGACY)
        self.assertIn("tools", result["capabilities"])
        self.assertIsNone(self.rpc.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        legacy_tools = self.rpc.handle(request("tools/list", version=None))
        self.assertIn("tools", legacy_tools["result"])
        self.completed(self.rpc.handle(request("tools/list")))
        settings = result["capabilities"].get("extensions", {}).get("openai/settings")
        if settings is None:
            settings = result["capabilities"].get("experimental", {}).get("openai/settings")
        self.assertEqual(settings, {"readTool": "riff_settings_read", "updateTool": "riff_settings_update"})

    def test_notifications_do_not_execute_mutating_requests_or_return_responses(self):
        incoming = request("tools/call", {"name": "riff_generate", "arguments": {"recipe": {}}})
        del incoming["id"]
        self.assertIsNone(self.rpc.handle(incoming))
        self.assertFalse(self.backend.calls)

    def test_unknown_method_tool_and_resource_use_current_protocol_errors(self):
        unknown_method = self.rpc.handle(request("not/a/method"))
        self.assertEqual(unknown_method["error"]["code"], -32601)
        unknown_tool = self.call("not_a_riff_tool")
        self.assertEqual(unknown_tool["error"]["code"], -32602)
        unknown_resource = self.rpc.handle(request("resources/read", {"uri": "file:///etc/passwd"}))
        # 2026-07-28 resources changed missing-resource errors to Invalid Params;
        # -32002 is the accepted legacy form, not the modern server contract.
        self.assertEqual(unknown_resource["error"]["code"], -32602)
        self.assertFalse(self.backend.calls)

    def test_non_object_params_and_boolean_request_ids_are_invalid(self):
        invalid_params = request("tools/list")
        invalid_params["params"] = []
        self.assertEqual(self.rpc.handle(invalid_params)["error"]["code"], -32602)
        invalid_id = request("tools/list", request_id=True)
        self.assertEqual(self.rpc.handle(invalid_id)["error"]["code"], -32600)

    def test_stdio_recovers_after_bad_json_without_mixing_logs_into_results(self):
        valid = request("tools/list", request_id=0)
        stream = io.BytesIO(b"not-json\n" + b'{"bad": NaN}\n' + json.dumps(valid).encode() + b"\n")
        output = io.StringIO()
        serve(self.adapter, stream, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual([entry["error"]["code"] for entry in responses[:2]], [-32700, -32700])
        self.assertEqual(responses[2]["id"], 0)
        self.completed(responses[2])

    def test_oversized_stdio_frame_closes_before_trailing_mutation(self):
        mutation = request("tools/call", {"name": "riff_generate", "arguments": {"recipe": {}}})
        stream = io.BytesIO(b"x" * (MAX_INPUT + 8192) + b"\n" + json.dumps(mutation).encode() + b"\n")
        output = io.StringIO()
        serve(self.adapter, stream, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertFalse(self.backend.calls)

    def test_entrypoints_are_distinct_read_only_tools_accepting_empty_arguments(self):
        tools = self.tools()
        self.assertIn("riff_open_studio", tools)
        self.assertIn("riff_open_project", tools)
        names = []
        titles = []
        kinds = []
        for tool in tools.values():
            entrypoints = tool.get("_meta", {}).get("openai/ui", {}).get("entrypoints", [])
            if not entrypoints:
                continue
            self.assertEqual(len(entrypoints), 1, "Each entrypoint needs its own titled tool.")
            names.append(tool["name"])
            titles.append(tool["title"])
            kind = entrypoints[0]["type"]
            kinds.append(kind)
            if kind in ("global", "thread"):
                self.assertFalse(tool["inputSchema"].get("required"))
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                opened = self.completed(self.call(tool["name"]))
                self.assertIsNot(opened.get("isError"), True, opened)
        self.assertIn("global", kinds)
        self.assertIn("thread", kinds)
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(call[1] == "GET" for call in self.backend.calls))

    def test_every_linked_ui_is_listed_readable_html_with_fullscreen_metadata(self):
        tools = self.tools()
        listed = self.completed(self.rpc.handle(request("resources/list")))
        resources = {item["uri"]: item for item in listed["resources"]}
        uris = {tool.get("_meta", {}).get("ui", {}).get("resourceUri") for tool in tools.values()}
        for uri in uris - {None}:
            with self.subTest(uri=uri):
                self.assertTrue(uri.startswith("ui://"))
                self.assertIn(uri, resources)
                result = self.completed(RPC(self.adapter).handle(request("resources/read", {"uri": uri})))
                self.cached(result)
                content = next(item for item in result["contents"] if item["uri"] == uri)
                self.assertEqual(content["mimeType"], "text/html;profile=mcp-app")
                self.assertIn("<!doctype html", content["text"].lower())
                display = content["_meta"]["openai/ui"]
                self.assertEqual(display["preferredDisplayMode"], "fullscreen")
                self.assertIn("fullscreen", display["availableDisplayModes"])
                self.assertNotIn("pip", display["availableDisplayModes"])
                csp = content["_meta"]["ui"]["csp"]
                self.assertFalse(csp.get("connectDomains"), "The UI must use the host tool bridge, not localhost.")

    def test_tool_names_are_unique_and_binary_gateway_tools_are_app_only(self):
        result = self.completed(self.rpc.handle(request("tools/list")))
        definitions = result["tools"]
        self.assertEqual(len(definitions), len({item["name"] for item in definitions}))
        tools = {item["name"]: item for item in definitions}
        for name in ("riff_audio_chunk", "riff_media_chunk", "riff_ui_request"):
            with self.subTest(name=name):
                self.assertEqual(tools[name]["_meta"]["ui"]["visibility"], ["app"])
        for name in ("riff_audio_chunk", "riff_media_chunk"):
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["riff_ui_request"]["annotations"]["readOnlyHint"])

    def test_unimplemented_resource_subscriptions_are_not_advertised(self):
        capabilities = self.completed(self.rpc.handle(request("server/discover")))["capabilities"]
        self.assertFalse(capabilities["resources"].get("subscribe", False))
        self.assertFalse(capabilities["resources"].get("listChanged", False))

    def test_settings_advertise_native_output_contract_with_effective_defaults(self):
        discover = self.completed(self.rpc.handle(request("server/discover")))
        settings = discover["capabilities"]["extensions"]["openai/settings"]
        self.assertEqual(settings, {"readTool": "riff_settings_read", "updateTool": "riff_settings_update"})
        tools = self.tools()
        read_tool = tools[settings["readTool"]]
        self.assertTrue(read_tool["annotations"]["readOnlyHint"])
        self.assertFalse(read_tool["inputSchema"].get("required"))
        self.assertEqual(read_tool["outputSchema"]["type"], "object")
        self.assertTrue({"schema", "values"}.issubset(read_tool["outputSchema"]["required"]))
        state = self.settings()
        self.assertEqual(state["schema"]["type"], "object")
        self.assertNotIn("body", state, "Settings structuredContent must not use the HTTP gateway envelope.")
        for name, field in state["schema"]["properties"].items():
            self.assertIn(name, state["values"])
            self.assertIn(field["type"], ("boolean", "string", "number", "integer"))
            self.assertIsInstance(field["title"], str)
        self.assertFalse(self.backend.calls)

    def test_settings_updates_merge_persist_and_do_not_change_draft_revision(self):
        before = self.settings()
        baseline_draft = self.drafts.load()
        updated_value = not before["values"]["auto_save_draft"]
        updated = self.completed(self.call("riff_settings_update", {"set": {"auto_save_draft": updated_value}}))
        self.assertIsNot(updated.get("isError"), True)
        expected = {**before["values"], "auto_save_draft": updated_value}
        self.assertEqual(updated["structuredContent"]["values"], expected)
        second = Adapter(RecordingBackend(), DraftStore(self.database), self.ui)
        self.assertEqual(self.settings(rpc=RPC(second))["values"], expected)
        self.assertEqual(self.drafts.load(), baseline_draft)

    def test_settings_invalid_updates_are_atomic(self):
        original = self.settings()["values"]
        invalid = [
            {"set": {"unadvertised_preference": True}},
            {"set": {"auto_save_draft": "false"}},
            {"set": {"media_cache_mib": True}},
            {"set": {"media_cache_mib": 0}},
            {"set": {"media_cache_mib": 1025}},
            {"set": {"default_view": "unknown-view"}},
            {"set": {"auto_save_draft": not original["auto_save_draft"], "media_cache_mib": -1}},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.rejected(self.call("riff_settings_update", arguments))
                self.assertEqual(self.settings()["values"], original)

    def test_schema_argument_rejections_have_no_backend_side_effects(self):
        cases = [
            ("riff_read", {"path": []}),
            ("riff_read", {"path": "/api/state", "url": "https://untrusted.invalid"}),
            ("riff_generate", {}),
            ("riff_generate", {"recipe": []}),
            ("riff_generate", {"recipe": {}, "plan_only": "false"}),
            ("riff_save_draft", {"recipe": {}, "expected_revision": True}),
            ("riff_save_draft", {"recipe": {}, "expected_revision": -1}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.rejected(self.call(name, arguments))
        self.assertFalse(self.backend.calls)
        self.assertEqual(self.drafts.load()["revision"], 0)

    def test_studio_cannot_replace_the_packaged_executable_or_model_paths(self):
        # Native readiness probes execute the configured engine with --help;
        # changing this path would execute a caller-selected program on refresh.
        dangerous = {
            "binary": "/tmp/caller-selected-program",
            "model_root": "/tmp/unverified-models",
            "model_file": "alternate.gguf",
            "vae_file": "alternate-decoder.gguf",
            "backend": "cuda",
            "unadvertised_engine_option": "value",
        }
        for field, value in dangerous.items():
            with self.subTest(field=field):
                self.backend.calls.clear()
                result = self.call("riff_ui_request", {
                    "path": "/api/system/engine", "method": "POST", "body": {field: value},
                })
                self.rejected(result)
                self.assertFalse(any(call[1] == "POST" for call in self.backend.calls))

    def test_original_engine_form_can_submit_unchanged_pinned_paths_and_tuning(self):
        fixed = {key: self.backend.engine[key]
                 for key in ("backend", "binary", "model_root", "model_file", "vae_file")}
        tuning = {"threads": 6, "device": 1, "warm_engine": True}
        result = self.completed(self.call("riff_ui_request", {
            "path": "/api/system/engine", "method": "POST", "body": {**fixed, **tuning},
        }))
        self.assertIsNot(result.get("isError"), True, result)
        mutations = [call for call in self.backend.calls if call[1] == "POST"]
        self.assertEqual(mutations, [("/api/system/engine", "POST", tuning)])

    def test_backend_render_failure_is_a_visible_tool_error_without_fake_audio(self):
        result = self.completed(self.call("riff_generate", {"recipe": {"lyrics": "contract test"}}))
        self.assertIs(result.get("isError"), True)
        visible = " ".join(block.get("text", "") for block in result["content"])
        self.assertIn("unavailable", visible)
        self.assertFalse(any(block.get("type") == "audio" for block in result["content"]))
        self.assertEqual(self.backend.calls[0][:2], ("/api/generations", "POST"))

    def test_audio_and_media_payloads_are_bounded_and_only_in_result_metadata(self):
        cases = [
            ("riff_audio_chunk", {"track_id": TRACK_ID, "offset": 0, "length": MAX_CHUNK}, "riff/audio"),
            ("riff_media_chunk", {"path": f"/api/tracks/{TRACK_ID}/audio", "offset": 0, "length": MAX_CHUNK}, "riff/media"),
        ]
        encoded = base64.b64encode(self.backend.audio).decode("ascii")
        for name, arguments, meta_key in cases:
            with self.subTest(name=name):
                result = self.completed(self.call(name, arguments))
                self.assertIsNot(result.get("isError"), True, result)
                self.assertEqual(result["content"], [])
                self.assertEqual(result["_meta"][meta_key]["base64"], encoded)
                self.assertNotIn(encoded, json.dumps(result["structuredContent"]))
                self.assertEqual(result["structuredContent"]["bytes"], len(self.backend.audio))
                self.assertEqual(result["structuredContent"]["total"], len(self.backend.audio))
                self.assertTrue(result["structuredContent"]["eof"])

    def test_invalid_media_ranges_and_external_paths_never_reach_backend(self):
        for offset, length in ((-1, 1), (True, 1), (0, 0), (0, MAX_CHUNK + 1), (0, True)):
            with self.subTest(offset=offset, length=length):
                self.rejected(self.call("riff_media_chunk", {
                    "path": f"/api/tracks/{TRACK_ID}/audio", "offset": offset, "length": length,
                }))
        for path in ("https://untrusted.invalid/private", "file:///etc/passwd", "/api/../private", "/api/%2e%2e/private"):
            with self.subTest(path=path):
                self.rejected(self.call("riff_media_chunk", {"path": path, "offset": 0, "length": 1}))
        self.assertFalse(self.backend.calls)

    def test_hub_webm_preview_uses_the_native_supported_media_type(self):
        # loras.MEDIA_TYPES advertises video/webm. This verifies transport of
        # opaque bytes and its MIME type, not video decoding or real playback.
        self.backend.media_mime = "video/webm"
        self.backend.audio = b"\x1a\x45\xdf\xa3contract-fixture"
        result = self.completed(self.call("riff_media_chunk", {
            "path": "/api/loras/hub/media?repo=creator%2Fadapter&revision=" + "c" * 40 + "&file=preview.webm",
            "offset": 0, "length": MAX_CHUNK,
        }))
        self.assertIsNot(result.get("isError"), True, result)
        self.assertEqual(result["_meta"]["riff/media"]["mimeType"], "video/webm")
        self.assertEqual(result["content"], [])

    def test_two_draft_writers_cannot_silently_overwrite_each_other(self):
        peer = DraftStore(self.database)
        barrier = threading.Barrier(2)
        outcomes = []

        def save(store, lyrics):
            barrier.wait(timeout=5)
            try:
                outcomes.append(("saved", store.save({"lyrics": lyrics}, 0)))
            except AdapterError as error:
                outcomes.append(("conflict", str(error)))

        threads = [threading.Thread(target=save, args=(self.drafts, "first")),
                   threading.Thread(target=save, args=(peer, "second"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=8)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["conflict", "saved"])
        final = self.drafts.load()
        self.assertEqual(final["revision"], 1)
        winner = next(result for kind, result in outcomes if kind == "saved")
        self.assertEqual(final["recipe"], winner["recipe"])

    def test_unexpected_internal_failure_does_not_leak_private_detail_on_wire(self):
        secret = "private-contract-secret-/users/private/path"
        self.backend.failure = RuntimeError(secret)
        error_log = io.StringIO()
        with contextlib.redirect_stderr(error_log):
            response = self.call("riff_read", {"path": "/api/state"})
        self.rejected(response)
        self.assertNotIn(secret, json.dumps(response))


if __name__ == "__main__":
    unittest.main(verbosity=2)
