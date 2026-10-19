#!/usr/bin/env python3
"""Riff MCP over stdio: modern per-request discovery and legacy initialization."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import sys
import threading

from adapter import (Adapter, AdapterError, DraftStore, LoopbackBackend, TOOLS, TOOL_MAP,
                     UI_URI, MIME, VERSION, MAX_INPUT, SETTINGS_CAPABILITY)
from runtime import ManagedRiff

CURRENT_PROTOCOL = "2026-07-28"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
PROTOCOL_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = {"name": "riff-studio-adapter", "title": "Riff", "version": VERSION}
INSTRUCTIONS = (
    "Use Riff's original visual studio and shared draft. Read riff_get_draft before changing a recipe; "
    "save with its expected revision. Read /api/capabilities for the native recipe schema. "
    "A generation submission is queued work, not a successful recording. Poll the job to completion. "
    "Use app-only tools only from the studio. Never place credentials or audio bytes in chat context."
)


def capabilities(*, modern):
    return {"tools": {}, "resources": {},
            "extensions" if modern else "experimental": {"openai/settings": SETTINGS_CAPABILITY}}


class RPC:
    def __init__(self, adapter):
        self.adapter, self.initialized = adapter, False

    def handle(self, msg):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return self.error(None, -32600, "Invalid JSON-RPC request.")
        # Request methods without ids are notifications, never mutations.
        if "id" not in msg:
            return None
        mid = msg["id"]
        if not isinstance(mid, (str, int)) or isinstance(mid, bool):
            return self.error(None, -32600, "Invalid request id.")
        method, params = msg["method"], msg.get("params", {})
        if not isinstance(params, dict):
            return self.error(mid, -32602, "params must be an object.")
        metadata = params.get("_meta", {})
        if not isinstance(metadata, dict):
            return self.error(mid, -32602, "Request metadata must be an object.")
        requested = metadata.get(PROTOCOL_KEY)
        has_version = PROTOCOL_KEY in metadata
        modern = method == "server/discover" or has_version
        if has_version:
            if not isinstance(requested, str) or not requested:
                return self.error(mid, -32602, "Protocol version metadata must be a nonempty string.")
            if requested != CURRENT_PROTOCOL:
                return self.error(mid, -32022, "Unsupported protocol version.",
                                  {"supported": [CURRENT_PROTOCOL], "requested": requested})
            if not isinstance(metadata.get(CLIENT_CAPABILITIES_KEY), dict):
                return self.error(mid, -32602, "Modern requests require client capabilities metadata.")
        try:
            if method == "server/discover":
                result = {"supportedVersions": [CURRENT_PROTOCOL], "capabilities": capabilities(modern=True),
                          "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO}, "instructions": INSTRUCTIONS}
            elif method == "initialize":
                version = params.get("protocolVersion")
                version = version if version in PROTOCOLS else PROTOCOLS[0]
                self.initialized = True
                modern = False
                result = {"protocolVersion": version, "serverInfo": SERVER_INFO,
                          "capabilities": capabilities(modern=False), "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif not modern and not self.initialized:
                return self.error(mid, -32000, "Initialize the legacy connection or provide modern request metadata.")
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "resources/list":
                result = {"resources": [{"uri": UI_URI, "name": "Riff Studio", "mimeType": MIME}]}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": []}
            elif method == "resources/read":
                if params.get("uri") != UI_URI:
                    return self.error(mid, -32602 if modern else -32002, "Unknown Riff resource.")
                result = self.adapter.resource(params["uri"])
            elif method == "tools/call":
                name = params.get("name")
                if not isinstance(name, str) or name not in TOOL_MAP:
                    return self.error(mid, -32602, "Unknown Riff tool.")
                try:
                    result = self.adapter.call(name, params.get("arguments", {}))
                except (AdapterError, KeyError, TypeError, ValueError) as exc:
                    result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
            else:
                return self.error(mid, -32601, "Unsupported MCP method.")
            if modern:
                result = {**result, "resultType": "complete"}
                if method in ("server/discover", "tools/list", "resources/list", "resources/templates/list", "resources/read"):
                    result.update(ttlMs=0, cacheScope="private")
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except (AdapterError, KeyError, ValueError, TypeError) as exc:
            return self.error(mid, -32602, str(exc))
        except Exception as exc:
            # Never log request arguments: they may contain app-entered keys.
            print(f"Riff adapter internal error: {type(exc).__name__}", file=sys.stderr)
            return self.error(mid, -32603, "Riff adapter internal error; inspect its private log.")

    @staticmethod
    def error(mid, code, message, data=None):
        result = {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
        if data is not None:
            result["error"]["data"] = data
        return result


def serve(adapter, source=None, sink=None, *, concurrent=False, on_disconnect=None):
    source, sink = source or sys.stdin.buffer, sink or sys.stdout
    rpc, output_lock, pending_lock = RPC(adapter), threading.Lock(), threading.Lock()
    active_ids = set()

    def emit(response):
        if response is not None:
            wire = json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n"
            with output_lock:
                sink.write(wire)
                sink.flush()

    def execute(msg):
        try:
            emit(rpc.handle(msg))
        finally:
            with pending_lock:
                active_ids.discard(msg.get("id"))

    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="riff-mcp") if concurrent else None
    # Bound queued messages so a fast stdin writer cannot exhaust host memory.
    slots = threading.BoundedSemaphore(32)
    try:
        while True:
            raw = source.readline(MAX_INPUT + 4097)
            if not raw:
                return
            if len(raw) > MAX_INPUT + 4096:
                emit(RPC.error(None, -32600, "MCP request exceeds the transfer limit."))
                return
            try:
                msg = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeError, RecursionError):
                emit(RPC.error(None, -32700, "Invalid JSON."))
                continue
            if not executor or not isinstance(msg, dict) or msg.get("method") in ("initialize", "server/discover", "ping") or "id" not in msg:
                emit(rpc.handle(msg))
                continue
            mid = msg.get("id")
            if not isinstance(mid, (int, str)) or isinstance(mid, bool):
                emit(rpc.handle(msg))
                continue
            with pending_lock:
                duplicate = mid in active_ids
                if not duplicate:
                    active_ids.add(mid)
            if duplicate:
                emit(RPC.error(mid, -32600, "Request id is already in progress."))
                continue
            slots.acquire()
            future = executor.submit(execute, msg)
            future.add_done_callback(lambda _: slots.release())
    finally:
        if executor:
            # Stop queued tool work, then cancel native/provider processes so
            # an outstanding writing call cannot hold host shutdown for minutes.
            executor.shutdown(wait=False, cancel_futures=True)
            if on_disconnect:
                on_disconnect()
            executor.shutdown(wait=True, cancel_futures=True)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--riff-root", type=Path, default=root / "riff")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ui-file", type=Path, default=root / "dist" / "studio.html")
    args = parser.parse_args()
    protocol_output = sys.stdout
    sys.stdout = sys.stderr
    adapter = None
    previous_handlers = {}

    def stop(signum, frame):
        raise KeyboardInterrupt

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, stop)
    try:
        managed = ManagedRiff(args.riff_root, args.workspace)
        with managed as port:
            adapter = Adapter(LoopbackBackend(port), DraftStore(args.workspace / "adapter-draft.sqlite3"), args.ui_file)
            try:
                serve(adapter, sink=protocol_output, concurrent=True, on_disconnect=managed.stop_work)
            except (KeyboardInterrupt, BrokenPipeError):
                pass
            finally:
                adapter.close()
    finally:
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
        sys.stdout = protocol_output


if __name__ == "__main__":
    main()
