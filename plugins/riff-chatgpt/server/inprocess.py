"""Use the pinned studio's handlers in process, without opening a listener.

Adapter route/schema checks and the studio's own origin/mutation validation
remain in force. Only request transport changes; native jobs stay authoritative.
"""
import contextlib
from email.message import Message
import html
import http.client
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.error import HTTPError

from transport import LoopbackBackend, MAX_JSON, decode_json


class InProcessBackend(LoopbackBackend):
    def __init__(self, studio, store, generator, reviews, maintenance):
        self.studio = studio
        self.store, self.generator = store, generator
        self.reviews, self.maintenance = reviews, maintenance
        # This is an origin-validation token, not an opened network port.
        self.server_port = self.port = 0
        self.network_access = None
        self.restart_requested = False
        self.studio_identity = studio.studio_identity(studio.WEB, (studio.ROOT/'VERSION').read_text().strip())
        self.studio_index = (studio.WEB/'index.html').read_text().replace(
            '__RIFF_STUDIO_BUILD__', html.escape(self.studio_identity['build'], quote=True)).encode()
        self.video_exports = studio.VideoExports(store)
        maintenance.video_exports = self.video_exports
        # Reuse the existing bounded media-response parser through this opener.
        self.base = 'http://127.0.0.1:0'
        self.opener = self

    @contextlib.contextmanager
    def response(self, path, method='GET', body=None, content_type='application/json', headers=None):
        handler = self.studio.Handler.__new__(self.studio.Handler)
        handler.server = self
        handler.command, handler.path = method, path
        handler.request_version = 'HTTP/1.1'
        handler.requestline = method+' '+path+' HTTP/1.1'
        handler.client_address = ('127.0.0.1', 0)
        handler.close_connection = True
        handler.headers = Message()
        for name, value in {'Host':'127.0.0.1:0', 'X-Riff-Request':'1',
                            'Content-Type':content_type, **(headers or {})}.items():
            handler.headers[name] = str(value)
        with contextlib.ExitStack() as stack:
            if isinstance(body, Path):
                handler.rfile = stack.enter_context(body.open('rb'))
                size = body.stat().st_size
            else:
                raw = b'' if body is None else json.dumps(body,allow_nan=False).encode()
                handler.rfile = io.BytesIO(raw)
                size = len(raw)
            handler.headers['Content-Length'] = str(size)
            output = stack.enter_context(tempfile.TemporaryFile())
            handler.wfile = output
            getattr(handler, 'do_'+method)()
            output.seek(0)
            class BufferSocket:
                def makefile(self, *_):
                    return output
            response = http.client.HTTPResponse(BufferSocket())
            response.begin()
            # urllib responses expose code; HTTPResponse exposes status.
            response.code = response.status
            try:
                yield response
            finally:
                response.close()

    def json_request(self, path, method='GET', body=None):
        with self.response(path, method, body) as response:
            return response.status, decode_json(response.read(MAX_JSON+1))

    def open(self, request, timeout=None):
        # LoopbackBackend.media_chunk consumes this as a context manager.
        parsed = urlsplit(request.full_url)
        if parsed.netloc != '127.0.0.1:0':
            raise ValueError('In-process requests cannot address external services.')
        path = parsed.path+('?' + parsed.query if parsed.query else '')
        manager = self.response(path, request.get_method(), headers=dict(request.header_items()))
        response = manager.__enter__()
        class ManagedResponse:
            """urllib.open returns a response, not a context-manager factory."""
            closed = False
            def __getattr__(self, name):
                return getattr(response, name)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                if not self.closed:
                    self.closed = True
                    return manager.__exit__(*exc)
            def close(self):
                self.__exit__(None, None, None)
        wrapped = ManagedResponse()
        if response.code >= 400:
            raise HTTPError(request.full_url,response.code,response.reason,response.headers,wrapped)
        return wrapped

    def upload_file(self, path, file, content_type, headers):
        with self.response(path, 'POST', Path(file), content_type, headers) as response:
            return response.status, decode_json(response.read(MAX_JSON+1))

    def server_close(self):
        self.video_exports.close()
        if hasattr(self.store.loras, 'close'):
            self.store.loras.close()
