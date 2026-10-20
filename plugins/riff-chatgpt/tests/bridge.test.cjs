const { test } = require('node:test');
const assert = require('node:assert/strict');
const { RiffBridge } = require('../web/host.js');

function mockWindow(handler = () => ({ structuredContent: { status: 200, body: { ok: true } } })) {
  const listeners = new Set();
  const sent = [];
  const win = { Response, Blob, URL, atob, btoa, Headers, ArrayBuffer, DOMException, fetch, openai: undefined,
    addEventListener: (name, fn) => { if (name === 'message') listeners.add(fn); },
    removeEventListener: (name, fn) => listeners.delete(fn),
  };
  const deliver = (data, source = win.parent, origin = 'https://chatgpt.test') => {
    for (const fn of [...listeners]) fn({ data, source, origin });
  };
  win.parent = { postMessage(message, target) {
    sent.push({ message, target });
    if (!Object.hasOwn(message, 'id')) return;
    const result = message.method === 'ui/initialize'
      ? { protocolVersion: '2026-01-26', hostContext: { displayMode: 'inline' }, hostCapabilities: { downloadFile: {}, updateModelContext: {} } }
      : handler(message);
    if (result !== undefined) queueMicrotask(() => deliver({ jsonrpc: '2.0', id: message.id, result }));
  } };
  return { win, sent, deliver, listeners };
}
function wavFixture() {
  const b = Buffer.alloc(60);
  b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8);
  b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(8000, 24); b.writeUInt32LE(16000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(16, 40);
  return b;
}
const id = 'a'.repeat(32);

test('initialization precedes tool calls and binds parent origin', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win); await b.api('/api/state');
  assert.equal(h.sent[0].message.method, 'ui/initialize');
  assert.equal(h.sent[1].message.method, 'ui/notifications/initialized');
  assert.equal(h.sent[2].target, 'https://chatgpt.test');
  b.close();
});
test('original UI requests use the app-only JSON gateway', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win); const result = await b.api('/api/state');
  assert.equal(result.ok, true);
  assert.equal(h.sent.at(-1).message.params.name, 'riff_ui_request'); b.close();
});
test('simultaneous state polls coalesce', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win);
  await Promise.all([b.api('/api/state'), b.api('/api/state')]);
  assert.equal(h.sent.filter(x => x.message.method === 'tools/call').length, 1); b.close();
});
test('writes neither coalesce nor retry automatically', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win);
  await Promise.all([b.api('/api/generations', 'POST', { seed: '1' }), b.api('/api/generations', 'POST', { seed: '1' })]);
  assert.equal(h.sent.filter(x => x.message.method === 'tools/call').length, 2);
  assert.equal(h.sent.at(-1).message.params.name, 'riff_ui_request'); b.close();
});
test('traversing and external routes are rejected before a tool call', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win); await b.ready;
  for (const path of ['https://evil.test', '/api/../state', '/api/%73tate', '/api/state?secret=1']) await assert.rejects(b.api(path));
  assert.equal(h.sent.filter(x => x.message.method === 'tools/call').length, 0); b.close();
});
test('tool errors are surfaced rather than treated as generated output', async () => {
  const h = mockWindow(() => ({ isError: true, content: [{ type: 'text', text: 'Engine unavailable.' }] }));
  const b = new RiffBridge(h.win);
  await assert.rejects(b.api('/api/generations', 'POST', {}), /Engine unavailable/); b.close();
});
test('wrong source and wrong origin cannot settle requests', async () => {
  const h = mockWindow(() => undefined); const b = new RiffBridge(h.win); await b.ready;
  const p = b.callTool('riff_read', { path: '/api/state' }); await new Promise(r => setTimeout(r, 0));
  const mid = h.sent.at(-1).message.id;
  const wrong = { jsonrpc: '2.0', id: mid, result: { attacker: true } };
  h.deliver(wrong, {}, 'https://chatgpt.test'); h.deliver(wrong, h.win.parent, 'https://evil.test');
  assert.equal(b.pending.size, 1);
  h.deliver({ jsonrpc: '2.0', id: mid, result: { accepted: true } });
  assert.deepEqual(await p, { accepted: true }); b.close();
});
test('timed-out calls clear pending state and are not retried', async () => {
  const h = mockWindow(() => undefined); const b = new RiffBridge(h.win, { timeoutMs: 10 });
  await assert.rejects(b.callTool('riff_generate', { recipe: {} }), /No mutation will be retried/);
  assert.equal(b.pending.size, 0);
  assert.equal(h.sent.filter(x => x.message.method === 'tools/call').length, 1); b.close();
});
test('WAV transfer consumes metadata without text or network fetch', async () => {
  const wav = wavFixture();
  const h = mockWindow((message) => {
    assert.equal(message.params.name, 'riff_media_chunk');
    return { content: [], structuredContent: { offset: 0, bytes: wav.length, total: wav.length, eof: true },
             _meta: { 'riff/media': { name: 'test.wav', base64: wav.toString('base64'), mimeType: 'audio/wav' } } };
  });
  const b = new RiffBridge(h.win); const blob = await b.audioBlob(id);
  assert.deepEqual(Buffer.from(await blob.arrayBuffer()), wav); assert.equal(blob.type, 'audio/wav'); b.close();
});
test('invalid WAV content is rejected', async () => {
  const h = mockWindow(() => ({ structuredContent: { offset: 0, bytes: 12, total: 12, eof: true },
    _meta: { 'riff/media': { name: 'test.wav', base64: Buffer.alloc(12).toString('base64'), mimeType: 'audio/wav' } } }));
  const b = new RiffBridge(h.win); await assert.rejects(b.audioBlob(id), /WAV recording/); b.close();
});
test('oversized audio is rejected before decoding', async () => {
  const h = mockWindow(() => ({ structuredContent: { offset: 0, bytes: 1, total: 1025 * 1024 * 1024, eof: false } }));
  const b = new RiffBridge(h.win); await assert.rejects(b.audioBlob(id), /oversized/); b.close();
});
test('context and fullscreen use MCP Apps methods', async () => {
  const h = mockWindow(() => ({})); const b = new RiffBridge(h.win);
  await b.shareContext({ selectedTrackId: id }); await b.fullscreen();
  assert.equal(h.sent.at(-2).message.method, 'ui/update-model-context');
  assert.equal(h.sent.at(-1).message.method, 'ui/request-display-mode'); b.close();
});
test('close rejects outstanding work and removes listener', async () => {
  const h = mockWindow(() => undefined); const b = new RiffBridge(h.win); await b.ready;
  const p = b.callTool('riff_read', { path: '/api/state' }); await new Promise(r => setTimeout(r, 0));
  const rejection = assert.rejects(p, /closed/); b.close(); await rejection;
  assert.equal(h.listeners.size, 0); assert.equal(b.pending.size, 0);
});
test('fetch adapter rejects invalid binary upload routes explicitly', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win);
  const response = await b.fetch('/api/video-exports/x/frames', { method: 'POST', body: new Blob(['x']) });
  assert.equal(response.status, 400); assert.match((await response.json()).error, /Unsupported Riff binary upload route/); b.close();
});

test('LoRA query values and review refresh reach the gateway without lossy decoding', async () => {
  const h = mockWindow(); const b = new RiffBridge(h.win);
  const paths = ['/api/loras/hub?q=folk+room&stage=ar%2Bnar&page=0&limit=20',
    '/api/loras/hub/detail?repo=musician%2Fstyle&revision=' + 'a'.repeat(40), '/api/review/models?refresh=1'];
  for (const path of paths) { await b.api(path); assert.equal(h.sent.at(-1).message.params.arguments.path, path); }
  await assert.rejects(b.api('/api/loras/hub?q=one&q=two'), /query/);
  b.close();
});

test('JSON error responses preserve upstream HTTP status for source retry and conflict handling', async () => {
  const h = mockWindow(() => ({ isError: true, structuredContent: { status: 409, body: { error: 'Draft changed.' } } }));
  const b = new RiffBridge(h.win);
  const response = await b.fetch('/api/state');
  assert.equal(response.status, 409); assert.deepEqual(await response.json(), { error: 'Draft changed.' }); b.close();
});

test('File uploads are bounded, ordered, and carry exact metadata on every chunk', async () => {
  const payload = Buffer.alloc(2 * 1024 * 1024 + 7, 9), received = [];
  const uploadId = 'b'.repeat(32);
  const h = mockWindow(({ params }) => {
    assert.equal(params.name, 'riff_upload_chunk');
    const args = params.arguments, bytes = Buffer.from(args.base64, 'base64'); received.push(args);
    assert(bytes.length <= 1024 * 1024);
    return { structuredContent: { upload_id: uploadId, offset: args.offset, bytes: bytes.length,
      received: args.offset + bytes.length, total: args.total, complete: args.final, status: args.final ? 201 : 200,
      body: args.final ? { id: 'installed' } : {} } };
  });
  const b = new RiffBridge(h.win);
  const response = await b.fetch('/api/loras/import?name=music.safetensors', { method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream', 'X-Riff-LoRA-Metadata': '{"name":"Music"}' }, body: new Blob([payload]) });
  assert.equal(response.status, 201); assert.equal((await response.json()).id, 'installed');
  assert.deepEqual(received.map(x => x.offset), [0, 1024 * 1024, 2 * 1024 * 1024]);
  assert.deepEqual(received.map(x => x.final), [false, false, true]);
  assert.equal(received[0].upload_id, undefined); assert.equal(received[1].upload_id, uploadId);
  assert(received.every(x => x.headers['x-riff-lora-metadata'] === '{"name":"Music"}'));
  assert.deepEqual(Buffer.concat(received.map(x => Buffer.from(x.base64, 'base64'))), payload);
  b.close();
});

test('video frames preserve typed-array boundaries and frame sequence headers', async () => {
  const h = mockWindow(({ params }) => {
    const args = params.arguments, bytes = Buffer.from(args.base64, 'base64');
    assert.deepEqual([...bytes], [2, 3, 4]); assert.equal(args.headers['x-riff-frame'], '9');
    assert.equal(args.content_type, 'image/png');
    return { structuredContent: { upload_id: 'c'.repeat(32), offset: 0, bytes: 3, received: 3, total: 3, complete: true, status: 200, body: { received: 10 } } };
  });
  const b = new RiffBridge(h.win), bytes = new Uint8Array([1, 2, 3, 4, 5]);
  const response = await b.fetch(`/api/video-exports/${id}/frames`, { method: 'POST',
    headers: { 'Content-Type': 'image/png', 'X-Riff-Frame': '9' }, body: bytes.subarray(1, 4) });
  assert.equal(response.status, 200); b.close();
});

test('failed staged imports cancel staging and never retry the committed mutation', async () => {
  let writes = 0, cancellations = 0;
  const h = mockWindow(({ params }) => {
    if (params.name === 'riff_upload_cancel') { cancellations++; return { structuredContent: { ok: true } }; }
    writes++; const a = params.arguments, length = Buffer.from(a.base64, 'base64').length;
    if (a.final) return { isError: true, content: [{ type: 'text', text: 'Invalid adapter tensor.' }] };
    return { structuredContent: { upload_id: id, offset: a.offset, bytes: length, received: a.offset + length,
      total: a.total, complete: false, status: 200, body: {} } };
  });
  const b = new RiffBridge(h.win);
  const response = await b.fetch('/api/loras/import?name=bad.safetensors', { method: 'POST', body: new Blob([Buffer.alloc(1024 * 1024 + 1)]) });
  assert.equal(response.status, 400); await new Promise(r => setTimeout(r, 0));
  assert.equal(writes, 2); assert.equal(cancellations, 1); b.close();
});

test('aborted requests reject with AbortError and remove pending listeners', async () => {
  const h = mockWindow(() => undefined), b = new RiffBridge(h.win); await b.ready;
  const controller = new AbortController(), promise = b.fetch('/api/state', { signal: controller.signal });
  await new Promise(r => setTimeout(r, 0)); controller.abort();
  await assert.rejects(promise, error => error.name === 'AbortError'); assert.equal(b.pending.size, 0); b.close();
});

test('media chunks reject mixed metadata and malformed completion markers', async () => {
  const payload = Buffer.alloc(1024 * 1024), h = mockWindow(({ params }) => {
    const offset = params.arguments.offset, bytes = offset ? Buffer.from([1]) : payload;
    return { structuredContent: { offset, bytes: bytes.length, total: payload.length + 1, eof: !!offset },
      _meta: { 'riff/media': { base64: bytes.toString('base64'), name: offset ? 'changed.mp4' : 'movie.mp4', mimeType: 'video/mp4' } } };
  });
  const b = new RiffBridge(h.win); await assert.rejects(b.mediaBlob(`/api/video-exports/${id}/download`), /changed/); b.close();
});

test('exports use the host download request with embedded binary resource', async () => {
  const h = mockWindow(() => ({})); const b = new RiffBridge(h.win);
  await b.downloadBlob(new Blob(['score'], { type: 'text/plain' }), 'melody.abc');
  const request = h.sent.at(-1).message;
  assert.equal(request.method, 'ui/download-file');
  assert.deepEqual(request.params.contents, [{ type: 'resource', resource: { uri: 'file:///melody.abc', mimeType: 'text/plain', blob: Buffer.from('score').toString('base64') } }]);
  b.close();
});

test('denied downloads and messages are not announced as delivered', async () => {
  const h = mockWindow(() => ({ isError: true })); const b = new RiffBridge(h.win);
  await assert.rejects(b.downloadBlob(new Blob(['x']), 'test.txt'), /could not save/);
  await assert.rejects(b.message('Write a chorus'), /could not receive/); b.close();
});

test('Chat file extension exports exact bytes to Library without a shared download capability', async () => {
  const h = mockWindow(), b = new RiffBridge(h.win); await b.ready;
  b.hostCapabilities = {}; h.win.File = File;
  const calls = [];
  h.win.openai = {
    async uploadFile(file, options) { calls.push({ file, options }); return { fileId: 'file-export' }; },
    async getFileDownloadUrl(input) { calls.push(input); return { downloadUrl: 'https://files.chatgpt.test/export.wav' }; },
    async openExternal(input) { calls.push(input); },
  };
  const events = []; b.on('download', value => events.push(value));
  const bytes = wavFixture();
  assert.deepEqual(await b.downloadBlob(new Blob([bytes], { type: 'audio/wav' }), '../take.wav'), { fileId: 'file-export' });
  assert.deepEqual(Buffer.from(await calls[0].file.arrayBuffer()), bytes);
  assert.equal(calls[0].file.name, '.._take.wav');
  assert.equal(calls[0].file.type, 'audio/wav');
  assert.deepEqual(calls[0].options, { library: true });
  assert.deepEqual(calls[1], { fileId: 'file-export' });
  assert.deepEqual(calls[2], { href: 'https://files.chatgpt.test/export.wav', redirectUrl: false });
  assert.deepEqual(events, [{ name: '.._take.wav', bytes: bytes.length }]);
  assert.equal(h.sent.some(x => x.message.method === 'ui/download-file'), false); b.close();
});

test('Chat file export does not replay rejected uploads or announce failed downloads', async () => {
  const h = mockWindow(), b = new RiffBridge(h.win); await b.ready;
  b.hostCapabilities = {}; h.win.File = File;
  let uploads = 0, opened = 0; const events = []; b.on('download', x => events.push(x));
  h.win.openai = {
    async uploadFile() { uploads++; throw new Error('Upload denied'); },
    async getFileDownloadUrl() { return { downloadUrl: 'javascript:alert(1)' }; },
    async openExternal() { opened++; },
  };
  await assert.rejects(b.downloadBlob(new Blob(['score']), 'score.abc'), /Upload denied/);
  assert.equal(uploads, 1);
  h.win.openai.uploadFile = async () => ({ fileId: 'file-export' });
  await assert.rejects(b.downloadBlob(new Blob(['score']), 'score.abc'), /valid file download URL/);
  assert.equal(opened, 0); assert.deepEqual(events, []); b.close();
});

test('WAV export uses the current conversation when the host cannot download app files', async () => {
  const h = mockWindow(() => ({})), b = new RiffBridge(h.win); await b.ready;
  b.hostCapabilities = {};
  const events = []; b.on('export-request', value => events.push(value));
  const result = await b.downloadLink({ getAttribute: () => `/api/tracks/${id}/audio?download=1` });
  assert.deepEqual(result, { requestedInChat: true });
  const request = h.sent.at(-1).message;
  assert.equal(request.method, 'ui/message');
  assert(request.params.content[0].text.includes(id));
  assert(request.params.content[0].text.includes('Do not generate music or change the draft.'));
  assert.deepEqual(events, [{ trackId: id }]);
  assert.equal(h.sent.some(x => x.message.method === 'tools/call'), false); b.close();
});

test('background context omits transcript content and explicit context attaches it', async () => {
  const h = mockWindow(() => ({})); const b = new RiffBridge(h.win);
  const context = { recipe: { style: 'folk' }, sharedDraftRevision: 3 };
  await b.shareContext(context, { explicit: false });
  assert.deepEqual(h.sent.at(-1).message.params, { structuredContent: context });
  await b.shareContext(context); assert.equal(h.sent.at(-1).message.params.content[0].type, 'text'); b.close();
});

test('direct tool-result params and host deep links retain project context', async () => {
  const h = mockWindow(), b = new RiffBridge(h.win); await b.ready;
  let received;
  b.on('tool-result', result => received = result);
  const result = { structuredContent: { body: { draft: { revision: 1, recipe: { title: 'Room' } } } }, _meta: { private: 'kept' } };
  h.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: result });
  assert.deepEqual(received, result);
  h.deliver({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { 'openai/deepLink': { url: '/?recording=' + id } } });
  assert.equal(b.preferredTrack(), id); assert.equal(b.hostContext.displayMode, 'inline');
  h.deliver({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { 'openai/deepLink': { url: 'https://evil.test/?recording=' + id } } });
  assert.equal(b.preferredTrack(), null); b.close();
});

test('resource teardown acknowledges only after view cleanup', async () => {
  const h = mockWindow(), b = new RiffBridge(h.win); await b.ready;
  let cleaned = false;
  b.on('teardown', async () => { await new Promise(r => setTimeout(r, 10)); cleaned = true; });
  h.deliver({ jsonrpc: '2.0', id: 'host-close', method: 'ui/resource-teardown', params: {} });
  assert.equal(b.closed, false); await new Promise(r => setTimeout(r, 30));
  assert.equal(cleaned, true); assert.equal(b.closed, true);
  assert.deepEqual(h.sent.at(-1).message, { jsonrpc: '2.0', id: 'host-close', result: {} });
});
