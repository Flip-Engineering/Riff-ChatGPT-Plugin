"""Riff tools, shared drafts, settings, and the complete embedded-studio surface.

The native application remains authoritative for generation and validation.
Binary payloads are bounded and carried only in app tool-result metadata.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Protocol

from routes import AdapterError, ID, HASH, TOKEN, route
from transport import LoopbackBackend, NoRedirect, UploadStore, MAX_JSON, MAX_CHUNK, MAX_UPLOAD

VERSION = "0.2.0"
UI_URI = "ui://riff/studio/adapter-v0.2.1.html"
MIME = "text/html;profile=mcp-app"
MAX_BODY = 256 * 1024
# Binary chunks are one MiB before base64. The wire budget includes metadata.
MAX_INPUT = 2 * 1024 * 1024


class Backend(Protocol):
    def json_request(self, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]: ...
    def audio_chunk(self, track_id: str, offset: int, length: int) -> tuple[bytes, int]: ...
    def media_chunk(self, path: str, offset: int, length: int) -> tuple[bytes, int, str, str]: ...


def object_body(value: Any, limit=MAX_BODY) -> dict:
    if not isinstance(value, dict):
        raise AdapterError("Expected a JSON object.")
    try:
        size = len(json.dumps(value, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise AdapterError("Only finite JSON values are accepted.") from exc
    if size > limit:
        raise AdapterError(f"Input exceeds {limit // 1024} KiB.")
    return value


def validate(value, spec, location="arguments"):
    """Validate the JSON Schema subset used by every declared tool/settings input."""
    kind = spec.get("type")
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "boolean": lambda x: type(x) is bool,
              "integer": lambda x: type(x) is int, "number": lambda x: type(x) in (int, float)}
    if kind in checks and not checks[kind](value):
        raise AdapterError(f"{location} must be {kind}.")
    if "enum" in spec and value not in spec["enum"]:
        raise AdapterError(f"{location} is not an allowed value.")
    if kind in ("integer", "number"):
        if "minimum" in spec and value < spec["minimum"] or "maximum" in spec and value > spec["maximum"]:
            raise AdapterError(f"{location} is outside its allowed range.")
    elif kind == "string":
        if len(value) > spec.get("maxLength", MAX_INPUT):
            raise AdapterError(f"{location} is too long.")
        if "pattern" in spec and not re.search(spec["pattern"], value):
            raise AdapterError(f"{location} has an invalid format.")
    elif kind == "object":
        properties = spec.get("properties", {})
        if set(spec.get("required", [])) - set(value):
            raise AdapterError(f"{location} is missing required fields.")
        if spec.get("additionalProperties") is False and set(value) - set(properties):
            raise AdapterError(f"{location} contains unexpected fields.")
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key], f"{location}.{key}")
    elif kind == "array" and "items" in spec:
        for index, item in enumerate(value):
            validate(item, spec["items"], f"{location}[{index}]")


class DraftStore:
    """Single-user durable draft with optimistic concurrency across UI instances."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS draft (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, body TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO draft VALUES (1, 0, '{}')")
        path.chmod(0o600)

    def load(self) -> dict:
        with sqlite3.connect(self.path) as db:
            revision, body = db.execute("SELECT revision, body FROM draft WHERE id=1").fetchone()
        return {"revision": revision, "recipe": json.loads(body)}

    def save(self, recipe: dict, revision: int) -> dict:
        object_body(recipe)
        if type(revision) is not int or revision < 0:
            raise AdapterError("An integer expected_revision is required.")
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("UPDATE draft SET revision=revision+1, body=? WHERE id=1 AND revision=?",
                                (json.dumps(recipe, allow_nan=False), revision))
            if cursor.rowcount != 1:
                raise AdapterError("Draft conflict: restore the latest saved draft before saving again.")
        return {"revision": revision + 1, "recipe": recipe}


def schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


SETTINGS_SCHEMA = schema({
    "auto_save_draft": {"type": "boolean", "title": "Save draft changes automatically", "default": False},
    "context_sharing": {"type": "boolean", "title": "Share the active song with ChatGPT", "default": True},
    "media_cache_mib": {"type": "integer", "title": "Playback cache (MiB)", "minimum": 32, "maximum": 1024, "default": 256},
    "default_view": {"type": "string", "title": "Opening view", "enum": ["studio", "library"], "default": "studio"},
})
SETTINGS_DEFAULTS = {key: value["default"] for key, value in SETTINGS_SCHEMA["properties"].items()}


class SettingsStore:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS plugin_settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO plugin_settings VALUES(1, '{}')")

    def read(self):
        with sqlite3.connect(self.path) as db:
            body = json.loads(db.execute("SELECT body FROM plugin_settings WHERE id=1").fetchone()[0])
        return {"schema": SETTINGS_SCHEMA, "values": {**SETTINGS_DEFAULTS, **body}}

    def update(self, changes):
        object_body(changes)
        validate(changes, SETTINGS_SCHEMA, "set")
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute("SELECT body FROM plugin_settings WHERE id=1").fetchone()[0])
            current.update(changes)
            db.execute("UPDATE plugin_settings SET body=? WHERE id=1", (json.dumps(current, allow_nan=False),))
        return self.read()


def tool(name, description, input_schema, *, title=None, read=False, destructive=False,
         app_only=False, entrypoint=None, open_world=False, output_schema=None):
    item = {"name": name, "title": title or name.replace("riff_", "").replace("_", " ").title(),
            "description": description, "inputSchema": input_schema,
            "annotations": {"readOnlyHint": read, "destructiveHint": destructive,
                            "idempotentHint": read, "openWorldHint": open_world}}
    meta = {}
    if app_only:
        meta["ui"] = {"visibility": ["app"]}
    if entrypoint:
        meta.setdefault("ui", {})["resourceUri"] = UI_URI
        meta["openai/ui"] = {"entrypoints": [{"type": entrypoint}]}
    if meta:
        item["_meta"] = meta
    if output_schema:
        item["outputSchema"] = output_schema
    return item


PATH_FIELD = {"type": "string", "maxLength": 8192}
ID_FIELD = {"type": "string", "pattern": "^" + ID + "$"}
TOOLS = [
    tool("riff_open_studio", "Open the complete Riff visual studio and its current saved draft. Does not generate music.",
         schema(), title="Riff", read=True, entrypoint="global"),
    tool("riff_open_project", "Open the current song beside this conversation, with the shared Riff draft and recording library.",
         schema(), title="Current song", read=True, entrypoint="thread"),
    tool("riff_read", "Read Riff state, capabilities, tracks, scores, saved acoustics, queues, reviews, and LoRA metadata. Hub/model catalog routes contact their providers.",
         schema({"path": PATH_FIELD}, ["path"]), read=True, open_world=True),
    tool("riff_generate", "Queue a real YuE2 render or symbolic plan from an explicit Riff recipe. Read /api/capabilities for its current schema. Submission is not rendering success; inspect the returned job.",
         schema({"recipe": {"type": "object"}, "plan_only": {"type": "boolean", "default": False}}, ["recipe"])),
    tool("riff_edit", "Edit track metadata or presets, or cancel/reorder a queued job. Use the studio for credentials and permanent recording deletion.",
         schema({"path": PATH_FIELD, "method": {"type": "string", "enum": ["POST", "PATCH", "DELETE"]}, "body": {"type": "object"}}, ["path", "method", "body"]), destructive=True),
    tool("riff_get_draft", "Read the shared saved recipe and revision before making a conversational edit.", schema(), read=True),
    tool("riff_save_draft", "Save a recipe only when expected_revision matches. Open studios receive the new draft without overwriting their unsaved edits. Saving does not render music.",
         schema({"recipe": {"type": "object"}, "expected_revision": {"type": "integer", "minimum": 0}}, ["recipe", "expected_revision"])),
    tool("riff_setup", "Check readiness, download the pinned music models into the plugin workspace, or cancel that download. The plugin supplies its own native runtime; setup does not install external applications.",
         schema({"action": {"type": "string", "enum": ["setup", "check", "cancel"]}, "options": {"type": "object"}}, ["action"]), open_world=True),
    tool("riff_write", "Run Riff's configured writing provider for ideas or score revisions, or cancel it. To compose with ChatGPT directly, edit the shared draft instead. Provider calls may consume the user's configured API usage.",
         schema({"action": {"type": "string", "enum": ["ideas", "revise_score", "cancel"]}, "recipe": {"type": "object"}}, ["action"]), open_world=True),
    tool("riff_review", "Request or cancel a listening review using the user's enabled Riff provider. Starting a review transmits the chosen audio to that provider.",
         schema({"action": {"type": "string", "enum": ["start", "cancel"]}, "track_id": ID_FIELD, "review_id": ID_FIELD, "options": {"type": "object"}}, ["action"]), open_world=True),
    tool("riff_lora", "Install a pinned Hub LoRA, edit installed adapter metadata, remove an unreferenced adapter, or cancel a download. Read capabilities and LoRA detail first; deletion requires body.confirm=true.",
         schema({"action": {"type": "string", "enum": ["install", "update", "delete", "cancel"]},
                 "id": {"type": "string", "pattern": "^[a-f0-9]{32,64}$"}, "body": {"type": "object"}}, ["action"]), destructive=True, open_world=True),
    tool("riff_settings_read", "Read Riff's ChatGPT display and draft preferences. No credentials are included.", schema(), read=True,
         output_schema=schema({"schema": {"type": "object"}, "values": {"type": "object"}}, ["schema", "values"])),
    tool("riff_settings_update", "Persist only the supplied Riff display and draft preference changes.",
         schema({"set": SETTINGS_SCHEMA}, ["set"])),
    tool("riff_ui_request", "Embedded-studio JSON transport for the full Riff interface. Credential mutations remain confined to the app surface. Native validation and errors are preserved.",
         schema({"path": PATH_FIELD, "method": {"type": "string", "enum": ["GET", "POST", "PATCH", "DELETE"], "default": "GET"}, "body": {"type": "object"}}, ["path"]), app_only=True, destructive=True, open_world=True),
    tool("riff_audio_chunk", "UI-only bounded WAV transfer. Bytes are returned only in result metadata.",
         schema({"track_id": ID_FIELD, "offset": {"type": "integer", "minimum": 0}, "length": {"type": "integer", "minimum": 1, "maximum": MAX_CHUNK}}, ["track_id", "offset", "length"]), read=True, app_only=True),
    tool("riff_media_chunk", "UI-only bounded audio, video, preview image, or setup-log transfer. No media bytes are placed in conversation content.",
         schema({"path": PATH_FIELD, "offset": {"type": "integer", "minimum": 0}, "length": {"type": "integer", "minimum": 1, "maximum": MAX_CHUNK}}, ["path", "offset", "length"]), read=True, app_only=True, open_world=True),
    tool("riff_upload_chunk", "UI-only ordered transfer of a browser-selected LoRA or rendered video frame. Imports only after the last byte; never accepts a host file path.",
         schema({"path": PATH_FIELD, "upload_id": ID_FIELD, "offset": {"type": "integer", "minimum": 0},
                 "total": {"type": "integer", "minimum": 1, "maximum": MAX_UPLOAD}, "base64": {"type": "string", "maxLength": 1398104},
                 "final": {"type": "boolean"}, "content_type": {"type": "string", "enum": ["application/octet-stream", "image/png", "video/h264"]},
                 "headers": {"type": "object"}}, ["path", "offset", "total", "base64", "final", "content_type"]), app_only=True),
    tool("riff_upload_cancel", "Discard an incomplete app file transfer without importing it.", schema({"upload_id": ID_FIELD}, ["upload_id"]), app_only=True),
]
TOOL_MAP = {item["name"]: item for item in TOOLS}
SETTINGS_CAPABILITY = {"readTool": "riff_settings_read", "updateTool": "riff_settings_update"}


def json_result(body, status=200, *, visible=True):
    return {"structuredContent": {"status": status, "body": body},
            "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}] if visible else [], "isError": status >= 400}


class Adapter:
    def __init__(self, backend: Backend, drafts: DraftStore, ui_file: Path):
        self.backend, self.drafts, self.ui_file = backend, drafts, ui_file
        self.settings = SettingsStore(drafts.path)
        self.uploads = UploadStore(drafts.path.parent / "adapter-transfers", backend)

    def close(self):
        self.uploads.close()

    def engine_tuning(self, payload):
        """Retain the original form without allowing it to choose executables."""
        fixed = {"backend", "binary", "model_root", "model_file", "vae_file"}
        tuning = {"threads", "device", "warm_engine"}
        if set(payload) - fixed - tuning:
            raise AdapterError("Unknown plugin engine preference.")
        if set(payload) & fixed:
            status, state = self.backend.json_request("/api/state")
            current = state.get("engine", {})
            if status != 200 or any(payload[key] != current.get(key) for key in set(payload) & fixed):
                raise AdapterError("The plugin manages its engine and model locations. Only performance preferences can change.")
        return {key: value for key, value in payload.items() if key in tuning}

    def call(self, name: str, args: dict) -> dict:
        object_body(args, MAX_INPUT)
        if not isinstance(name, str) or name not in TOOL_MAP:
            raise AdapterError("Unknown Riff tool.")
        validate(args, TOOL_MAP[name]["inputSchema"])
        if name in ("riff_open_studio", "riff_open_project"):
            status, body = self.backend.json_request("/api/state")
            return json_result({"state": body, "draft": self.drafts.load(), "adapter_version": VERSION}, status)
        if name == "riff_get_draft":
            return json_result(self.drafts.load())
        if name == "riff_save_draft":
            return json_result(self.drafts.save(object_body(args["recipe"]), args["expected_revision"]))
        if name in ("riff_settings_read", "riff_settings_update"):
            settings = self.settings.read() if name.endswith("read") else self.settings.update(args["set"])
            return {"structuredContent": settings, "content": [{"type": "text", "text": json.dumps(settings)}]}
        if name in ("riff_audio_chunk", "riff_media_chunk"):
            offset, length = args["offset"], args["length"]
            if name == "riff_audio_chunk":
                raw, total = self.backend.audio_chunk(args["track_id"], offset, length)
                mime, filename, key = "audio/wav", "riff-" + args["track_id"] + ".wav", "riff/audio"
            else:
                path = route(args["path"], "GET", ui=True, media=True)
                raw, total, mime, filename = self.backend.media_chunk(path, offset, length)
                key = "riff/media"
            if (not isinstance(raw, bytes) or type(total) is not int or total < 0 or len(raw) > length
                    or offset + len(raw) > total or not raw and total != 0):
                raise AdapterError("Invalid media response.")
            if not isinstance(mime, str) or mime not in ("audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg", "audio/flac", "audio/mp4", "video/mp4", "video/webm", "image/png", "image/jpeg", "image/webp", "text/plain"):
                raise AdapterError("Unsupported Riff media type.")
            return {"content": [], "structuredContent": {"offset": offset, "bytes": len(raw), "total": total, "eof": offset + len(raw) == total},
                    "_meta": {key: {"base64": base64.b64encode(raw).decode("ascii"), "mimeType": mime, "name": filename}}}
        if name == "riff_upload_chunk":
            value = self.uploads.chunk(args)
            failed = value["status"] >= 400
            return {"structuredContent": value, "content": [{"type": "text", "text": str(value["body"].get("error", "Riff import failed."))}] if failed else [], "isError": failed}
        if name == "riff_upload_cancel":
            return json_result(self.uploads.cancel(args["upload_id"]), visible=False)
        if name == "riff_generate":
            path = "/api/plans" if args.get("plan_only", False) else "/api/generations"
            status, body = self.backend.json_request(path, "POST", object_body(args["recipe"]))
        elif name == "riff_read":
            status, body = self.backend.json_request(route(args["path"], "GET"))
        elif name == "riff_setup":
            status, body = self.backend.json_request("/api/system/" + args["action"], "POST", object_body(args.get("options", {})))
        elif name == "riff_write":
            path = {"ideas": "/api/inspiration", "revise_score": "/api/composition/revise", "cancel": "/api/inspiration/cancel"}[args["action"]]
            status, body = self.backend.json_request(path, "POST", object_body(args.get("recipe", {})))
        elif name == "riff_review":
            field = "track_id" if args["action"] == "start" else "review_id"
            if field not in args:
                raise AdapterError(f"{field} is required for this action.")
            path = f"/api/tracks/{args[field]}/reviews" if field == "track_id" else f"/api/reviews/{args[field]}/cancel"
            status, body = self.backend.json_request(path, "POST", object_body(args.get("options", {})))
        elif name == "riff_lora":
            action, ident = args["action"], args.get("id", "")
            if action == "install":
                path, method = "/api/loras", "POST"
            elif action == "cancel" and re.fullmatch(ID, ident):
                path, method = f"/api/loras/tasks/{ident}/cancel", "POST"
            elif action in ("update", "delete") and re.fullmatch(HASH, ident):
                path, method = f"/api/loras/{ident}", "PATCH" if action == "update" else "DELETE"
            else:
                raise AdapterError("This LoRA action requires its exact library or task identifier.")
            status, body = self.backend.json_request(path, method, object_body(args.get("body", {})))
        elif name == "riff_ui_request":
            method = args.get("method", "GET")
            path = route(args["path"], method, ui=True)
            if method == "GET" and args.get("body"):
                raise AdapterError("GET requests cannot carry a mutation body.")
            payload = None if method == "GET" else object_body(args.get("body", {}))
            if path == "/api/system/engine" and method == "POST":
                payload = self.engine_tuning(payload)
            status, body = self.backend.json_request(path, method, payload)
            return json_result(body, status, visible=False)
        else:
            method = args["method"]
            path = route(args["path"], method)
            payload = object_body(args["body"])
            if method == "PATCH" and re.fullmatch(rf"/api/tracks/{ID}", path):
                if set(payload) - {"title", "notes", "favorite", "archived"}:
                    raise AdapterError("Only track metadata fields may be edited.")
            status, body = self.backend.json_request(path, method, payload)
        return json_result(body, status)

    def resource(self, uri: str) -> dict:
        if uri != UI_URI:
            raise AdapterError("Unknown Riff resource.")
        if not self.ui_file.is_file():
            raise AdapterError("The packaged Riff studio resource is missing. Reinstall the complete plugin package.")
        return {"contents": [{"uri": UI_URI, "mimeType": MIME, "text": self.ui_file.read_text(),
                              "_meta": {"ui": {"prefersBorder": False, "csp": {"connectDomains": [], "resourceDomains": ["blob:", "data:"]}},
                                        "openai/ui": {"preferredDisplayMode": "fullscreen", "availableDisplayModes": ["inline", "fullscreen"]}}}]}
