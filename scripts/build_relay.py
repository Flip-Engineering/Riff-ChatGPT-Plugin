#!/usr/bin/env python3
"""Derive the hosted transport's tool/resource contract from pinned Riff code."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'plugins/riff-chatgpt'
sys.path.insert(0,str(PLUGIN/'server'))
from adapter import TOOLS, UI_URI, MIME

# Keep the documented ChatGPT compatibility alias for resource scanners that
# do not yet resolve the standard ui.resourceUri during connection refresh.
TOOLS=json.loads(json.dumps(TOOLS))
for item in TOOLS:
    if item.get('_meta',{}).get('ui',{}).get('resourceUri'):
        item['_meta']['openai/outputTemplate']=UI_URI

html=(PLUGIN/'dist/studio.html').read_bytes()
compressed=base64.b64encode(gzip.compress(html,mtime=0)).decode()
source=(ROOT/'transport-site/worker/relay.js').read_text().replace('export class Relay','class Relay').replace('export function createWorker','function createWorker')
source+='\nconst contracts='+json.dumps(TOOLS,separators=(',',':'))+';\n'
source+='const studio='+json.dumps(compressed)+';\n'
source+='''const resource={uri:URI,mimeType:MIME,async read(){
 const bytes=Uint8Array.from(atob(studio),c=>c.charCodeAt(0));
 const text=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
 return {uri:URI,mimeType:MIME,text,_meta:{ui:{prefersBorder:false,csp:{connectDomains:[],resourceDomains:["blob:","data:"]}},'openai/ui':{preferredDisplayMode:'fullscreen',availableDisplayModes:['inline','fullscreen']}}};
}};
export default createWorker(contracts,resource);
'''.replace('URI',json.dumps(UI_URI)).replace('MIME',json.dumps(MIME))
(ROOT/'transport-site/worker/index.js').write_text(source)
receipt={'studio_sha256':hashlib.sha256(html).hexdigest(),'tools':len(TOOLS),'resource_uri':UI_URI,'source':'plugins/riff-chatgpt/dist/studio.html','native_runtime':'user ChatGPT Chat cloud workspace'}
(ROOT/'transport-site/contract-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
