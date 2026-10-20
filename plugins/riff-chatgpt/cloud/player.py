#!/usr/bin/env python3
"""Export an actual Riff recording as a self-contained HTML player for Chat.

Uses the pinned upstream artwork renderer and motion interpolation unchanged.
This is a recording view; it does not pretend to connect studio controls.
"""
import argparse
import base64
import hashlib
import html
import io
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def script(source):
    # JSON values may contain user lyrics or titles, including HTML end tags.
    return source.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def build_player(bundle, track, motion, audio, output):
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        measured = {'frames': wav.getnframes(), 'sample_rate': wav.getframerate(),
                    'channels': wav.getnchannels(), 'duration': wav.getnframes()/wav.getframerate()}
    web = bundle/'riff/web'
    artwork = (web/'artwork.js').read_text()
    visualizer = (web/'visualizer.js').read_text()
    # Fail on upstream drift instead of silently substituting a visualizer.
    start, end = 'function motionAt(data, seconds) {', '\nfunction updateMiniPlayer()'
    if visualizer.count(start) != 1 or visualizer.count(end) != 1:
        raise ValueError('Pinned Riff motion interpolation changed; review the player integration.')
    interpolation = visualizer[visualizer.index(start):visualizer.index(end)]
    receipt = {'recording_id': track['id'], 'audio_sha256': hashlib.sha256(audio).hexdigest(),
               'audio_bytes': len(audio), **measured,
               'artwork_sha256': hashlib.sha256(artwork.encode()).hexdigest(),
               'visualizer_sha256': hashlib.sha256(visualizer.encode()).hexdigest()}
    payload = {'track': track, 'motion': motion, 'receipt': receipt,
               'audio': base64.b64encode(audio).decode('ascii')}
    title = html.escape(str(track.get('title') or 'Riff recording'))
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · Riff</title>
<style>
:root{color-scheme:light dark;font:15px/1.5 system-ui,sans-serif;background:#edf0ec;color:#24352f}
body{margin:0;padding:20px}main{max-width:840px;margin:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:baseline}
h1{font-size:22px;font-weight:500;letter-spacing:-.03em;margin:4px 0}p{margin:4px 0 16px;color:#53665c}
canvas{display:block;width:100%;height:clamp(220px,45vw,440px);border-radius:16px;background:#e0e7e0}
audio{display:block;width:100%;margin:16px 0 8px}footer{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:13px}
a{color:inherit}details{font-size:12px;margin-top:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere}
@media(prefers-color-scheme:dark){:root{background:#17221e;color:#dce5de}p{color:#a7b9ad}}
</style><main><header><h1>__TITLE__</h1><span>RIFF</span></header>
<p>Recording player · Original Riff sound visualization</p>
<canvas id="visualizer" aria-label="Riff audio-reactive artwork"></canvas>
<audio id="audio" controls preload="auto"></audio>
<footer><label><input id="loop" type="checkbox"> Loop</label><a id="download" download="riff-recording.wav">Download WAV</a><span id="status" role="status">Loading recording…</span></footer>
<p style="font-size:12px;margin-top:18px">This saved recording plays inside this panel. Ask Riff in Chat to compose, manage the library or change LoRAs.</p>
<details><summary>Recording receipt</summary><pre id="receipt"></pre></details></main>
<script id="riff-player-data" type="application/json">__DATA__</script>
<script>__ARTWORK__
const settledMotion = new WeakMap();
__INTERPOLATION__
const data=JSON.parse(document.getElementById('riff-player-data').textContent);
const audio=document.getElementById('audio'),canvas=document.getElementById('visualizer');
const raw=Uint8Array.from(atob(data.audio),c=>c.charCodeAt(0));
const url=URL.createObjectURL(new Blob([raw],{type:'audio/wav'}));
audio.src=url;document.getElementById('download').href=url;
document.getElementById('receipt').textContent=JSON.stringify(data.receipt,null,2);
document.getElementById('loop').addEventListener('change',e=>audio.loop=e.target.checked);
const reduced=matchMedia('(prefers-reduced-motion: reduce)');let frame=null;
function draw(){
  frame=null;const r=canvas.getBoundingClientRect(),scale=devicePixelRatio||1;
  canvas.width=Math.round(r.width*scale);canvas.height=Math.round(r.height*scale);
  drawSeedArtwork(canvas.getContext('2d'),canvas.width,canvas.height,data.track.recipe?.seed??data.track.id,
    audio.currentTime,motionAt(data.motion,audio.currentTime),RiffArtwork.defaults);
  if(!audio.paused&&!audio.ended&&!reduced.matches&&!document.hidden)frame=requestAnimationFrame(draw);
}
function refresh(){if(frame!==null)cancelAnimationFrame(frame);draw()}
for(const event of ['play','pause','seeked','loadedmetadata','ended'])audio.addEventListener(event,refresh);
audio.addEventListener('loadedmetadata',()=>document.getElementById('status').textContent=audio.duration.toFixed(3)+' seconds');
audio.addEventListener('error',()=>document.getElementById('status').textContent='Playback failed: '+(audio.error?.message||'audio decode error'));
document.addEventListener('visibilitychange',refresh);addEventListener('resize',refresh);reduced.addEventListener('change',refresh);
draw();
</script></html>'''
    # A single pass prevents user text resembling a token from being expanded.
    values = {'__ARTWORK__': artwork, '__INTERPOLATION__': interpolation,
              '__TITLE__': title, '__DATA__': script(json.dumps(payload, ensure_ascii=False))}
    page = re.sub('|'.join(values), lambda match: values[match[0]], page)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page)
    return {**receipt, 'html': str(output), 'html_bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.cwd()/'riff-workspace')
    parser.add_argument('--track-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{32}', args.track_id):
        parser.error('track-id must be a real Riff recording ID')
    from riff import bootstrap
    bundle = bootstrap(Path(__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp)/'result.json'
        def call(tool, arguments):
            result = subprocess.run([sys.executable, '-B', str(bundle/'server/cloud.py'),
                '--workspace', str(args.workspace.resolve()), 'call', tool,
                '--arguments', json.dumps(arguments), '--output-file', str(private)],
                capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout+result.stderr)
            return json.loads(private.read_text())['result']
        def read(path):
            return call('riff_read', {'path':path})['structuredContent']['body']
        track = read('/api/tracks/'+args.track_id)
        motion = read('/api/tracks/'+args.track_id+'/visualization')
        audio = bytearray()
        while True:
            result = call('riff_audio_chunk', {'track_id':args.track_id,'offset':len(audio),'length':1024*1024})
            chunk = base64.b64decode(result['_meta']['riff/audio']['base64'], validate=True)
            audio.extend(chunk)
            if result['structuredContent']['eof']:
                break
            if not chunk:
                raise ValueError('The recording transfer stopped before EOF.')
        print(json.dumps(build_player(bundle, track, motion, bytes(audio), args.output.resolve())))


if __name__ == '__main__':
    main()
