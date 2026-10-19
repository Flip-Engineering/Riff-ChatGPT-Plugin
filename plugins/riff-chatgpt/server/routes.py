"""Finite Riff HTTP surface shared by the model tools and the embedded studio.

Paths are canonicalized once. Callers cannot choose a host, filesystem path,
request header outside the two binary-upload fields, or an unlisted action.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

ID = r"[a-f0-9]{32}"
HASH = r"[a-f0-9]{64}"
TOKEN = r"[A-Za-z0-9:_-]{1,200}"
PRESET = r"[a-z0-9-]{1,200}"


class AdapterError(ValueError):
    pass


READS = [
    r"/api/(state|health|capabilities|system|loras)",
    rf"/api/tracks/{ID}(?:/(recipe|lineage|visualization|reviews))?",
    rf"/api/jobs/{ID}", rf"/api/(scores|acoustics)/{TOKEN}",
    rf"/api/presets/{PRESET}", rf"/api/reviews/{ID}",
    r"/api/review/(settings|models)", rf"/api/video-exports/{ID}",
    r"/api/loras/hub(?:/detail)?", rf"/api/loras/{HASH}(?:/updates)?",
    rf"/api/loras/tasks/{ID}",
]
EDITS = {
    "POST": [rf"/api/jobs/{ID}/(cancel|move)", r"/api/presets"],
    "PATCH": [rf"/api/tracks/{ID}", rf"/api/presets/{PRESET}"],
    "DELETE": [rf"/api/presets/{PRESET}"],
}
UI_EDITS = {
    "POST": EDITS["POST"] + [
        r"/api/(generations|plans|loras|inspiration)",
        r"/api/inspiration/cancel", r"/api/composition/revise",
        r"/api/system/(setup|engine|check|update|cancel|preferences|restart)",
        r"/api/review/settings", rf"/api/tracks/{ID}/(reviews|video-exports)",
        rf"/api/video-exports/{ID}/(finish|cancel)",
        rf"/api/reviews/{ID}/cancel", rf"/api/loras/tasks/{ID}/cancel",
    ],
    "PATCH": EDITS["PATCH"] + [rf"/api/loras/{HASH}"],
    "DELETE": EDITS["DELETE"] + [rf"/api/tracks/{ID}", rf"/api/loras/{HASH}", r"/api/review/key"],
}
MEDIA = [rf"/api/tracks/{ID}/audio", rf"/api/video-exports/{ID}/download",
         r"/api/loras/hub/media", r"/api/system/log"]
UPLOADS = [r"/api/loras/import", rf"/api/video-exports/{ID}/frames"]


def canonical(path):
    if not isinstance(path, str) or not path.startswith("/api/") or len(path) > 8192:
        raise AdapterError("Invalid Riff route.")
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or "\\" in path:
        raise AdapterError("Invalid characters in Riff route.")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise AdapterError("External or fragment routes are not permitted.")
    # Riff percent-encodes the colon in opaque score/acoustic identifiers.
    # No other encoded path syntax is needed by its public API.
    if re.search(r"%(?!3[aA])", parsed.path):
        raise AdapterError("Unsupported encoded Riff path.")
    try:
        decoded = unquote(parsed.path, errors="strict")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=16, errors="strict")
    except (ValueError, UnicodeError) as exc:
        raise AdapterError("Invalid encoded Riff route.") from exc
    if (any(c in decoded for c in ("%", "\\", "?", "#")) or ".." in decoded
            or "//" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
        raise AdapterError("Encoded or traversing Riff routes are not permitted.")
    # Paths are ASCII capability identifiers; international titles live in JSON.
    if not decoded.isascii():
        raise AdapterError("Invalid Riff capability identifier.")
    allowed = set()
    if decoded == "/api/loras/hub":
        allowed = {"q", "sort", "genre", "page", "limit", "license", "stage", "compatibility"}
    elif decoded in ("/api/loras/hub/detail", "/api/loras/hub/media"):
        allowed = {"repo", "revision"} | ({"file"} if decoded.endswith("/media") else set())
    elif decoded == "/api/loras/import":
        allowed = {"name"}
    elif decoded == "/api/review/models":
        allowed = {"refresh"}
    elif re.fullmatch(rf"/api/tracks/{ID}/(audio|recipe)", decoded):
        allowed = {"download"}
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)) or set(keys) - allowed:
        raise AdapterError("Unsupported or repeated Riff query parameter.")
    if any(len(v) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in v) for _, v in pairs):
        raise AdapterError("Invalid Riff query value.")
    return decoded, pairs


def route(path, method, *, ui=False, media=False, upload=False):
    decoded, pairs = canonical(path)
    if not isinstance(method, str) or method not in ("GET", "POST", "PATCH", "DELETE"):
        raise AdapterError("Unsupported Riff request method.")
    if media:
        patterns = MEDIA if method == "GET" else []
    elif upload:
        patterns = UPLOADS if method == "POST" else []
    elif method == "GET":
        patterns = READS
    else:
        patterns = (UI_EDITS if ui else EDITS).get(method, [])
    if not any(re.fullmatch(p, decoded) for p in patterns):
        raise AdapterError("This Riff action is not available through this tool.")
    if upload and decoded == "/api/loras/import":
        name = dict(pairs).get("name", "")
        if not name.endswith(".safetensors") or "/" in name or "\\" in name or ".." in name:
            raise AdapterError("Choose a named .safetensors LoRA file.")
    return decoded + ("?" + urlencode(pairs) if pairs else "")


def upload_headers(path, content_type, values):
    values = values or {}
    if not isinstance(values, dict) or len(values) > 2:
        raise AdapterError("Invalid upload headers.")
    lowered = {str(k).lower(): v for k, v in values.items()}
    if len(lowered) != len(values) or set(lowered) - {"x-riff-frame", "x-riff-lora-metadata"}:
        raise AdapterError("Only Riff frame and LoRA metadata headers are allowed.")
    if any(not isinstance(v, str) or len(v) > 32768 or "\r" in v or "\n" in v or "\x00" in v for v in lowered.values()):
        raise AdapterError("Invalid upload header value.")
    is_lora = urlsplit(path).path == "/api/loras/import"
    if is_lora:
        if content_type != "application/octet-stream" or "x-riff-frame" in lowered:
            raise AdapterError("LoRA imports require application/octet-stream.")
    elif (content_type not in ("image/png", "video/h264") or "x-riff-lora-metadata" in lowered
          or not re.fullmatch(r"\d{1,8}", lowered.get("x-riff-frame", ""))):
        raise AdapterError("Video uploads require a frame index and PNG or H.264 content.")
    return lowered
