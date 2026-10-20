/* Riff's original studio over MCP Apps. All server traffic stays in tools/call. */
(function (root) {
  "use strict";
  const CHUNK = 1024 * 1024;
  const MEDIA_LIMIT = 1024 * 1024 * 1024;
  const TRACK = /^[a-f0-9]{32}$/;
  const QUERY_KEYS = {
    "/api/loras/hub": ["q", "sort", "genre", "license", "stage", "compatibility", "page", "limit"],
    "/api/loras/hub/detail": ["repo", "revision"],
    "/api/loras/hub/media": ["repo", "revision", "file"],
    "/api/loras/import": ["name"],
    "/api/review/models": ["refresh"],
  };

  class RiffError extends Error {
    constructor(message, status = 400, body) { super(message); this.status = status; this.body = body; }
  }

  class RiffBridge {
    constructor(win, { timeoutMs = 120000, initializeTimeoutMs = 8000 } = {}) {
      this.win = win;
      this.timeoutMs = timeoutMs;
      this.nextId = 1;
      this.pending = new Map();
      this.inflightReads = new Map();
      this.media = new Map();
      this.objectUrls = new Map();
      this.listeners = new Map();
      this.workers = new Set();
      this.uploads = new Set();
      this.assets = {};
      this.origin = null;
      this.closed = false;
      this.compatibility = false;
      this.hostContext = {};
      this.hostCapabilities = {};
      this.onMessage = event => this.receive(event);
      win.addEventListener("message", this.onMessage);
      this.ready = this.request("ui/initialize", {
        protocolVersion: "2026-01-26",
        appInfo: { name: "Riff Studio", version: "1.0.0" },
        appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
      }, initializeTimeoutMs).then(result => {
        if (result?.protocolVersion !== "2026-01-26") throw new Error("Unsupported MCP Apps protocol version.");
        this.hostContext = result.hostContext || {};
        this.hostCapabilities = result.hostCapabilities || {};
        this.notify("ui/notifications/initialized", {});
        this.emit("host-context", this.hostContext);
        return result;
      }).catch(error => {
        // Older ChatGPT hosts expose this compatibility bridge. Never pick a server URL.
        if (typeof win.openai?.callTool !== "function") throw error;
        this.compatibility = true;
        this.hostContext = win.openai || {};
        this.lastToolResult = win.openai.toolOutput ? { structuredContent: win.openai.toolOutput } : null;
        return { compatibility: true };
      });
      this.ready.catch(() => {});
    }

    on(event, fn) {
      if (!this.listeners.has(event)) this.listeners.set(event, new Set());
      this.listeners.get(event).add(fn);
      return () => this.listeners.get(event)?.delete(fn);
    }

    emit(event, value) {
      for (const fn of this.listeners.get(event) || []) {
        try { Promise.resolve(fn(value)).catch(error => this.emitError(error)); }
        catch (error) { this.emitError(error); }
      }
    }

    emitError(error) {
      for (const fn of this.listeners.get("error") || []) {
        try { fn(error); } catch { /* Do not recurse through a broken status handler. */ }
      }
    }

    receive(event) {
      if (event.source !== this.win.parent || (this.origin !== null && event.origin !== this.origin)) return;
      const message = event.data;
      if (!message || typeof message !== "object" || message.jsonrpc !== "2.0") return;
      const pending = this.pending.get(message.id);
      if (pending && !message.method) {
        if (pending.method === "ui/initialize") this.origin = event.origin;
        pending.cleanup();
        if (message.error) pending.reject(new RiffError(String(message.error.message || "Host request failed."), 502));
        else pending.resolve(message.result);
        return;
      }
      if (message.method === "ui/notifications/host-context-changed") {
        this.hostContext = { ...this.hostContext, ...message.params };
        this.emit("host-context", this.hostContext);
      } else if (message.method === "ui/notifications/tool-input") {
        this.lastToolInput = message.params?.arguments || {};
        this.emit("tool-input", this.lastToolInput);
      } else if (message.method === "ui/notifications/tool-result") {
        this.lastToolResult = message.params;
        this.emit("tool-result", message.params);
      } else if (message.method === "ui/notifications/tool-cancelled") {
        this.emit("error", new Error(message.params?.reason || "The host cancelled this action."));
      } else if (message.method === "ui/resource-teardown" && Object.hasOwn(message, "id")) {
        // Teardown applies to this view. It never shuts down the shared Riff engine.
        Promise.allSettled([...this.listeners.get("teardown") || []].map(fn => Promise.resolve().then(fn)))
          .finally(() => {
            this.post({ jsonrpc: "2.0", id: message.id, result: {} });
            this.close();
          });
      }
    }

    post(message) {
      this.win.parent.postMessage(message, this.origin && this.origin !== "null" ? this.origin : "*");
    }

    request(method, params, timeoutMs = this.timeoutMs, signal) {
      if (this.closed) return Promise.reject(new Error("Riff host bridge is closed."));
      if (signal?.aborted) return Promise.reject(this.abortError());
      const id = this.nextId++;
      return new Promise((resolve, reject) => {
        const cleanup = () => { clearTimeout(timer); this.pending.delete(id); signal?.removeEventListener("abort", abort); };
        const abort = () => { cleanup(); reject(this.abortError()); };
        const timer = setTimeout(() => {
          cleanup();
          reject(new RiffError(`ChatGPT did not complete ${method}. No mutation will be retried automatically.`, 504));
        }, timeoutMs);
        this.pending.set(id, { method, resolve, reject, cleanup });
        signal?.addEventListener("abort", abort, { once: true });
        try { this.post({ jsonrpc: "2.0", id, method, params }); }
        catch (error) { cleanup(); reject(error); }
      });
    }

    abortError() { return new (this.win.DOMException || DOMException)("Request cancelled.", "AbortError"); }
    notify(method, params) { if (!this.closed) this.post({ jsonrpc: "2.0", method, params }); }

    async callTool(name, args, { signal, allowError = false, timeoutMs = this.timeoutMs } = {}) {
      await this.ready;
      if (signal?.aborted) throw this.abortError();
      const result = this.compatibility
        ? await this.win.openai.callTool(name, args)
        : await this.request("tools/call", { name, arguments: args }, timeoutMs, signal);
      if (!result || typeof result !== "object") throw new Error("Invalid Riff tool response.");
      if (result.isError && !allowError) throw this.toolError(result);
      return result;
    }

    toolError(result) {
      const data = result.structuredContent;
      const message = result.content?.filter(c => c.type === "text").map(c => c.text).join("\n");
      return new RiffError(message || data?.body?.error || "Riff operation failed.", data?.status || 400, data?.body);
    }

    validatePath(path) {
      if (typeof path !== "string" || path.length > 8192 || !path.startsWith("/api/") || /[#\\\r\n\0]/.test(path)) {
        throw new RiffError("Only explicit Riff API routes are accepted.");
      }
      const [pathname, query = ""] = path.split("?");
      if (pathname.includes("..") || pathname.includes("%") || path.split("?").length > 2) throw new RiffError("Invalid Riff API route.");
      if (query) {
        const allowed = QUERY_KEYS[pathname] || (/^\/api\/tracks\/[a-f0-9]{32}\/audio$/.test(pathname) ? ["download"] : []);
        const params = new URLSearchParams(query), seen = new Set();
        for (const [key, value] of params) {
          if (!allowed.includes(key) || seen.has(key) || /[\r\n\0]/.test(value)) throw new RiffError("Invalid Riff query parameter.");
          seen.add(key);
        }
      }
      return path;
    }

    async jsonResponse(path, method = "GET", body, signal) {
      this.validatePath(path);
      method = method.toUpperCase();
      if (!["GET", "POST", "PATCH", "DELETE"].includes(method)) throw new RiffError("Unsupported Riff request method.");
      const run = async () => {
        const result = await this.callTool("riff_ui_request", { path, method, ...(body === undefined ? {} : { body }) }, { signal, allowError: true });
        const data = result.structuredContent;
        if (!data || !Number.isInteger(data.status) || !Object.hasOwn(data, "body")) {
          if (result.isError) throw this.toolError(result);
          throw new Error("Invalid Riff JSON response.");
        }
        if (data.status < 400) this.emit("api", { path, method, body: data.body });
        return data;
      };
      if (method !== "GET" || signal) return run();
      if (!this.inflightReads.has(path)) this.inflightReads.set(path, run().finally(() => this.inflightReads.delete(path)));
      return this.inflightReads.get(path);
    }

    async api(path, method = "GET", body) {
      const result = await this.jsonResponse(path, method, body);
      if (result.status >= 400) throw new RiffError(result.body?.error || "Riff operation failed.", result.status, result.body);
      return result.body;
    }

    async fetch(path, options = {}) {
      const ResponseType = this.win.Response || Response;
      try {
        if (options.signal?.aborted) throw this.abortError();
        const method = (options.method || "GET").toUpperCase();
        const binary = options.body !== undefined && typeof options.body !== "string";
        const result = binary
          ? await this.upload(path, options)
          : await this.jsonResponse(path, method, options.body === undefined ? undefined : JSON.parse(options.body), options.signal);
        return new ResponseType([204, 304].includes(result.status) ? null : JSON.stringify(result.body), {
          status: result.status, headers: { "Content-Type": "application/json" },
        });
      } catch (error) {
        if (error.name === "AbortError") throw error;
        return new ResponseType(JSON.stringify(error.body || { error: error.message }), {
          status: error.status || 502, headers: { "Content-Type": "application/json" },
        });
      }
    }

    encode(bytes) {
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
      return (this.win.btoa || btoa)(binary);
    }

    async upload(path, options) {
      this.validatePath(path);
      if ((options.method || "GET").toUpperCase() !== "POST") throw new RiffError("Binary uploads require POST.");
      const HeadersType = this.win.Headers || Headers;
      const sourceHeaders = new HeadersType(options.headers || {}), headers = {};
      for (const name of ["x-riff-frame", "x-riff-lora-metadata"]) {
        if (sourceHeaders.has(name)) headers[name] = sourceHeaders.get(name);
      }
      const contentType = sourceHeaders.get("content-type") || "application/octet-stream";
      const pathname = path.split("?")[0];
      const frame = /^\/api\/video-exports\/[a-f0-9]{32}\/frames$/.test(pathname);
      if (pathname !== "/api/loras/import" && !frame) throw new RiffError("Unsupported Riff binary upload route.");
      if (frame ? !["image/png", "video/h264"].includes(contentType) || !/^\d+$/.test(headers["x-riff-frame"] || "")
        : contentType !== "application/octet-stream") throw new RiffError("Invalid binary upload headers.");
      const body = options.body;
      const isBlob = body && typeof body.slice === "function" && Number.isSafeInteger(body.size) && typeof body.arrayBuffer === "function";
      const bytes = isBlob ? null : ArrayBuffer.isView(body) ? new Uint8Array(body.buffer, body.byteOffset, body.byteLength)
        : body instanceof (this.win.ArrayBuffer || ArrayBuffer) ? new Uint8Array(body) : null;
      if (!isBlob && !bytes) throw new RiffError("Choose a file or encoded video frame to upload.");
      const total = isBlob ? body.size : bytes.byteLength;
      if (total < 1 || total > 2 * 1024 ** 3) throw new RiffError("The upload is empty or exceeds 2 GiB.");
      if (frame && total > 40 * CHUNK) throw new RiffError("This video frame exceeds 40 MiB.");
      let uploadId, offset = 0, complete = false;
      try {
        while (offset < total) {
          if (options.signal?.aborted) throw this.abortError();
          const end = Math.min(total, offset + CHUNK);
          const chunk = isBlob ? new Uint8Array(await body.slice(offset, end).arrayBuffer()) : bytes.subarray(offset, end);
          const result = await this.callTool("riff_upload_chunk", {
            path, ...(uploadId ? { upload_id: uploadId } : {}), offset, total,
            base64: this.encode(chunk), final: end === total, content_type: contentType, headers,
          }, { signal: options.signal, allowError: true });
          if (result.isError) throw this.toolError(result);
          const info = result.structuredContent;
          if (!info || !TRACK.test(info.upload_id) || (uploadId && info.upload_id !== uploadId) || info.offset !== offset ||
              info.bytes !== end - offset || info.received !== end || info.total !== total || info.complete !== (end === total)) {
            throw new Error("The studio returned an inconsistent upload receipt.");
          }
          uploadId = info.upload_id;
          this.uploads.add(uploadId);
          offset = end;
          this.emit("upload-progress", { path, received: offset, total });
          if (info.complete) { complete = true; return { status: info.status, body: info.body }; }
        }
      } finally {
        if (uploadId) {
          this.uploads.delete(uploadId);
          if (!complete && !this.closed) {
            // Only staging is cancelled; an upstream mutation is never retried.
            this.callTool("riff_upload_cancel", { upload_id: uploadId }, { timeoutMs: 10000 }).catch(() => {});
          }
        }
      }
    }

    async mediaBlob(path, { signal } = {}) {
      this.validatePath(path);
      const chunks = [];
      let offset = 0, total = null, mimeType, name;
      do {
        const result = await this.callTool("riff_media_chunk", { path, offset, length: CHUNK }, { signal });
        const info = result.structuredContent, media = result._meta?.["riff/media"];
        if (!info || info.offset !== offset || !Number.isSafeInteger(info.total) || info.total < 1 || info.total > MEDIA_LIMIT) {
          throw new Error("Invalid or oversized Riff media.");
        }
        if (total !== null && (info.total !== total || media?.mimeType !== mimeType || media?.name !== name)) throw new Error("Media changed during transfer.");
        if (typeof media?.mimeType !== "string" || typeof media.base64 !== "string" || media.base64.length > Math.ceil(CHUNK / 3) * 4 ||
            typeof media.name !== "string") throw new Error("Invalid Riff media payload.");
        total = info.total; mimeType = media.mimeType; name = media.name;
        const binary = (this.win.atob || atob)(media.base64);
        const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
        if (bytes.length < 1 || bytes.length !== info.bytes || bytes.length > CHUNK || offset + bytes.length > total) throw new Error("Invalid media chunk length.");
        if (offset === 0 && /^\/api\/tracks\/[a-f0-9]{32}\/audio(?:\?|$)/.test(path) &&
            (mimeType !== "audio/wav" || binary.slice(0, 4) !== "RIFF" || binary.slice(8, 12) !== "WAVE")) throw new Error("Riff did not return a WAV recording.");
        offset += bytes.length;
        if (info.eof !== (offset === total)) throw new Error("Inconsistent media completion marker.");
        chunks.push(bytes);
        this.emit("media-progress", { path, received: offset, total });
      } while (offset < total);
      const blob = new (this.win.Blob || Blob)(chunks, { type: mimeType });
      return { blob, name };
    }

    async audioBlob(id) {
      if (!TRACK.test(id)) throw new Error("Invalid Riff track id.");
      return (await this.mediaBlob(`/api/tracks/${id}/audio`)).blob;
    }

    async mediaUrl(path) {
      if (!this.media.has(path)) {
        const promise = this.mediaBlob(path).then(({ blob }) => {
          const url = this.win.URL.createObjectURL(blob);
          if (this.closed) { this.win.URL.revokeObjectURL(url); throw new Error("Riff host bridge is closed."); }
          return { url, blob };
        }).catch(error => { this.media.delete(path); throw error; });
        this.media.set(path, promise);
        // Keep both comparison takes and a few community previews. Blobs are reclaimed on close.
        while (this.media.size > 6) {
          const oldest = this.media.keys().next().value, entry = this.media.get(oldest);
          this.media.delete(oldest);
          entry.then(({ url }) => this.win.URL.revokeObjectURL(url)).catch(() => {});
        }
      }
      return (await this.media.get(path)).url;
    }

    audioUrl(id) {
      if (!TRACK.test(id)) return Promise.reject(new Error("Invalid Riff track id."));
      return this.mediaUrl(`/api/tracks/${id}/audio`);
    }

    async dataUrl(blob) {
      return `data:${blob.type || "application/octet-stream"};base64,${this.encode(new Uint8Array(await blob.arrayBuffer()))}`;
    }

    assignMedia(element, url, path, autoplay = false) {
      element.dataset.riffActiveMedia = path;
      // Some hosts deny blob: through CSP. A data: fallback retains offline playback.
      const fallback = async () => {
        element.removeEventListener("error", fallback);
        try {
          const cached = await this.media.get(path);
          if (!cached || !element.isConnected || element.dataset.riffActiveMedia !== path) return;
          element.src = await this.dataUrl(cached.blob);
          element.load?.();
          if (autoplay && element.play) await element.play();
        } catch (error) { this.emitError(error); }
      };
      element.addEventListener("error", fallback, { once: true });
      element.src = url;
    }

    async useMedia(element, path, autoplay = false) {
      const url = await this.mediaUrl(path);
      if (this.closed || !element.isConnected) return;
      this.assignMedia(element, url, path, autoplay);
      element.load?.();
      if (autoplay && element.play) {
        try { await element.play(); } catch (error) { if (!element.error) throw error; }
      }
    }

    createWorker(name) {
      const encoded = this.assets[name];
      if (typeof encoded !== "string") throw new Error("The Riff worker is not bundled.");
      const binary = (this.win.atob || atob)(encoded);
      const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
      const url = this.win.URL.createObjectURL(new (this.win.Blob || Blob)([bytes], { type: "text/javascript" }));
      try {
        const worker = new this.win.Worker(url), terminate = worker.terminate.bind(worker);
        worker.terminate = () => { this.win.URL.revokeObjectURL(url); this.workers.delete(worker); terminate(); };
        this.workers.add(worker);
        return worker;
      } catch (error) { this.win.URL.revokeObjectURL(url); throw error; }
    }

    createObjectURL(blob) {
      const url = this.win.URL.createObjectURL(blob);
      this.objectUrls.set(url, blob);
      return url;
    }

    revokeObjectURL(url) {
      this.win.URL.revokeObjectURL(url);
      this.objectUrls.delete(url);
    }

    async downloadLink(anchor) {
      const path = anchor.getAttribute("href") || "";
      let blob, name = anchor.download || "";
      if (path.startsWith("/api/")) {
        if (/^\/api\/tracks\/[a-f0-9]{32}\/recipe$/.test(path)) {
          blob = new (this.win.Blob || Blob)([JSON.stringify(await this.api(path), null, 2) + "\n"], { type: "application/json" });
          name ||= `riff-${path.split("/")[3]}.json`;
        } else {
          const media = await this.mediaBlob(path); blob = media.blob; name ||= media.name;
        }
      } else if (path.startsWith("blob:")) {
        // No fetch(blob:) is needed: connect-src may prohibit it in the host.
        blob = this.objectUrls.get(path);
        if (!blob) throw new Error("This local export has expired. Export it again.");
      } else if (path.startsWith("data:")) {
        const match = /^data:([^;,]*)(;base64)?,([\s\S]*)$/.exec(path);
        if (!match) throw new Error("Invalid local export.");
        const data = match[2] ? Uint8Array.from((this.win.atob || atob)(match[3]), c => c.charCodeAt(0)) : decodeURIComponent(match[3]);
        blob = new (this.win.Blob || Blob)([data], { type: match[1] || "application/octet-stream" });
      } else { throw new Error("This download is not a Riff export."); }
      return this.downloadBlob(blob, name || "riff-export");
    }

    async downloadBlob(blob, name) {
      await this.ready;
      name = String(name).replace(/[\\/\x00-\x1f\x7f]/g, "_").slice(0, 240) || "riff-export";
      if (blob.size > MEDIA_LIMIT) throw new Error("This file exceeds the host download size limit.");
      if (!this.hostCapabilities.downloadFile) {
        // Chat's documented file extension is available alongside MCP Apps even
        // when the host does not advertise the shared download-file capability.
        const files = this.win.openai;
        if (typeof files?.uploadFile !== "function" || typeof files?.getFileDownloadUrl !== "function" ||
            typeof files?.openExternal !== "function" || typeof this.win.File !== "function") {
          throw new Error("This ChatGPT host does not expose app file downloads.");
        }
        const { fileId } = await files.uploadFile(new this.win.File([blob], name, {
          type: blob.type || "application/octet-stream",
        }), { library: true });
        if (typeof fileId !== "string" || !fileId) throw new Error("ChatGPT did not return the exported file reference.");
        const { downloadUrl } = await files.getFileDownloadUrl({ fileId });
        let url;
        try { url = new URL(downloadUrl); } catch { /* Reject malformed host responses. */ }
        if (url?.protocol !== "https:" || url.username || url.password) throw new Error("ChatGPT did not return a valid file download URL.");
        await files.openExternal({ href: url.href, redirectUrl: false });
        this.emit("download", { name, bytes: blob.size });
        return { fileId };
      }
      const data = this.encode(new Uint8Array(await blob.arrayBuffer()));
      const result = await this.request("ui/download-file", { contents: [{ type: "resource", resource: {
        uri: "file:///" + encodeURIComponent(name), mimeType: blob.type || "application/octet-stream", blob: data,
      } }] });
      if (result?.isError) throw new Error(result.content?.find(item => item.type === "text")?.text || "The host could not save this export.");
      this.emit("download", { name, bytes: blob.size });
      return result;
    }

    async shareContext(context, { explicit = true } = {}) {
      await this.ready;
      const text = JSON.stringify(context);
      if (text.length > 65536) throw new Error("Select a smaller draft to share with ChatGPT.");
      if (this.compatibility) {
        if (!this.win.openai?.setWidgetState) throw new Error("This host cannot accept Riff context.");
        this.win.openai.setWidgetState({ ...(this.win.openai.widgetState || {}), modelContent: text });
        return;
      }
      if (!this.hostCapabilities.updateModelContext && !this.hostCapabilities.experimental?.["openai/modelContext"]) {
        throw new Error("This ChatGPT host does not expose app context updates.");
      }
      return this.request("ui/update-model-context", { structuredContent: context, ...(explicit ? { content: [{ type: "text", text }] } : {}) });
    }

    async message(text) {
      await this.ready;
      if (typeof text !== "string" || text.length > 65536) throw new Error("The message is too large.");
      const result = await this.request("ui/message", { role: "user", content: [{ type: "text", text }] });
      if (result?.isError) throw new Error("ChatGPT could not receive this writing request.");
      return result;
    }

    async fullscreen() {
      await this.ready;
      if (this.compatibility) {
        if (!this.win.openai?.requestDisplayMode) throw new Error("Fullscreen is not exposed by this host.");
        return this.win.openai.requestDisplayMode({ mode: "fullscreen" });
      }
      return this.request("ui/request-display-mode", { mode: "fullscreen" });
    }

    async openLink(url) {
      const address = new URL(url);
      if (!["https:", "http:"].includes(address.protocol)) throw new Error("Only web links can open outside the studio.");
      await this.ready;
      return this.request("ui/open-link", { url: address.href });
    }

    preferredTrack() {
      const body = this.lastToolResult?.structuredContent?.body || this.lastToolResult?.structuredContent || {};
      const candidates = [body.track_id, body.selectedTrackId, body.track?.id, this.lastToolInput?.track_id];
      const link = this.hostContext?.["openai/deepLink"]?.url;
      if (typeof link === "string" && link.startsWith("/") && !link.startsWith("//") && !/[#\\\r\n\0]/.test(link)) {
        try {
          const url = new URL(link, "https://riff.invalid");
          candidates.push(url.searchParams.get("recording"), /^\/tracks\/([a-f0-9]{32})$/.exec(url.pathname)?.[1]);
        } catch { /* An invalid optional deep link does not interrupt the editor. */ }
      }
      return candidates.find(value => typeof value === "string" && TRACK.test(value)) || null;
    }

    replaceHistory(url) {
      this.navigation = String(url);
      try { this.win.history.replaceState(null, "", url); }
      catch { /* Opaque resource frames cannot change their URL; navigation stays in this view. */ }
      this.emit("navigation", this.navigation);
    }

    recordingReference(id) {
      if (!TRACK.test(id)) throw new Error("Invalid Riff track id.");
      return `Riff recording ${id}\nStudio path: /?recording=${id}`;
    }

    close() {
      if (this.closed) return;
      for (const uploadId of this.uploads) {
        // Post cleanup before closing; callTool would defer it past close() at await ready.
        const cleanup = this.compatibility ? this.win.openai.callTool("riff_upload_cancel", { upload_id: uploadId })
          : this.request("tools/call", { name: "riff_upload_cancel", arguments: { upload_id: uploadId } }, 5000);
        Promise.resolve(cleanup).catch(() => {});
      }
      this.closed = true;
      this.win.removeEventListener("message", this.onMessage);
      for (const pending of [...this.pending.values()]) { pending.cleanup(); pending.reject(new Error("Riff host bridge closed.")); }
      for (const worker of [...this.workers]) worker.terminate();
      for (const entry of this.media.values()) entry.then(({ url }) => this.win.URL.revokeObjectURL(url)).catch(() => {});
      for (const url of this.objectUrls.keys()) this.win.URL.revokeObjectURL(url);
      this.objectUrls.clear();
      this.media.clear(); this.listeners.clear();
    }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { RiffBridge, RiffError };
  else root.RiffBridge = RiffBridge;
})(typeof window !== "undefined" ? window : globalThis);
