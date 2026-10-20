#!/usr/bin/env python3
"""Export an actual Riff recording as a self-contained HTML player for Chat.

Uses the pinned upstream artwork renderer and motion interpolation unchanged.
This is a recording view; it does not pretend to connect studio controls.
"""
import argparse
import base64
import gzip
import hashlib
import html
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def script(source):
    # JSON values may contain user lyrics or titles, including HTML end tags.
    return source.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def build_player(bundle, track, motion, audio, output, panel_max_bytes=1_000_000):
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
    # Visualize's documented 1 MB fragment budget includes embedded media.
    # Compress the complete original motion data without dropping analysis frames.
    motion_gzip = gzip.compress(json.dumps(motion,separators=(',',':')).encode(),mtime=0)
    payload = {'track': track, 'motionGzip': base64.b64encode(motion_gzip).decode(),
               'receipt': receipt, 'preview': False, 'audioMime': 'audio/wav',
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
<footer><label><input id="loop" type="checkbox"> Loop</label><a id="download" download="riff-recording.wav">Download WAV</a><label id="full-file-label" hidden>Open full WAV<input id="full-file" type="file" accept="audio/wav,.wav"></label><span id="status" role="status">Loading recording…</span></footer>
<p id="mode" style="font-size:12px;margin-top:18px">This saved recording plays inside this panel. Ask Riff in Chat to compose, manage the library or change LoRAs.</p>
<details><summary>Recording receipt</summary><pre id="receipt"></pre></details></main>
<script id="riff-player-data" type="application/json">__DATA__</script>
<script>__ARTWORK__
const settledMotion = new WeakMap();
__INTERPOLATION__
async function initialize(){
const data=JSON.parse(document.getElementById('riff-player-data').textContent);
const unpacked=new Blob([Uint8Array.from(atob(data.motionGzip),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('gzip'));
const motion=JSON.parse(await new Response(unpacked).text());
const audio=document.getElementById('audio'),canvas=document.getElementById('visualizer');
const raw=Uint8Array.from(atob(data.audio),c=>c.charCodeAt(0));
let url=URL.createObjectURL(new Blob([raw],{type:data.audioMime}));
audio.src=url;document.getElementById('download').href=url;
if(data.preview){
  document.getElementById('full-file-label').hidden=false;
  document.getElementById('mode').textContent='Embedded MP3 preview · The full original WAV is saved separately in Library. Download it, then choose Open full WAV here for full-length playback and visualization.';
  document.getElementById('download').textContent='Download preview';document.getElementById('download').download='riff-preview.mp3';
}
document.getElementById('full-file').addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  const bytes=await file.arrayBuffer();
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(digest!==data.receipt.audio_sha256){document.getElementById('status').textContent='That file does not match this recording’s receipt.';return}
  audio.pause();URL.revokeObjectURL(url);url=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));audio.src=url;
  const download=document.getElementById('download');download.href=url;download.download='riff-recording.wav';download.textContent='Download WAV';
  document.getElementById('mode').textContent='Full original WAV · SHA-256 verified against the recording receipt. Audio stays in this browser panel.';
});
document.getElementById('receipt').textContent=JSON.stringify(data.receipt,null,2);
document.getElementById('loop').addEventListener('change',e=>audio.loop=e.target.checked);
const reduced=matchMedia('(prefers-reduced-motion: reduce)');let frame=null;
function draw(){
  frame=null;const r=canvas.getBoundingClientRect(),scale=devicePixelRatio||1;
  canvas.width=Math.round(r.width*scale);canvas.height=Math.round(r.height*scale);
  drawSeedArtwork(canvas.getContext('2d'),canvas.width,canvas.height,data.track.recipe?.seed??data.track.id,
    audio.currentTime,motionAt(motion,audio.currentTime),RiffArtwork.defaults);
  if(!audio.paused&&!audio.ended&&!reduced.matches&&!document.hidden)frame=requestAnimationFrame(draw);
}
function refresh(){if(frame!==null)cancelAnimationFrame(frame);draw()}
for(const event of ['play','pause','seeked','loadedmetadata','ended'])audio.addEventListener(event,refresh);
audio.addEventListener('loadedmetadata',()=>document.getElementById('status').textContent=audio.duration.toFixed(3)+' seconds');
audio.addEventListener('error',()=>document.getElementById('status').textContent='Playback failed: '+(audio.error?.message||'audio decode error'));
document.addEventListener('visibilitychange',refresh);addEventListener('resize',refresh);reduced.addEventListener('change',refresh);
draw();
}
initialize().catch(error=>document.getElementById('status').textContent='Player failed: '+error.message);
</script></html>'''
    # A single pass prevents user text resembling a token from being expanded.
    def render():
        values = {'__ARTWORK__': artwork, '__INTERPOLATION__': interpolation,
                  '__TITLE__': title, '__DATA__': script(json.dumps(payload, ensure_ascii=False))}
        return re.sub('|'.join(values), lambda match: values[match[0]], page)
    result = render()
    if len(result.encode()) > panel_max_bytes:
        payload.update(audio='',preview=True,audioMime='audio/mpeg')
        # Base64 expands every three bytes to four. Reserve exactly the remaining
        # fragment budget; a CBR preview's duration follows from that capacity.
        budget = (panel_max_bytes-len(render().encode()))//4*3
        bitrate = 128_000
        seconds = min(measured['duration'],budget/(bitrate/8))
        with tempfile.TemporaryDirectory() as tmp:
            source,target=Path(tmp)/'recording.wav',Path(tmp)/'preview.mp3'
            source.write_bytes(audio)
            while seconds > 0:
                subprocess.run([str(bundle/'runtime/media/ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y',
                    '-i',str(source),'-t',str(seconds),'-c:a','libmp3lame','-b:a',str(bitrate),'-ar','48000',str(target)],
                    check=True,capture_output=True,env={**os.environ,'LD_LIBRARY_PATH':str(bundle/'runtime/lib')})
                preview=target.read_bytes()
                if len(preview)<=budget:
                    payload['audio']=base64.b64encode(preview).decode()
                    receipt.update(preview_sha256=hashlib.sha256(preview).hexdigest(),preview_bytes=len(preview))
                    result=render()
                    if len(result.encode())<=panel_max_bytes:break
                    # Receipt fields added above also count against the budget.
                    budget -= (len(result.encode())-panel_max_bytes+3)//4*3
                # MP3 frames at 48 kHz contain 1152 samples. Drop the actual
                # overflow plus one encoder frame, not a guessed song limit.
                seconds -= max(0,len(preview)-budget)/(bitrate/8)+1152/48000
            else:
                raise ValueError('The original visualization exceeds this HTML panel budget. Export the WAV and HTML separately or use the connected studio.')
    if len(result.encode())>panel_max_bytes:
        raise ValueError('Recording player exceeds the configured host HTML budget.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result)
    return {**receipt, 'preview':payload['preview'],'html': str(output), 'html_bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.cwd()/'riff-workspace')
    parser.add_argument('--track-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--panel-max-bytes',type=int,default=1_000_000,help='Host HTML fragment budget; Visualize documents 1 MB')
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
        print(json.dumps(build_player(bundle, track, motion, bytes(audio), args.output.resolve(),args.panel_max_bytes)))


if __name__ == '__main__':
    main()
