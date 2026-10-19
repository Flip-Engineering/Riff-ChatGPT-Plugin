"""Binary gateway boundaries, disk staging and real private HTTP transport.

Fixtures contain arbitrary bytes, not generated audio or valid model weights.
The HTTP tests bind only 127.0.0.1 and make no external requests.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import stat
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from adapter import Adapter, DraftStore
from routes import AdapterError, route, upload_headers
from transport import LoopbackBackend, MAX_CHUNK, MAX_FRAME, MAX_JSON, MAX_UPLOAD, UploadStore


ID = "a" * 32
HASH = "b" * 64
IMPORT = "/api/loras/import?name=studio-style.safetensors"
FRAMES = f"/api/video-exports/{ID}/frames"


def upload_args(data=b"ab", **changes):
    args = {"path": IMPORT, "total": 4, "offset": 0, "final": False,
            "content_type": "application/octet-stream",
            "base64": base64.b64encode(data).decode("ascii")}
    args.update(changes)
    return args


class CaptureUploadBackend:
    """Read the staged file during import, while its lifetime is guaranteed."""
    def __init__(self):
        self.calls = []
        self.status, self.body = 201, {"accepted_by_test_fixture": True}
        self.failure = None
        self.hook = None

    def upload_file(self, path, file, content_type, headers):
        self.calls.append({"path": path, "file": file, "data": file.read_bytes(),
                           "content_type": content_type, "headers": dict(headers)})
        if self.hook:
            self.hook(file)
        if self.failure:
            raise self.failure
        return self.status, dict(self.body)


class RouteTests(unittest.TestCase):
    def test_score_and_acoustic_colons_are_decoded_once(self):
        for kind in ("scores", "acoustics"):
            for separator in (":", "%3A", "%3a"):
                with self.subTest(kind=kind, separator=separator):
                    self.assertEqual(route(f"/api/{kind}/saved{separator}{ID}", "GET"),
                                     f"/api/{kind}/saved:{ID}")
            with self.assertRaises(AdapterError):
                route(f"/api/{kind}/saved%253A{ID}", "GET")

    def test_hub_queries_preserve_search_and_nested_media_names(self):
        examples = [
            ("/api/loras/hub", [("q", "café & soul + drums"), ("sort", "downloads"),
                                ("genre", ""), ("license", "apache-2.0"), ("stage", "ar"),
                                ("compatibility", "compatible"), ("page", "2"), ("limit", "20")], {}),
            ("/api/loras/hub/detail", [("repo", "artist/style"), ("revision", HASH)], {}),
            ("/api/loras/hub/media", [("repo", "artist/style"), ("revision", HASH),
                                      ("file", "demos/live & studio/été.webm")], {"media": True}),
        ]
        for path, pairs, options in examples:
            with self.subTest(path=path):
                result = route(path + "?" + urlencode(pairs), "GET", **options)
                self.assertEqual(urlsplit(result).path, path)
                self.assertEqual(parse_qsl(urlsplit(result).query, keep_blank_values=True), pairs)
                self.assertTrue(result.isascii(), "The HTTP request target remains percent-encoded.")

    def test_query_keys_are_scoped_unique_and_bounded(self):
        paths = [
            "/api/loras/hub?q=first&%71=second", "/api/loras/hub?url=https%3A%2F%2Fevil.invalid",
            "/api/loras/hub/detail?repo=artist%2Fstyle&file=weights.safetensors",
            "/api/loras/hub?q=%00", "/api/loras/hub?q=%0D%0AX-Test%3Ayes",
            "/api/loras/hub?q=%FF", "/api/loras/hub?q=" + "x" * 4097,
            "/api/loras/hub?" + "&".join("q=x" for _ in range(17)),
            "/api/presets/studio?download=1",
        ]
        for path in paths:
            with self.subTest(path=path[:100]), self.assertRaises(AdapterError):
                route(path, "GET")

    def test_json_media_upload_and_app_mutations_are_separate_capabilities(self):
        examples = [
            ("/api/state", "GET", {}),
            (f"/api/tracks/{ID}/recipe?download=1", "GET", {}),
            ("/api/system/engine", "POST", {"ui": True}),
            (f"/api/loras/{HASH}", "PATCH", {"ui": True}),
            ("/api/system/log", "GET", {"media": True}),
            (FRAMES, "POST", {"upload": True}),
            (IMPORT, "POST", {"upload": True}),
        ]
        for path, method, flags in examples:
            with self.subTest(path=path):
                self.assertEqual(route(path, method, **flags), path)
                if flags:
                    with self.assertRaises(AdapterError):
                        route(path, method)
        for path, method, flags in [
            (FRAMES, "GET", {"upload": True}), (IMPORT, "DELETE", {"upload": True}),
            ("/api/state", "GET", {"media": True}), ("/api/generations", "POST", {"upload": True}),
            ("/api/system/log", "POST", {"ui": True}), ("/api/state", "HEAD", {}),
            ("/api/unlisted", "GET", {"ui": True}),
        ]:
            with self.subTest(path=path, method=method, flags=flags), self.assertRaises(AdapterError):
                route(path, method, **flags)

    def test_encoded_delimiters_do_not_expand_path_authority(self):
        for token in ("%2F", "%5C", "%2E%2E", "%252F", "%00", "%3F", "%23", "%", "é"):
            with self.subTest(token=token), self.assertRaises(AdapterError):
                route("/api/scores/" + token + ID, "GET")
        for path in ("//127.0.0.1/api/state", "/api/scores/a:b#fragment", "/api/scores/a\\b"):
            with self.subTest(path=path), self.assertRaises(AdapterError):
                route(path, "GET")

    def test_import_names_are_filenames_not_host_paths(self):
        safe = "/api/loras/import?" + urlencode({"name": "été studio.safetensors"})
        self.assertEqual(route(safe, "POST", upload=True), safe)
        for name in ("", "style.bin", "../style.safetensors", "/tmp/style.safetensors",
                     "C:\\models\\style.safetensors", "nested/style.safetensors", "a..b.safetensors"):
            with self.subTest(name=name), self.assertRaises(AdapterError):
                route("/api/loras/import?" + urlencode({"name": name}), "POST", upload=True)

    def test_upload_headers_have_route_specific_types_and_no_authority_headers(self):
        self.assertEqual(upload_headers(IMPORT, "application/octet-stream", {"X-Riff-LoRA-Metadata": "{}"}),
                         {"x-riff-lora-metadata": "{}"})
        for content_type in ("image/png", "video/h264"):
            self.assertEqual(upload_headers(FRAMES, content_type, {"X-Riff-Frame": "0"}), {"x-riff-frame": "0"})
        cases = [(IMPORT, "application/octet-stream", {name: "changed"})
                 for name in ("Host", "Authorization", "Content-Length", "Transfer-Encoding", "X-Riff-Request")]
        cases += [
            (IMPORT, "image/png", {}), (IMPORT, "application/octet-stream", {"x-riff-frame": "0"}),
            (FRAMES, "image/png", {}), (FRAMES, "application/octet-stream", {"x-riff-frame": "0"}),
            (FRAMES, "image/png", {"x-riff-frame": "0", "x-riff-lora-metadata": "{}"}),
            (IMPORT, "application/octet-stream", {"x-riff-lora-metadata": "{}", "X-Riff-LoRA-Metadata": "{}"}),
            (IMPORT, "application/octet-stream", ["unexpected"]),
        ]
        cases += [(FRAMES, "image/png", {"x-riff-frame": value})
                  for value in ("-1", "1.0", "100000000", "one", 0)]
        cases += [(IMPORT, "application/octet-stream", {"x-riff-lora-metadata": value})
                  for value in ("{}\r\nHost: evil.invalid", "\x00", "x" * 32769, {}, False)]
        for path, content_type, headers in cases:
            with self.subTest(path=path, content_type=content_type, headers=str(headers)[:100]), self.assertRaises(AdapterError):
                upload_headers(path, content_type, headers)


class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.backend = CaptureUploadBackend()
        self.store = UploadStore(self.root / "transfers", self.backend)
        self.addCleanup(self.store.close)

    def assert_empty(self):
        self.assertEqual(self.store.transfers, {})
        self.assertEqual(list(self.store.directory.glob("*.part")), [])

    def test_ordered_chunks_import_exactly_once_after_final_byte(self):
        first = self.store.chunk(upload_args(b"ab", total=6))
        self.assertFalse(first["complete"])
        self.assertEqual(first["received"], 2)
        self.assertEqual(self.backend.calls, [])
        upload_id = first["upload_id"]
        second = self.store.chunk(upload_args(b"cd", total=6, offset=2, upload_id=upload_id))
        self.assertEqual(second["upload_id"], upload_id)
        self.assertEqual(self.backend.calls, [])
        final = upload_args(b"ef", total=6, offset=4, upload_id=upload_id, final=True)
        result = self.store.chunk(final)
        self.assertTrue(result["complete"])
        self.assertEqual((result["received"], result["total"], result["status"]), (6, 6, 201))
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.backend.calls[0]["data"], b"abcdef")
        self.assertNotIn("base64", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assert_empty()
        with self.assertRaises(AdapterError):
            self.store.chunk(final)
        self.assertEqual(len(self.backend.calls), 1, "An uncertain final response must not replay an import.")

    def test_rejected_sequence_or_metadata_keeps_accepted_bytes_unchanged(self):
        first = self.store.chunk(upload_args(b"ab", total=6, headers={"x-riff-lora-metadata": "{}"}))
        upload_id = first["upload_id"]
        file = self.store.transfers[upload_id]["file"]
        base = upload_args(b"cd", total=6, offset=2, upload_id=upload_id, headers={"x-riff-lora-metadata": "{}"})
        changes = [
            {"offset": 0}, {"offset": 3}, {"total": 7}, {"final": True},
            {"path": IMPORT.replace("studio-style", "different-style")},
            {"headers": {"x-riff-lora-metadata": '{"name":"changed"}'}},
            {"path": FRAMES, "content_type": "image/png", "headers": {"x-riff-frame": "0"}},
            {"base64": base64.b64encode(b"cdef").decode("ascii"), "final": False},
            {"base64": base64.b64encode(b"cdefg").decode("ascii"), "final": True},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(AdapterError):
                self.store.chunk(base | change)
            self.assertEqual(file.read_bytes(), b"ab")
            self.assertEqual(self.store.transfers[upload_id]["received"], 2)
            self.assertEqual(self.backend.calls, [])
        result = self.store.chunk(base)
        self.assertEqual(result["received"], 4, "A rejected chunk does not poison a valid next chunk.")

    def test_malformed_chunks_do_not_allocate_or_import(self):
        cases = [
            {"base64": ""}, {"base64": "YQ==\n"}, {"base64": "%%%"}, {"base64": "YQ="},
            {"base64": "data:application/octet-stream;base64,YQ=="}, {"base64": None},
            {"base64": 12}, {"offset": True}, {"offset": -1}, {"offset": 1},
            {"total": True}, {"total": 0}, {"total": "4"}, {"final": 0}, {"final": "false"},
            {"final": True}, {"total": 1}, {"upload_id": "../elsewhere"}, {"upload_id": []},
            {"headers": {"X-Riff-LoRA-Metadata": "{}\r\nHost: evil.invalid"}},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(AdapterError):
                self.store.chunk(upload_args(**changes))
            self.assert_empty()
            self.assertEqual(self.backend.calls, [])

    def test_chunk_and_total_bounds_do_not_allocate_declared_total(self):
        for path, content_type, headers, limit in [
            (IMPORT, "application/octet-stream", {}, MAX_UPLOAD),
            (FRAMES, "image/png", {"x-riff-frame": "0"}, MAX_FRAME),
        ]:
            with self.subTest(path=path):
                args = upload_args(b"a", path=path, content_type=content_type, headers=headers, total=limit)
                result = self.store.chunk(args)
                staged = self.store.transfers[result["upload_id"]]["file"]
                self.assertEqual(staged.stat().st_size, 1)
                self.store.cancel(result["upload_id"])
                with self.assertRaises(AdapterError):
                    self.store.chunk(args | {"total": limit + 1})
        result = self.store.chunk(upload_args(b"x" * MAX_CHUNK, total=MAX_CHUNK + 1))
        self.assertEqual(result["bytes"], MAX_CHUNK)
        self.store.cancel(result["upload_id"])
        with self.assertRaises(AdapterError):
            self.store.chunk(upload_args(b"x" * (MAX_CHUNK + 1), total=MAX_CHUNK + 2))
        self.assert_empty()
        self.assertEqual(self.backend.calls, [])

    def test_active_upload_limit_recovers_after_cancellation(self):
        started = [self.store.chunk(upload_args())["upload_id"] for _ in range(4)]
        self.assertEqual(len(set(started)), 4)
        with self.assertRaises(AdapterError):
            self.store.chunk(upload_args())
        self.assertEqual(len(self.store.transfers), 4)
        self.store.cancel(started[0])
        new = self.store.chunk(upload_args())["upload_id"]
        self.assertNotIn(new, started)
        self.assertEqual(len(self.store.transfers), 4)

    def test_cancel_is_idempotent_and_cannot_import_or_resume(self):
        upload_id = self.store.chunk(upload_args())["upload_id"]
        for _ in range(2):
            self.assertEqual(self.store.cancel(upload_id), {"upload_id": upload_id, "cancelled": True})
        for invalid in (None, True, "../transfer", "A" * 32, "a" * 31):
            with self.subTest(invalid=invalid), self.assertRaises(AdapterError):
                self.store.cancel(invalid)
        with self.assertRaises(AdapterError):
            self.store.chunk(upload_args(b"cd", offset=2, upload_id=upload_id, final=True))
        self.assert_empty()
        self.assertEqual(self.backend.calls, [])

    def test_expiry_removes_only_inactive_stale_transfers(self):
        with patch("transport.time.monotonic", return_value=100):
            old = self.store.chunk(upload_args())["upload_id"]
        with patch("transport.time.monotonic", return_value=2000):
            live = self.store.chunk(upload_args())["upload_id"]
        with patch("transport.time.monotonic", return_value=3701):
            self.store.chunk(upload_args())
            self.assertNotIn(old, self.store.transfers)
            self.assertIn(live, self.store.transfers)
            with self.assertRaisesRegex(AdapterError, "expired"):
                self.store.chunk(upload_args(b"cd", offset=2, upload_id=old, final=True))
        self.assertFalse((self.store.directory / (old + ".part")).exists())
        self.assertEqual(self.backend.calls, [])

    def test_private_staging_cleanup_preserves_unrelated_files_and_symlink_targets(self):
        upload_id = self.store.chunk(upload_args())["upload_id"]
        staged = self.store.transfers[upload_id]["file"]
        self.assertEqual(stat.S_IMODE(self.store.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
        self.store.close()
        self.store.close()
        self.assert_empty()
        stale = self.store.directory / "interrupted.part"
        stale.write_bytes(b"partial")
        unrelated = self.store.directory / "retained.txt"
        unrelated.write_text("unrelated")
        target = self.root / "outside.txt"
        target.write_text("do not follow")
        link = self.store.directory / "outside.part"
        link.symlink_to(target)
        reopened = UploadStore(self.store.directory, self.backend)
        self.addCleanup(reopened.close)
        self.assertFalse(stale.exists())
        self.assertEqual(unrelated.read_text(), "unrelated")
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), "do not follow")

    def test_upstream_exception_removes_staging_without_retry(self):
        self.backend.failure = AdapterError("The native import did not complete.")
        first = self.store.chunk(upload_args())
        final = upload_args(b"cd", offset=2, upload_id=first["upload_id"], final=True)
        with self.assertRaisesRegex(AdapterError, "did not complete"):
            self.store.chunk(final)
        self.assert_empty()
        with self.assertRaises(AdapterError):
            self.store.chunk(final)
        self.assertEqual(len(self.backend.calls), 1)

    def test_committing_transfer_cannot_be_cancelled_expired_or_committed_twice(self):
        entered, release = Event(), Event()

        def hold(file):
            entered.set()
            if not release.wait(5):
                raise AssertionError("The test did not release the import fixture.")
            self.assertTrue(file.exists())

        self.backend.hook = hold
        with patch("transport.time.monotonic", return_value=100):
            upload_id = self.store.chunk(upload_args())["upload_id"]
            final = upload_args(b"cd", offset=2, upload_id=upload_id, final=True)
            with ThreadPoolExecutor(max_workers=1) as worker:
                pending = worker.submit(self.store.chunk, final)
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaisesRegex(AdapterError, "being imported"):
                        self.store.cancel(upload_id)
                    with patch("transport.time.monotonic", return_value=10000):
                        self.store.chunk(upload_args())
                        self.assertIn(upload_id, self.store.transfers)
                        with self.assertRaises(AdapterError):
                            self.store.chunk(final)
                finally:
                    release.set()
                self.assertTrue(pending.result(timeout=2)["complete"])
        self.assertNotIn(upload_id, self.store.transfers)
        self.assertEqual(len(self.backend.calls), 1)


class AuditedFile:
    """Instrument file reads while leaving HTTP and disk I/O real."""
    def __init__(self, path):
        self.path, self.read_sizes = path, []

    def stat(self):
        return self.path.stat()

    def open(self, mode):
        if mode != "rb":
            raise AssertionError("Uploads must read binary files.")
        owner = self

        class Reader:
            def __enter__(self):
                self.file = owner.path.open(mode)
                return self

            def read(self, size=-1):
                if not 0 < size <= MAX_CHUNK:
                    raise AssertionError("An upload attempted an unbounded file read.")
                owner.read_sizes.append(size)
                return self.file.read(size)

            def __exit__(self, *args):
                self.file.close()

        return Reader()


class LoopbackUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                self.connection.settimeout(5)
                remaining = int(self.headers.get("Content-Length", "0"))
                blocks = []
                while remaining:
                    block = self.rfile.read(min(65536, remaining))
                    if not block:
                        break
                    blocks.append(block)
                    remaining -= len(block)
                self.server.received.append({"path": self.path, "headers": dict(self.headers),
                                             "data": b"".join(blocks), "missing": remaining})
                if self.server.drop_response:
                    self.close_connection = True
                    return
                status, raw, headers = self.server.reply
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=lambda: cls.server.serve_forever(poll_interval=0.01), daemon=True)
        cls.thread.start()
        cls.backend = LoopbackBackend(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.file = self.root / "opaque-upload.bin"
        self.file.write_bytes(b"opaque transport fixture")
        self.server.received = []
        self.server.reply = (201, b'{"accepted_by_test_fixture":true}', {})
        self.server.drop_response = False

    def test_large_file_streams_bounded_reads_to_private_origin_with_exact_length(self):
        payload = bytes(range(256)) * (2 * MAX_CHUNK // 256) + b"final block"
        self.file.write_bytes(payload)
        audited = AuditedFile(self.file)
        headers = {"x-riff-lora-metadata": '{"name":"transport fixture"}'}
        status, body = self.backend.upload_file(IMPORT, audited, "application/octet-stream", headers)
        self.assertEqual((status, body), (201, {"accepted_by_test_fixture": True}))
        self.assertGreaterEqual(len(audited.read_sizes), 3)
        self.assertEqual(len(self.server.received), 1)
        received = self.server.received[0]
        self.assertEqual(received["path"], IMPORT)
        self.assertEqual(received["data"], payload)
        self.assertEqual(received["missing"], 0)
        self.assertEqual(received["headers"]["Host"], f"127.0.0.1:{self.server.server_port}")
        self.assertEqual(received["headers"]["X-Riff-Request"], "1")
        self.assertEqual(received["headers"]["Content-Length"], str(len(payload)))
        self.assertEqual(received["headers"]["Content-Type"], "application/octet-stream")
        self.assertEqual(received["headers"]["x-riff-lora-metadata"], headers["x-riff-lora-metadata"])
        self.assertNotIn("Transfer-Encoding", received["headers"])

    def test_video_frame_mime_and_index_survive_the_complete_store_transport(self):
        store = UploadStore(self.root / "frames", self.backend)
        self.addCleanup(store.close)
        for content_type in ("image/png", "video/h264"):
            with self.subTest(content_type=content_type):
                result = store.chunk(upload_args(b"frame", total=5, final=True, path=FRAMES,
                                                 content_type=content_type, headers={"X-Riff-Frame": "12"}))
                received = self.server.received[-1]
                self.assertTrue(result["complete"])
                self.assertEqual(received["path"], FRAMES)
                self.assertEqual(received["data"], b"frame")
                self.assertEqual(received["headers"]["Content-Type"], content_type)
                self.assertEqual(received["headers"]["x-riff-frame"], "12")
                self.assertEqual(list(store.directory.glob("*.part")), [])

    def test_upstream_failure_status_and_message_reach_app_without_replaying_import(self):
        ui = self.root / "studio.html"
        ui.write_text("<!doctype html><p>Gateway test fixture</p>")
        adapter = Adapter(self.backend, DraftStore(self.root / "draft.sqlite3"), ui)
        self.addCleanup(adapter.close)
        for status in (400, 409, 413, 503):
            with self.subTest(status=status):
                error = {"error": "The supplied LoRA metadata or tensor data was rejected."}
                self.server.reply = (status, json.dumps(error).encode(), {})
                first = adapter.call("riff_upload_chunk", upload_args(headers={"X-Riff-LoRA-Metadata": "{malformed"}))
                self.assertEqual(first["content"], [])
                final = upload_args(b"cd", offset=2, final=True,
                                    upload_id=first["structuredContent"]["upload_id"],
                                    headers={"X-Riff-LoRA-Metadata": "{malformed"})
                count = len(self.server.received)
                result = adapter.call("riff_upload_chunk", final)
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["status"], status)
                self.assertEqual(result["structuredContent"]["body"], error)
                self.assertEqual(result["content"], [{"type": "text", "text": error["error"]}])
                self.assertNotIn("base64", json.dumps(result))
                self.assertEqual(len(self.server.received), count + 1)
                self.assertEqual(list(adapter.uploads.directory.glob("*.part")), [])
                with self.assertRaises(AdapterError):
                    adapter.call("riff_upload_chunk", final)
                self.assertEqual(len(self.server.received), count + 1)

    def test_invalid_json_upload_responses_fail_after_one_request(self):
        for raw in (b"not-json", b"[]", b'{"bad":NaN}', b"\xff"):
            with self.subTest(raw=raw):
                self.server.reply = (200, raw, {})
                before = len(self.server.received)
                with self.assertRaises(AdapterError):
                    self.backend.upload_file(IMPORT, self.file, "application/octet-stream", {})
                self.assertEqual(len(self.server.received), before + 1)

    def test_oversized_json_upload_response_is_bounded(self):
        self.server.reply = (200, b" " * (MAX_JSON + 1), {})
        with self.assertRaisesRegex(AdapterError, "transfer limit"):
            self.backend.upload_file(IMPORT, self.file, "application/octet-stream", {})
        self.assertEqual(len(self.server.received), 1)

    def test_upload_redirect_is_not_followed(self):
        destination = f"http://127.0.0.1:{self.server.server_port}/must-not-follow"
        self.server.reply = (307, b"{}", {"Location": destination})
        with self.assertRaisesRegex(AdapterError, "redirects"):
            self.backend.upload_file(IMPORT, self.file, "application/octet-stream", {})
        self.assertEqual([item["path"] for item in self.server.received], [IMPORT])

    def test_lost_upload_response_is_not_retried(self):
        self.server.drop_response = True
        with self.assertRaisesRegex(AdapterError, "not retried"):
            self.backend.upload_file(IMPORT, self.file, "application/octet-stream", {})
        self.assertEqual(len(self.server.received), 1)
        self.assertEqual(self.server.received[0]["data"], self.file.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
