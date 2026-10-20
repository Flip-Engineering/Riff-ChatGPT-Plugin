const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.RIFF_PLAYWRIGHT_MODULE || 'playwright');

test('exported recording plays, seeks, loops and animates the pinned artwork without a server', { timeout: 60000 }, async () => {
  const root = path.resolve(__dirname, '../../..');
  const temporary = mkdtempSync(path.join(os.tmpdir(), 'riff-player-test-'));
  let browser;
  try {
    // A deterministic PCM fixture tests media transport; it is not generated music.
    execFileSync('python3', ['-c', `
import importlib.util,io,json,math,struct,sys,wave
from pathlib import Path
repo,out=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('player',repo/'plugins/riff-chatgpt/cloud/player.py')
player=importlib.util.module_from_spec(spec);spec.loader.exec_module(player)
stream=io.BytesIO()
with wave.open(stream,'wb') as wav:
 wav.setparams((1,2,8000,0,'NONE','not compressed'))
 wav.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(i*math.pi/20))) for i in range(16000)))
bundle=out/'bundle';(bundle/'riff').mkdir(parents=True)
(bundle/'riff/web').symlink_to(repo/'riff/web',target_is_directory=True)
track={'id':'a'*32,'title':'__DATA__ <script>window.injected=true</script>','recipe':{'seed':'1234'}}
motion={'fps':10,'frames':[[i/20,.4,.3,.2,0,.2,.5,.1] for i in range(21)]}
receipt=player.build_player(bundle,track,motion,stream.getvalue(),out/'player.html')
(out/'receipt.json').write_text(json.dumps(receipt))
`, root, temporary], { stdio: 'pipe' });
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.RIFF_BROWSER_EXECUTABLE,
      args: ['--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 900, height: 850 } });
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => requests.push(r.url()));
    await page.goto('file://' + path.join(temporary, 'player.html'));
    await page.waitForFunction(() => document.querySelector('audio').readyState >= 2);
    assert.equal(await page.locator('h1').innerText(), '__DATA__ <script>window.injected=true</script>');
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.equal(await page.locator('audio').evaluate(e => e.duration), 2);
    const before = await page.locator('canvas').evaluate(e => e.toDataURL());
    await page.locator('audio').evaluate(e => e.play());
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
    assert.equal(receipt.frames, 16000);
    assert.equal(receipt.audio_bytes, 32044);
    assert.equal(requests.filter(url => /^https?:/.test(url)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    rmSync(temporary, { recursive: true, force: true });
  }
});
