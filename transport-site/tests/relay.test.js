import test from 'node:test';
import assert from 'node:assert/strict';
import {Relay,createWorker} from '../worker/relay.js';

// Strongly consistent R2 operations, including compare-and-swap etags.
class Bucket {
  constructor(){this.data=new Map();this.serial=0;}
  async get(key){const row=this.data.get(key);return row?{etag:row.etag,json:async()=>JSON.parse(row.raw)}:null;}
  async put(key,raw,options={}){
    const prev=this.data.get(key),cond=options.onlyIf;
    if(cond?.etagMatches&&prev?.etag!==cond.etagMatches)return null;
    if(cond?.etagDoesNotMatch==='*'&&prev)return null;
    const row={raw,etag:String(++this.serial)};this.data.set(key,row);return row;
  }
  async delete(keys){for(const key of Array.isArray(keys)?keys:[keys])this.data.delete(key);}
  async list({prefix,limit=1000}){const keys=[...this.data.keys()].filter(k=>k.startsWith(prefix)).sort();return {objects:keys.slice(0,limit).map(key=>({key})),truncated:false};}
}
const tools=[{name:'riff_get_draft',inputSchema:{type:'object',properties:{}}},{name:'riff_save_draft',inputSchema:{type:'object'}}];
const resource={uri:'ui://riff/test',mimeType:'text/html;profile=mcp-app',read:async()=>({text:'<main>Original studio</main>'})};
const env=()=>({BUCKET:new Bucket()});
const request=(path,body,headers={})=>new Request('https://riff.example'+path,{method:'POST',headers:{'content-type':'application/json',...headers},body:JSON.stringify(body)});

test('one-use pairing, racing claims and owner isolation',async()=>{
  const r=new Relay(new Bucket(),tools),a=await r.pair('alice'),b=await r.pair('bob');
  assert.notEqual(a.session_id,b.session_id);
  await assert.rejects(r.pair('alice'),/already exists/);
  await assert.rejects(r.claim(a.session_id,b.enrollment_token),/invalid/);
  const results=await Promise.allSettled([r.claim(a.session_id,a.enrollment_token),r.claim(a.session_id,a.enrollment_token)]);
  assert.equal(results.filter(x=>x.status==='fulfilled').length,1);
  const key=results.find(x=>x.status==='fulfilled').value.worker_token;
  await assert.rejects(r.authenticate(b.session_id,key),/Invalid worker/);
  await r.poll(a.session_id,key);
  await r.disconnect('alice');
  await assert.rejects(r.poll(a.session_id,key),/expired|disconnected/);
  assert.equal((await r.ownerSession('bob')).value.id,b.session_id);
});

test('real MCP envelope transports app-only media privately and delivers a mutation once',async()=>{
  const e=env(),worker=createWorker(tools,resource);
  let mid=0;
  const mcp=async(name,args={},identity='alice')=>(await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:++mid,method:'tools/call',params:{name,arguments:args}},{'oai-authenticated-user-id':identity}),e)).json();
  const pair=(await mcp('riff_connect_runtime')).result.structuredContent;
  const claim=await (await worker.fetch(request('/runtime/claim',pair),e)).json();
  const headers={authorization:'Bearer '+claim.worker_token};
  const poll=async()=> (await worker.fetch(request('/runtime/poll',{session_id:pair.session_id},headers),e)).json();
  await poll();
  const waiting=mcp('riff_save_draft',{expected_revision:0,recipe:{title:'Actual draft'}});
  let command;for(let i=0;i<20&&!command;i++){await new Promise(r=>setTimeout(r,5));command=(await poll()).command;}
  assert.equal(command.tool,'riff_save_draft');assert.equal(command.arguments.recipe.title,'Actual draft');
  assert.equal((await poll()).command,null,'claimed mutations are never requeued');
  const result={content:[],structuredContent:{status:200,body:{revision:1}},_meta:{base64:'AAEC',receipt:{sha256:'original'}}};
  const completed=await worker.fetch(request('/runtime/complete',{session_id:pair.session_id,request_id:command.request_id,claim:command.claim,result},headers),e);
  assert.equal(completed.status,200);
  const actual=(await waiting).result;assert.deepEqual(actual._meta,result._meta);assert.equal(actual.structuredContent.body.revision,1);
  assert.equal((await worker.fetch(request('/runtime/complete',{session_id:pair.session_id,request_id:command.request_id,claim:command.claim,result},headers),e)).status,409);
  assert.equal((await mcp('riff_runtime_status',{},'bob')).result.structuredContent.paired,false);
  assert.equal((await mcp('riff_save_draft',{},'bob')).result.isError,true);
});

test('older requests run before new requests regardless of UUID ordering',async()=>{
  const r=new Relay(new Bucket(),tools,()=>1000000),pair=await r.pair('alice');
  const credential=(await r.claim(pair.session_id,pair.enrollment_token)).worker_token;
  const prefix='requests/'+pair.session_id+'/';
  await r.put(prefix+'000-newer',{id:'000-newer',state:'queued',deadline:1045000,tool:'riff_get_draft',arguments:{}});
  await r.put(prefix+'fff-older',{id:'fff-older',state:'queued',deadline:1040000,tool:'riff_get_draft',arguments:{}});
  assert.equal((await r.poll(pair.session_id,credential)).request_id,'fff-older');
  assert.equal((await r.poll(pair.session_id,credential)).request_id,'000-newer');
  assert.equal(await r.poll(pair.session_id,credential),null);
});

test('offline and expired workers never receive new work',async()=>{
  let at=1000000;const bucket=new Bucket(),r=new Relay(bucket,tools,()=>at),pair=await r.pair('alice');
  const credential=(await r.claim(pair.session_id,pair.enrollment_token)).worker_token;
  await assert.rejects(r.call('alice','riff_save_draft',{}),/offline/);
  assert.equal((await bucket.list({prefix:'requests/'})).objects.length,0);
  await r.poll(pair.session_id,credential);at+=21000;
  await assert.rejects(r.call('alice','riff_save_draft',{}),/offline/);
  at+=3600000;await assert.rejects(r.poll(pair.session_id,credential),/expired/);
});

test('MCP commands require trusted caller identity; static resources support host scanning',async()=>{
  const e=env(),worker=createWorker(tools,resource);
  const send=async(method,params={},headers={})=>worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method,params},headers),e);
  assert.equal((await send('resources/read',{uri:resource.uri})).status,200);
  assert.equal((await send('tools/call',{name:'riff_connect_runtime',arguments:{}})).status,401);
  const listed=await (await send('tools/list')).json();assert.equal(listed.result.tools.length,5);
  const read=await (await send('resources/read',{uri:resource.uri},{'oai-authenticated-user-id':'alice'})).json();
  assert.equal(read.result.contents[0].text,'<main>Original studio</main>');
  for(const method of ['resources/list','resources/templates/list','resources/read']) {
    const response=await (await send(method,{uri:resource.uri})).json();
    assert.equal(response.result.resultType,'complete');
    assert.equal(response.result.ttlMs,0);
    assert.equal(response.result.cacheScope,'private');
  }
});
