const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, writeFileSync, readFileSync } = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.RIFF_PLAYWRIGHT_MODULE || 'playwright');
const { startHost, ROOT, PLUGIN } = require('./browser/host.cjs');

const RESULTS = path.join(ROOT, 'test-results/chatgpt-plugin');
mkdirSync(RESULTS, { recursive: true });

test('complete original Riff studio through production ManagedRiff and stdio MCP', { timeout: 240000 }, async t => {
  const host = await startHost();
  let browser, page;
  const errors = [], frameRequests = [], checks = [];
  const check = text => { checks.push(text); console.log('PASS ' + text); };
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.RIFF_BROWSER_EXECUTABLE,
      args: ['--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader'] });
    page = await browser.newPage({ viewport: { width: 1400, height: 1080 }, reducedMotion: 'reduce' });
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { try { if (request.frame().name() === 'riff-studio') frameRequests.push(request.url()); } catch {} });
    await page.goto(host.url);
    let app = page.frame({ name: 'riff-studio' });
    await app.waitForFunction(() => typeof selected !== 'undefined' && selected && document.querySelector('#play').disabled === false);
    await app.waitForFunction(() => document.querySelector('#riff-chatgpt-status').textContent.includes('ready'));
    assert.equal(await app.evaluate(() => selected.id), host.fixture.track_id);
    assert.equal(await app.locator('#generation-form').count(), 1);
    assert.equal(await app.locator('#score-dialog').count(), 1);
    assert.equal(await app.locator('#lora-dialog').count(), 1);
    assert.equal(await app.locator('#take-comparison').count(), 1);
    assert.equal(await app.locator('#producer-panel').count(), 1);
    assert.equal(await app.locator('#studio-update').isHidden(), true);
    assert.equal(await page.locator('iframe').getAttribute('sandbox'), 'allow-scripts allow-forms allow-modals');
    check('The original studio, score workspace, library, comparison and producer panels load in an opaque sandbox through the real MCP resource');

    await app.locator('#play').click();
    await app.waitForFunction(() => audio.currentTime > .15);
    await app.locator('#play').click();
    const firstSource = await app.locator('#audio').getAttribute('src');
    assert(firstSource.startsWith('blob:'));
    await app.locator('#take-comparison').evaluate(node => node.open = true);
    const originalDraft = await app.evaluate(() => JSON.stringify(formRecipe()));
    await app.locator('#compare-a').selectOption(host.fixture.track_id);
    await app.locator('#compare-b').selectOption(host.fixture.second_track_id);
    await app.locator('[data-compare=b]').click();
    await app.waitForFunction(id => selected.id === id, host.fixture.second_track_id);
    await app.locator('[data-compare=a]').click();
    await app.waitForFunction(id => selected.id === id, host.fixture.track_id);
    assert.equal(await app.evaluate(() => JSON.stringify(formRecipe())), originalDraft);
    check('Chunked WAV media decodes and plays; A/B switching keeps the creative draft');

    await app.locator('#title').fill('A studio in ChatGPT');
    await app.locator('input[name="creation-mode"][value="lyrics"]').check();
    await app.locator('#lyrics').fill('[Verse]\nA little light across the bay.\nThe reeds will sing another day.');
    await app.locator('#style').fill('warm folk, intimate room');
    await app.locator('#riff-save-shared').click();
    await app.waitForFunction(() => document.querySelector('#riff-chatgpt-status').textContent === 'Shared draft saved.');
    let shared = (await host.rpc('tools/call', { name: 'riff_get_draft', arguments: {} })).structuredContent.body;
    assert.equal(shared.recipe.title, 'A studio in ChatGPT');
    await host.rpc('tools/call', { name: 'riff_save_draft', arguments: { expected_revision: shared.revision, recipe: { ...shared.recipe, title: 'Written together' } } });
    await app.waitForFunction(() => document.querySelector('#title').value === 'Written together');
    await app.locator('#title').fill('My unsaved title');
    shared = (await host.rpc('tools/call', { name: 'riff_get_draft', arguments: {} })).structuredContent.body;
    await host.rpc('tools/call', { name: 'riff_save_draft', arguments: { expected_revision: shared.revision, recipe: { ...shared.recipe, title: 'ChatGPT revised title' } } });
    await app.waitForFunction(() => document.querySelector('#riff-chatgpt-status').textContent.includes('while you were editing'));
    assert.equal(await app.locator('#title').inputValue(), 'My unsaved title');
    page.once('dialog', dialog => dialog.accept());
    await app.locator('#riff-restore-shared').click();
    await app.waitForFunction(() => document.querySelector('#title').value === 'ChatGPT revised title');
    check('Draft saves round-trip to SQLite; agent edits sync; concurrent local edits produce a recoverable conflict');

    await app.locator('#riff-share-context').click();
    await app.evaluate(() => RiffHost.fullscreen());
    await app.locator('#riff-write-with-chatgpt').click();
    await app.locator('#riff-writing-request').fill('Write a more hopeful chorus.');
    await app.locator('#riff-chatgpt-writing button[type=submit]').click();
    await page.waitForFunction(() => hostMessages.length === 1);
    const chat = await page.evaluate(() => ({ message: hostMessages[0], contexts: hostContexts, trace: hostTrace }));
    assert(chat.message.content[0].text.includes('hopeful chorus'));
    assert(chat.contexts.some(x => x.content?.[0]?.type === 'text'));
    assert(chat.contexts.some(x => x.structuredContent?.recipe && !x.content));
    assert(chat.trace.some(x => x.method === 'ui/request-display-mode'));
    check('Explicit ChatGPT writing, background structured context, draft attachment and fullscreen use host protocol methods');

    await app.locator('#system-open').click();
    assert.equal(await app.locator('#setup-engine').textContent(), 'Download music models');
    assert(await app.locator('#engine-backend').isHidden());
    assert(await app.locator('#engine-binary').isHidden());
    await app.locator('#engine-threads').fill('2');
    await app.locator('#engine-form button[type=submit]').click();
    await app.waitForFunction(() => document.querySelector('#toast').textContent === 'Engine settings saved');
    await app.locator('[data-close=system-dialog]').click();
    check('Managed studio settings retain CPU tuning and expose the real pinned model setup while hiding fixed installation paths');

    await app.locator('#lora-composer').evaluate(node => node.open = true);
    await app.locator('#lora-open').click();
    await app.locator('[data-lora-hub]').waitFor();
    await app.locator('#lora-query').fill('folk');
    await app.locator('#lora-search-form button[type=submit]').click();
    await app.locator('[data-lora-hub]').waitFor();
    await app.locator('[data-lora-hub]').click();
    await app.locator('#lora-install').waitFor();
    assert(await app.locator('#lora-detail input:disabled').count() >= 1);
    assert.equal(await app.evaluate(() => window.loraXSS), undefined);
    await app.locator('.riff-media-load').first().click();
    await app.waitForFunction(() => document.querySelector('#lora-detail audio').currentTime > .1);
    await app.locator('#lora-detail audio').evaluate(audio => audio.pause());
    await app.locator('#lora-install').click();
    await app.waitForFunction(async () => (await RiffHost.api('/api/loras')).loras.some(item => item.source?.type === 'huggingface'));
    await app.locator('#lora-import-open').click();
    await app.locator('#lora-import-file').setInputFiles(host.fixture.loras.upload);
    await app.waitForFunction(() => document.querySelector('#lora-status').textContent.includes('imported'));
    const loras = await app.evaluate(() => RiffHost.api('/api/loras'));
    assert(loras.loras.some(item => item.files.some(file => file.original_name === 'local-study.safetensors')));
    const installed = loras.loras.find(item => item.source?.type === 'huggingface');
    await app.locator(`[data-lora-use="${installed.id}"]`).click();
    await app.locator('#lora-dialog').waitFor({ state: 'hidden' });
    assert.equal(await app.locator('#lora-ar').inputValue(), installed.id);
    assert.equal(await app.locator('#lora-nar').inputValue(), installed.id);
    check('Community search, safe cards, preview playback, verified installation and binary safetensors import use actual backend LoRA code');

    await app.locator('#duration').fill('4');
    await app.locator('#generate').click();
    await app.waitForFunction(() => state.jobs.some(job => job.status === 'done'));
    const generated = await app.evaluate(() => state.jobs.find(job => job.status === 'done'));
    const detail = await app.evaluate(id => RiffHost.api('/api/tracks/' + id), generated.track_id);
    assert(detail.recipe.lora_provenance[0].files.length === 2);
    check('The real queue creates a recording, with complete adapter provenance; audio inference itself is an explicit test double');

    await app.locator('.study-controls').evaluate(node => node.open = true);
    await app.locator('#export-draft').click();
    await page.waitForFunction(() => hostDownloads.some(x => x.mimeType === 'application/json'));
    await app.locator('#track-details').click();
    await app.locator('#export-audio').click();
    await page.waitForFunction(() => hostDownloads.some(x => x.mimeType === 'audio/wav'));
    await app.locator('#export-art').click();
    await page.waitForFunction(() => hostDownloads.some(x => x.mimeType === 'image/png'));
    await app.locator('[data-close=track-dialog]').click();
    const downloads = await page.evaluate(() => hostDownloads);
    assert.equal(Buffer.from(downloads.find(x => x.mimeType === 'audio/wav').blob, 'base64').toString('ascii', 0, 4), 'RIFF');
    assert.equal(Buffer.from(downloads.find(x => x.mimeType === 'image/png').blob, 'base64').toString('hex', 0, 8), '89504e470d0a1a0a');
    check('WAV, recipe and seed artwork exports reach ui/download-file with real bytes despite an iframe without allow-downloads');

    await app.locator('.creative-controls').evaluate(node => node.open = true);
    await app.locator('#score-open').click();
    const abc = 'X:1\nT:Studio sketch\nM:4/4\nL:1/8\nQ:1/4=108\nK:Dm\nD2 F2 A2 G2|F2 E2 D4|\n';
    await app.locator('#import-abc').setInputFiles({ name: 'sketch.abc', mimeType: 'text/plain', buffer: Buffer.from(abc) });
    await app.waitForFunction(() => document.querySelector('#score-notation svg'));
    await app.locator('#transpose-up').click();
    await app.locator('#export-abc').click(); await app.locator('#export-midi').click();
    await page.waitForFunction(() => hostDownloads.some(x => x.mimeType === 'audio/midi'));
    const midi = await page.evaluate(() => hostDownloads.find(x => x.mimeType === 'audio/midi'));
    assert.equal(Buffer.from(midi.blob, 'base64').toString('ascii', 0, 4), 'MThd');
    await app.locator('#compose-score').click();
    await app.waitForFunction(() => document.querySelector('#score-status').textContent === 'Score ready');
    await app.locator('[data-close=score-dialog]').click();
    check('Original ABC import, notation editing, MIDI/ABC exports and queued score composition operate through the plugin');

    await app.locator('#review-settings-open').click();
    await app.locator('#refresh-review-models').click();
    await app.waitForFunction(() => document.querySelector('#review-model-status').textContent.includes('1 audio model'));
    await app.locator('#reviews-enabled').check();
    await app.locator('#review-model').fill('fixture/audio-model');
    await app.locator('#review-api-key').fill('sk-riff-browser-fixture-only');
    await app.locator('#review-settings-form button[type=submit]').click();
    await app.locator('#review-settings-dialog').waitFor({ state: 'hidden' });
    await app.locator('#producer-panel').evaluate(node => node.open = true);
    await app.locator('#review-focus').fill('Listen for the balance of the melody and accompaniment.');
    await app.locator('#request-review').click();
    await app.locator('[data-export-review]').first().waitFor({ state: 'attached' });
    await app.locator('[data-export-review]').first().evaluate(node => node.closest('details').open = true);
    await app.locator('[data-export-review]').first().click();
    await page.waitForFunction(() => hostDownloads.some(x => x.uri.endsWith('riff-recommended-take.json')));
    await app.locator('#review-settings-open').click();
    await app.locator('#remove-review-key').click();
    await app.waitForFunction(() => document.querySelector('#toast').textContent === 'Review key removed.');
    await app.locator('[data-close=review-settings-dialog]').click();
    assert.equal(await page.evaluate(() => JSON.stringify(hostContexts).includes('sk-riff-browser-fixture-only')), false);
    check('Optional review settings, model refresh, queued listening notes, recommended-recipe export and key removal preserve the original workflow without exposing credentials to chat');

    const worker = await app.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 48;
      canvas.getContext('2d').fillRect(0, 0, 64, 48);
      const encoder = await createVideoFrameEncoder(canvas, new AbortController().signal, { transport: 'png' });
      const workerCount = RiffHost.workers.size;
      try { const bytes = await encoder.encode(0); return { workerCount, signature: [...new Uint8Array(bytes).slice(0, 8)] }; }
      finally { encoder.close(); }
    });
    assert.equal(worker.workerCount, 1); assert.deepEqual(worker.signature, [137, 80, 78, 71, 13, 10, 26, 10]);
    await app.locator('#download-video').click();
    await app.locator('#video-options').evaluate(node => node.open = true);
    await app.locator('#video-width').fill('320'); await app.locator('#video-height').fill('248'); await app.locator('#video-fps').fill('12');
    await app.locator('#video-selection').selectOption('passage'); await app.locator('#video-end').fill('0:01');
    await app.locator('#render-video').click();
    await page.waitForFunction(() => hostDownloads.some(x => x.mimeType === 'video/mp4'), { timeout: 90000 });
    await app.waitForFunction(() => videoExport === null);
    const video = await page.evaluate(() => hostDownloads.find(x => x.mimeType === 'video/mp4'));
    const videoPath = path.join(RESULTS, 'original-studio-video.mp4');
    writeFileSync(videoPath, Buffer.from(video.blob, 'base64'));
    const probe = JSON.parse(execFileSync(process.env.RIFF_FFPROBE || 'ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type,width,height,duration', '-of', 'json', videoPath], { encoding: 'utf8' }));
    assert(probe.streams.some(x => x.codec_type === 'video' && x.width === 320 && x.height === 248));
    assert(probe.streams.some(x => x.codec_type === 'audio'));
    await app.locator('[data-close=video-dialog]').click();
    check('The bundled video worker produces PNG frames; staged frame uploads and real FFmpeg finish a playable MP4 with original audio');

    await page.screenshot({ path: path.join(RESULTS, 'studio-desktop.png'), fullPage: false });
    await page.setViewportSize({ width: 390, height: 844 });
    await app.evaluate(() => showView('studio', false));
    assert(await app.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(RESULTS, 'studio-mobile.png'), fullPage: false });
    await page.setViewportSize({ width: 1400, height: 1080 });
    await page.evaluate(id => window.sendRiff('ui/notifications/host-context-changed', { 'openai/deepLink': { url: '/?recording=' + id } }), host.fixture.second_track_id);
    await app.waitForFunction(id => selected.id === id, host.fixture.second_track_id);
    check('Responsive original UI and host-directed recording deep links work without iframe URL navigation');

    await page.evaluate(() => { const frame = document.querySelector('iframe'); frame.srcdoc = frame.srcdoc.replace('media-src data: blob:', 'media-src data:').replace('worker-src blob:', "worker-src 'none'"); });
    app = page.frame({ name: 'riff-studio' });
    await app.waitForFunction(() => typeof selected !== 'undefined' && selected && document.querySelector('#audio').src.startsWith('data:') && audio.readyState >= 1);
    const fallback = await app.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32;
      const encoder = await createVideoFrameEncoder(canvas, new AbortController().signal, { transport: 'png' });
      try { return { workers: RiffHost.workers.size, bytes: (await encoder.encode(0)).byteLength }; }
      finally { encoder.close(); }
    });
    assert.equal(fallback.workers, 0); assert(fallback.bytes > 20);
    await app.locator('#play').click(); await app.waitForFunction(() => audio.currentTime > .1); await app.locator('#play').click();
    check('A host denying blob media/workers still plays data-URL audio and encodes frames with the original canvas fallback');

    await page.evaluate(() => window.sendRiff('ui/resource-teardown', {}, 'close-studio'));
    await page.waitForFunction(() => window.lastHostResponse?.id === 'close-studio');
    assert.equal(await app.evaluate(() => RiffHost.closed), true);
    const finalState = await host.rpc('tools/call', { name: 'riff_read', arguments: { path: '/api/state' } });
    assert(!finalState.isError && finalState.structuredContent.body.tracks.length >= 3);
    check('View teardown acknowledges cleanup while the shared backend and saved music remain available');
    assert.deepEqual(errors, []);
    assert(frameRequests.every(url => url.startsWith('blob:') || url.startsWith('data:')), 'No original UI request escapes the MCP bridge: ' + frameRequests.join(', '));
    const trace = await page.evaluate(() => hostTrace);
    assert(trace.some(x => x.name === 'riff_upload_chunk' && x.path.startsWith('/api/video-exports/')));
    assert(trace.some(x => x.name === 'riff_upload_chunk' && x.path.startsWith('/api/loras/import')));
    writeFileSync(path.join(RESULTS, 'acceptance.json'), JSON.stringify({ checks, runtime: 'production ManagedRiff + stdio MCP',
      test_doubles: host.fixture.test_doubles, browser: await browser.version(), errors, frame_network_requests: frameRequests,
      tool_calls: trace.filter(x => x.method === 'tools/call').length }, null, 2));
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(RESULTS, 'failure.png'), fullPage: false }).catch(() => {});
      console.error('Browser errors:', errors);
      console.error('Recent host calls:', await page.evaluate(() => hostTrace?.slice(-12)).catch(() => []));
      console.error('Frame status:', await page.frame({ name: 'riff-studio' })?.evaluate(() => ({ status: document.querySelector('#riff-chatgpt-status')?.textContent, toast: document.querySelector('#toast')?.textContent, form: document.querySelector('#form-error')?.textContent, video: document.querySelector('#video-error')?.textContent, lora: document.querySelector('#lora-status')?.textContent })).catch(() => null));
    }
    console.error(host.diagnostics()); throw error;
  } finally { await browser?.close(); await host.close(); }
});
