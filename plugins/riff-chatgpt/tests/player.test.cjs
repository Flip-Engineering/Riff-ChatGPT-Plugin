const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, writeFileSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.RIFF_PLAYWRIGHT_MODULE || 'playwright');

for (const preview of [false, true]) test(`sandboxed ${preview ? 'budgeted preview and full-file' : 'exact WAV'} player works without a server`, { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, '../../..');
  const temporary = mkdtempSync(path.join(os.tmpdir(), 'riff-player-test-'));
  let browser;
  try {
    // A deterministic PCM fixture tests media transport; it is not generated music.
    execFileSync('python3', ['-c', `
import importlib.util,io,json,math,shutil,struct,sys,wave
from pathlib import Path
from html.parser import HTMLParser
repo,out=map(Path,sys.argv[1:3]);preview=sys.argv[3]=='true'
spec=importlib.util.spec_from_file_location('player',repo/'plugins/riff-chatgpt/cloud/player.py')
player=importlib.util.module_from_spec(spec);spec.loader.exec_module(player)
stream=io.BytesIO()
with wave.open(stream,'wb') as wav:
 wav.setparams((1,2,8000,0,'NONE','not compressed'))
 wav.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(i*math.pi/20))) for i in range(16000)))
bundle=out/'bundle';(bundle/'riff').mkdir(parents=True)
(bundle/'riff/web').symlink_to(repo/'riff/web',target_is_directory=True)
(bundle/'runtime/media').mkdir(parents=True)
if preview:(bundle/'runtime/media/ffmpeg').symlink_to(shutil.which('ffmpeg'))
(out/'recording.wav').write_bytes(stream.getvalue())
(out/'wrong.wav').write_bytes(b'wrong recording')
track={'id':'a'*32,'title':'__DATA__ <script>window.injected=true</script>','recipe':{'seed':'1234'}}
motion={'fps':10,'frames':[[i/20,.4,.3,.2,0,.2,.5,.1] for i in range(21)]}
receipt=player.build_player(bundle,track,motion,stream.getvalue(),out/'player.html',60000 if preview else 1000000)
assert receipt['preview']==preview
assert receipt['html_bytes']<=(60000 if preview else 1000000)
class FragmentParser(HTMLParser):
 def handle_starttag(self,tag,attrs):assert tag not in ('html','head','body')
 def handle_decl(self,decl):assert not decl.lower().startswith('doctype')
FragmentParser().feed((out/'player.html').read_text())
(out/'receipt.json').write_text(json.dumps(receipt))
`, root, temporary, String(preview)], { stdio: 'pipe' });
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.RIFF_BROWSER_EXECUTABLE,
      args: ['--enable-unsafe-swiftshader'] });
    let page = await browser.newPage({ viewport: { width: 900, height: 850 } });
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => requests.push(r.url()));
    // Exercise an opaque iframe and offline CSP, including user-file input and
    // a trusted keyboard play action, instead of relying on relaxed autoplay.
    const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src blob: data:; connect-src blob: data:; img-src data:; worker-src blob:">`;
    const source = (policy + readFileSync(path.join(temporary, 'player.html'), 'utf8')).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
    writeFileSync(path.join(temporary, 'host.html'), `<!doctype html><iframe name="riff-player" sandbox="allow-scripts allow-forms allow-downloads" allow="autoplay" style="width:880px;height:800px;border:0" srcdoc="${source}"></iframe>`);
    await page.goto('file://' + path.join(temporary, 'host.html'));
    await page.frameLocator('iframe').locator('audio').waitFor({ state: 'attached' });
    page = await (await page.locator('iframe').elementHandle()).contentFrame();
    await page.waitForFunction(() => document.querySelector('audio').readyState >= 2);
    assert.equal(await page.locator('h1').innerText(), '__DATA__ <script>window.injected=true</script>');
    assert.equal(await page.evaluate(() => window.injected), undefined);
    if (preview) {
      assert((await page.locator('audio').evaluate(e => e.duration)) < 2);
      assert.equal(await page.locator('#download').innerText(), 'Download preview');
      await page.locator('#full-file').setInputFiles(path.join(temporary, 'wrong.wav'));
      await page.waitForFunction(() => document.querySelector('#status').textContent.includes('does not match'));
      await page.locator('#full-file').setInputFiles(path.join(temporary, 'recording.wav'));
      await page.waitForFunction(() => document.querySelector('#mode').textContent.includes('SHA-256 verified'));
      await page.waitForFunction(() => document.querySelector('audio').readyState >= 2);
    }
    assert.equal(await page.locator('audio').evaluate(e => e.duration), 2);
    const before = await page.locator('canvas').evaluate(e => e.toDataURL());
    await page.locator('audio').press('Space');
    await page.waitForFunction(() => document.querySelector('audio').currentTime > .35);
    const after = await page.locator('canvas').evaluate(e => e.toDataURL());
    assert.notEqual(before, after, 'Artwork must change with playback');
    await page.locator('audio').evaluate(e => { e.pause(); e.currentTime = 1.25; });
    await page.waitForFunction(() => Math.abs(document.querySelector('audio').currentTime - 1.25) < .01);
    await page.locator('#loop').check();
    await page.locator('audio').evaluate(e => { e.currentTime = 1.9; return e.play(); });
    await page.waitForFunction(() => document.querySelector('audio').currentTime < .8);
    await page.locator('audio').evaluate(e => e.pause());
    assert.equal(await page.locator('audio').evaluate(e => e.loop), true);
    assert.equal(await page.locator('#download').getAttribute('href'), await page.locator('audio').getAttribute('src'));
    const receipt = JSON.parse(await page.locator('#receipt').textContent());
    const audioHash = await page.locator('audio').evaluate(async e => {
      const bytes = await (await fetch(e.src)).arrayBuffer();
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
    });
    assert.equal(audioHash, receipt.audio_sha256);
    assert.equal(receipt.frames, 16000);
    assert.equal(receipt.audio_bytes, 32044);
    assert.equal(requests.filter(url => /^https?:/.test(url)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    rmSync(temporary, { recursive: true, force: true });
  }
});
