"""Private loopback transport and bounded, disk-backed binary uploads."""
from __future__ import annotations

import base64
import binascii
import http.client
import json
from pathlib import Path
import re
import threading
import time
from urllib import request, error
from urllib.parse import unquote, urlsplit
import uuid

from routes import AdapterError, route, upload_headers

MAX_JSON = 4 * 1024 * 1024
MAX_CHUNK = 1024 * 1024
MAX_UPLOAD = 2 * 1024 ** 3
MAX_FRAME = 40 * 1024 ** 2


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AdapterError("Backend redirects are not permitted.")


def decode_json(raw):
    if len(raw) > MAX_JSON:
        raise AdapterError("Riff JSON response exceeds the transfer limit.")
    try:
        value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError) as exc:
        raise AdapterError("Riff returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise AdapterError("Riff returned a non-object response.")
    return value


class LoopbackBackend:
    def __init__(self, port):
        if type(port) is not int or not 0 < port < 65536:
            raise AdapterError("Invalid private backend port.")
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def json_request(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        req = request.Request(self.base + path, data=data, method=method,
                              headers={"X-Riff-Request": "1", "Content-Type": "application/json"})
        try:
            response = self.opener.open(req, timeout=300 if method != "GET" else 60)
        except error.HTTPError as exc:
            response = exc
        except (error.URLError, OSError) as exc:
            raise AdapterError("The plugin-managed Riff backend is unavailable.") from exc
        with response:
            raw, status = response.read(MAX_JSON + 1), response.code
        return status, decode_json(raw)

    def media_chunk(self, path, offset, length):
        req = request.Request(self.base + path, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
        try:
            response = self.opener.open(req, timeout=60)
        except error.HTTPError as exc:
            with exc:
                raw = exc.read(8192)
            try:
                reason = json.loads(raw).get("error", "")
            except (ValueError, AttributeError):
                reason = ""
            raise AdapterError(str(reason) or "The requested Riff media is unavailable.") from exc
        except (error.URLError, OSError) as exc:
            raise AdapterError("The requested Riff media is unavailable.") from exc
        with response:
            mime = response.headers.get("Content-Type", "application/octet-stream").split(";")[0]
            disposition = response.headers.get("Content-Disposition", "")
            name_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
            name = unquote(name_match[1]) if name_match else Path(urlsplit(path).path).name
            name = Path(name.replace("\\", "/")).name
            if not name or any(ord(c) < 32 for c in name):
                name = "riff-export"
            if response.code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match:
                    raise AdapterError("Riff did not return a bounded media range.")
                start, end, total = map(int, match.groups())
                if start != offset or end < start or end - start + 1 > length or end >= total:
                    raise AdapterError("Invalid backend media range.")
                raw = response.read(length + 1)
                if len(raw) != end - start + 1:
                    raise AdapterError("Interrupted or oversized media range.")
            elif response.code == 200 and offset == 0:
                # The small setup log is intentionally served without ranges.
                total = int(response.headers.get("Content-Length", "-1"))
                if not 0 <= total <= length:
                    raise AdapterError("This Riff resource does not support a bounded transfer.")
                raw = response.read(length + 1)
                if len(raw) != total:
                    raise AdapterError("Interrupted or oversized media response.")
            else:
                raise AdapterError("Riff did not honor the requested media range.")
        return raw, total, mime, name

    def audio_chunk(self, track_id, offset, length):
        raw, total, _, _ = self.media_chunk(f"/api/tracks/{track_id}/audio", offset, length)
        return raw, total

    def upload_file(self, path, file, content_type, headers):
        # The only destination is the process-owned Riff loopback server.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=300)
        try:
            connection.putrequest("POST", path)
            connection.putheader("X-Riff-Request", "1")
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(file.stat().st_size))
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            with file.open("rb") as source:
                while block := source.read(MAX_CHUNK):
                    connection.send(block)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise AdapterError("Backend redirects are not permitted.")
            return response.status, decode_json(response.read(MAX_JSON + 1))
        except (OSError, http.client.HTTPException) as exc:
            raise AdapterError("Riff could not complete the file transfer; it was not retried.") from exc
        finally:
            connection.close()


class UploadStore:
    """Ordered uploads scoped to one plugin process, with explicit cancellation.

    Transfers are never executed before the final byte. No caller path becomes
    a local path. The process workspace lock protects restart cleanup.
    """
    def __init__(self, directory, backend):
        self.directory, self.backend = Path(directory), backend
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.lock = threading.RLock()
        self.transfers = {}
        for file in self.directory.glob("*.part"):
            if file.is_file() and not file.is_symlink():
                file.unlink()

    def _remove(self, upload_id):
        item = self.transfers.pop(upload_id, None)
        if item:
            item["file"].unlink(missing_ok=True)

    def cancel(self, upload_id):
        if not isinstance(upload_id, str) or not re.fullmatch(r"[a-f0-9]{32}", upload_id):
            raise AdapterError("Invalid upload id.")
        with self.lock:
            item = self.transfers.get(upload_id)
            if item and item.get("committing"):
                raise AdapterError("The complete file is being imported. Wait for its result.")
            self._remove(upload_id)
        return {"upload_id": upload_id, "cancelled": True}

    def chunk(self, args):
        path = route(args["path"], "POST", ui=True, upload=True)
        total, offset, final = args["total"], args["offset"], args["final"]
        limit = MAX_UPLOAD if urlsplit(path).path == "/api/loras/import" else MAX_FRAME
        if type(total) is not int or not 0 < total <= limit or type(offset) is not int or offset < 0 or type(final) is not bool:
            raise AdapterError("Invalid upload size, offset or completion flag.")
        content_type = args["content_type"]
        headers = upload_headers(path, content_type, args.get("headers"))
        encoded = args["base64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_CHUNK + 2) // 3):
            raise AdapterError("Upload chunks must contain at most 1 MiB.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AdapterError("Invalid base64 upload chunk.") from exc
        if not 0 < len(data) <= MAX_CHUNK or offset + len(data) > total or final != (offset + len(data) == total):
            raise AdapterError("Invalid upload chunk length or completion flag.")
        upload_id = args.get("upload_id")
        with self.lock:
            now = time.monotonic()
            for old_id, item in list(self.transfers.items()):
                if not item.get("committing") and now - item["touched"] > 3600:
                    self._remove(old_id)
            if upload_id is None:
                if offset != 0 or len(self.transfers) >= 4:
                    raise AdapterError("Start at offset zero and finish or cancel existing uploads first.")
                upload_id = uuid.uuid4().hex
                file = self.directory / (upload_id + ".part")
                with file.open("xb"):
                    pass
                file.chmod(0o600)
                self.transfers[upload_id] = {"file": file, "path": path, "total": total, "received": 0,
                                             "content_type": content_type, "headers": headers, "touched": now}
            if not isinstance(upload_id, str) or upload_id not in self.transfers:
                raise AdapterError("Unknown or expired upload. Start the transfer again.")
            item = self.transfers[upload_id]
            if (item.get("committing") or offset != item["received"] or path != item["path"] or total != item["total"]
                    or content_type != item["content_type"] or headers != item["headers"]):
                raise AdapterError("Upload sequence or metadata changed; no bytes were accepted.")
            with item["file"].open("ab") as target:
                target.write(data)
            item["received"], item["touched"] = offset + len(data), now
            if final:
                item["committing"] = True
        status, body = 200, {}
        if final:
            try:
                status, body = self.backend.upload_file(path, item["file"], content_type, headers)
            finally:
                with self.lock:
                    self._remove(upload_id)
        return {"upload_id": upload_id, "offset": offset, "bytes": len(data), "received": offset + len(data),
                "total": total, "complete": final, "status": status, "body": body}

    def close(self):
        with self.lock:
            for upload_id in list(self.transfers):
                self._remove(upload_id)
