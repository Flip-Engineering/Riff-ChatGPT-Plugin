/* Transient MCP transport. Native code and project files remain in Chat. */
const MAX_BODY = 1600000;
const SESSION_MS = 60 * 60 * 1000;
const FRESH_MS = 20000;
const CALL_MS = 45000;
const ID = /^[a-f0-9]{32}$/;
const now = () => Date.now();
const uuid = () => crypto.randomUUID().replaceAll('-', '');
const token = () => uuid() + uuid();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const encode = value => JSON.stringify(value);
const error = (message, status=400) => Object.assign(new Error(message), {status});
const sha = async text => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), x=>x.toString(16).padStart(2,'0')).join('');
const json = (value, status=200) => new Response(encode(value), {status, headers:{'content-type':'application/json', 'cache-control':'private, no-store'}});
const textResult = (body, isError=false) => ({content:[{type:'text',text:encode(body)}],structuredContent:body,isError});

export class Relay {
  constructor(bucket, contracts, clock=now) {this.bucket=bucket;this.contracts=contracts;this.clock=clock;}
  async get(key) {const obj=await this.bucket.get(key);return obj?{value:await obj.json(),etag:obj.etag}:null;}
  async put(key, value, etag) {return this.bucket.put(key,encode(value),etag?{onlyIf:{etagMatches:etag}}:{onlyIf:{etagDoesNotMatch:'*'}});}
  ownerKey(owner) {return 'owners/'+owner;}
  async ownerSession(owner) {
    const map=await this.get(this.ownerKey(owner));
    if(!map)return null;
    const session=await this.get('sessions/'+map.value.id);
    return session&&session.value.owner===owner&&session.value.expires>this.clock()?session:null;
  }
  async pair(owner) {
    const key=this.ownerKey(owner),previous=await this.get(key);
    if(await this.ownerSession(owner))throw error('A runtime pairing already exists. Disconnect it explicitly before replacing it.',409);
    const id=uuid(),enrollment=token(),expires=this.clock()+SESSION_MS;
    await this.put('sessions/'+id,{id,owner,expires,enrollmentHash:await sha(enrollment),workerHash:null,claimed:false});
    if(!await this.put(key,{id},previous?.etag)){await this.bucket.delete('sessions/'+id);throw error('Another runtime pairing won the connection race.',409);}
    // The worker capability is revealed only once, after enrollment succeeds.
    return {session_id:id,enrollment_token:enrollment,enrollment_expires:this.clock()+300000,expires};
  }
  async current(id) {
    if(!ID.test(id||''))throw error('Invalid session.',401);
    const session=await this.get('sessions/'+id);
    if(!session||session.value.expires<=this.clock())throw error('Runtime session expired.',401);
    const map=await this.get(this.ownerKey(session.value.owner));
    if(map?.value.id!==id)throw error('Runtime session was disconnected.',401);
    return session;
  }
  async claim(id,enrollment) {
    const session=await this.current(id),s=session.value;
    if(s.claimed||s.expires-SESSION_MS+300000<this.clock()||typeof enrollment!=='string'||await sha(enrollment)!==s.enrollmentHash)throw error('Enrollment is invalid, expired or already used.',401);
    const worker=token();
    const next={...s,claimed:true,enrollmentHash:null,workerHash:await sha(worker)};
    if(!await this.put('sessions/'+id,next,session.etag))throw error('Enrollment was already claimed.',409);
    return {worker_token:worker,expires:s.expires};
  }
  async authenticate(id,credential) {
    const session=await this.current(id);
    if(!session.value.claimed||typeof credential!=='string'||await sha(credential)!==session.value.workerHash)throw error('Invalid worker credential.',401);
    return session.value;
  }
  async poll(id,credential) {
    await this.authenticate(id,credential);
    await this.bucket.put('heartbeat/'+id,encode({at:this.clock()}));
    const items=await this.bucket.list({prefix:'requests/'+id+'/',limit:32});
    // R2 lists UUID keys lexically, not by submission time. Repeated UI polls
    // must not starve an older library/media command with a later UUID.
    const records=await Promise.all(items.objects.map(async item=>({item,record:await this.get(item.key)})));
    records.sort((a,b)=>(a.record?.value.deadline||0)-(b.record?.value.deadline||0));
    for(const {item,record} of records) {
      if(record&&record.value.deadline<this.clock()){await this.bucket.delete(item.key);continue;}
      if(record?.value.state!=='queued')continue;
      const r=record.value;
      if(r.deadline<this.clock()){await this.put(item.key,{...r,state:'expired'},record.etag);continue;}
      const claim=token();
      if(await this.put(item.key,{...r,state:'claimed',claimHash:await sha(claim)},record.etag))return {request_id:r.id,claim,tool:r.tool,arguments:r.arguments};
    }
    return null;
  }
  async complete(id,credential,requestId,claim,result) {
    await this.authenticate(id,credential);
    if(!ID.test(requestId||'')||!result||typeof result!=='object'||Array.isArray(result)||encode(result).length>MAX_BODY)throw error('Invalid command response.');
    const key='requests/'+id+'/'+requestId,record=await this.get(key);
    if(!record||record.value.state!=='claimed'||typeof claim!=='string'||await sha(claim)!==record.value.claimHash)throw error('Command result is late, duplicate or unauthorized.',409);
    if(record.value.deadline<this.clock())throw error('Command deadline elapsed; inspect native state before retrying.',409);
    if(!await this.put(key,{id:requestId,state:'complete',deadline:record.value.deadline,result},record.etag))throw error('Command result raced with cancellation.',409);
    return {accepted:true};
  }
  async call(owner,name,args) {
    if(!this.contracts.some(t=>t.name===name))throw error('Unknown Riff tool.');
    const session=await this.ownerSession(owner);
    if(!session?.value.claimed)throw error('Connect this conversation’s Riff cloud runtime first.',503);
    const id=session.value.id,hb=await this.get('heartbeat/'+id);
    if(!hb||this.clock()-hb.value.at>FRESH_MS)throw error('The paired cloud runtime is offline. Restart its retained relay session; no command was sent.',503);
    const queued=await this.bucket.list({prefix:'requests/'+id+'/',limit:32});
    if(queued.objects.length>=32)throw error('This runtime already has 32 outstanding requests. Inspect them before sending more.',429);
    const requestId=uuid(),key='requests/'+id+'/'+requestId,deadline=this.clock()+CALL_MS;
    await this.put(key,{id:requestId,state:'queued',tool:name,arguments:args,deadline});
    while(this.clock()<deadline) {
      const r=await this.get(key);
      if(r?.value.state==='complete'){await this.bucket.delete(key);return r.value.result;}
      if(!await this.ownerSession(owner))throw error('Runtime disconnected; inspect native state before retrying.',503);
      await pause(200);
    }
    const r=await this.get(key);
    if(r?.value.state==='complete'){await this.bucket.delete(key);return r.value.result;}
    if(r)await this.put(key,{id:requestId,state:'expired',deadline},r.etag);
    throw error('Runtime command '+requestId+' timed out. Its outcome may be uncertain; inspect native state before retrying. It will not be replayed.',504);
  }
  async disconnect(owner) {
    const key=this.ownerKey(owner),map=await this.get(key);
    if(!map)return {disconnected:true};
    await this.bucket.delete(key);
    const id=map.value.id;
    await this.bucket.delete(['sessions/'+id,'heartbeat/'+id]);
    let cursor;
    do {const list=await this.bucket.list({prefix:'requests/'+id+'/',limit:1000,cursor});if(list.objects.length)await this.bucket.delete(list.objects.map(x=>x.key));cursor=list.truncated?list.cursor:null;}while(cursor);
    return {disconnected:true};
  }
  async reapExpired() {
    const marker=await this.get('maintenance/cursor');
    if(marker&&this.clock()-marker.value.at<60000)return;
    const list=await this.bucket.list({prefix:'sessions/',limit:32,...(marker?.value.cursor?{cursor:marker.value.cursor}:{})});
    for(const item of list.objects) {
      const record=await this.get(item.key);
      if(!record||record.value.expires>this.clock())continue;
      const id=record.value.id;
      let cursor;
      do {const requests=await this.bucket.list({prefix:'requests/'+id+'/',limit:1000,cursor});if(requests.objects.length)await this.bucket.delete(requests.objects.map(x=>x.key));cursor=requests.truncated?requests.cursor:null;}while(cursor);
      await this.bucket.delete(['sessions/'+id,'heartbeat/'+id]);
    }
    await this.bucket.put('maintenance/cursor',encode({at:this.clock(),cursor:list.truncated?list.cursor:null}));
  }
}

export function createWorker(contracts,resource) {
  const connectionTools=[
    {name:'riff_connect_runtime',description:'Create a one-use pairing for this user’s Riff runtime in Chat. Pass the returned enrollment to the bundled relay helper in a retained cloud execution session. Does not render music or run commands.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:false,destructiveHint:false,openWorldHint:false}},
    {name:'riff_disconnect_runtime',description:'Explicitly disconnect this user’s paired runtime and erase transient transport messages. Does not delete native library, drafts, LoRAs or scores.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:false,destructiveHint:true,openWorldHint:false}},
    {name:'riff_runtime_status',description:'Check this user’s pairing and runtime heartbeat without sending a native command.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:false}},
  ];
  return {async fetch(request,env,ctx) {
    try {
      const url=new URL(request.url),path=url.pathname;
      if(path==='/')return new Response('<!doctype html><title>Riff Studio Transport</title><h1>Riff Studio Transport</h1><p>Connects the Riff panel in ChatGPT Chat to your own cloud runtime. Music generation, library, LoRAs and scores remain in that runtime.</p><p>This transport stores only expiring pairing records and transient command messages. It does not host a music engine.</p>',{headers:{'content-type':'text/html; charset=utf-8','cache-control':'private, no-store'}});
      if(request.method!=='POST')return json({error:'Not found'},404);
      if(!env.BUCKET)throw error('Transport storage is unavailable.',503);
      if(Number(request.headers.get('content-length')||0)>MAX_BODY)throw error('Request exceeds transfer limit.',413);
      const reader=request.body?.getReader(),chunks=[];let length=0;
      if(!reader)throw error('A JSON body is required.');
      while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>MAX_BODY){await reader.cancel();throw error('Request exceeds transfer limit.',413);}chunks.push(value);}
      const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      const raw=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
      const body=JSON.parse(raw),relay=new Relay(env.BUCKET,contracts);
      if(ctx?.waitUntil)ctx.waitUntil(relay.reapExpired().catch(()=>{}));
      if(path.startsWith('/runtime/')) {
        const {session_id:id}=body;
        const credential=request.headers.get('authorization')?.replace(/^Bearer /,'');
        if(path==='/runtime/claim')return json(await relay.claim(id,body.enrollment_token));
        if(path==='/runtime/poll')return json({command:await relay.poll(id,credential)});
        if(path==='/runtime/complete')return json(await relay.complete(id,credential,body.request_id,body.claim,body.result));
        return json({error:'Not found'},404);
      }
      if(path!=='/mcp')return json({error:'Not found'},404);
      if(body?.jsonrpc!=='2.0'||typeof body.method!=='string')return json({error:'Invalid JSON-RPC'},400);
      if(!Object.hasOwn(body,'id'))return new Response(null,{status:202});
      const respond=result=>json({jsonrpc:'2.0',id:body.id,result:{...result,resultType:'complete',
        ...(['server/discover','tools/list','resources/list','resources/templates/list','resources/read'].includes(body.method)?{ttlMs:0,cacheScope:'private'}:{})}});
      if(body.method==='server/discover')return respond({supportedVersions:['2026-07-28'],capabilities:{tools:{},resources:{}},_meta:{'io.modelcontextprotocol/serverInfo':{name:'riff-cloud-transport',version:'0.4.0'}},ttlMs:0,cacheScope:'private'});
      if(body.method==='initialize')return respond({protocolVersion:'2025-11-25',capabilities:{tools:{},resources:{}},serverInfo:{name:'riff-cloud-transport',version:'0.4.0'}});
      if(body.method==='ping')return respond({});
      if(body.method==='tools/list')return respond({tools:[...connectionTools,...contracts],ttlMs:0,cacheScope:'private'});
      const p=body.params||{};
      if(body.method.startsWith('resources/'))console.info(JSON.stringify({event:'riff_resource_request',method:body.method,uri:p.uri||null}));
      // Static, identical studio source is safe for the host's resource scan.
      // User state and every runtime command still require caller identity.
      if(body.method==='resources/list')return respond({resources:[{uri:resource.uri,name:'Riff Studio',mimeType:resource.mimeType}]});
      if(body.method==='resources/templates/list')return respond({resourceTemplates:[]});
      if(body.method==='resources/read') {
        if(p.uri!==resource.uri)throw error('Unknown Riff resource.');
        const content=await resource.read();
        console.info(JSON.stringify({event:'riff_resource_served',uri:content.uri,mimeType:content.mimeType,length:content.text.length}));
        return respond({contents:[content]});
      }
      if(body.method!=='tools/call')return json({jsonrpc:'2.0',id:body.id,error:{code:-32601,message:'Unknown MCP method'}});
      const identity=request.headers.get('oai-authenticated-user-id');
      if(!identity)throw error('Authenticated ChatGPT user identity is required.',401);
      const owner=await sha(identity);
      try {
        if(!p.arguments||typeof p.arguments!=='object'||Array.isArray(p.arguments))throw error('Tool arguments must be an object.');
        if(connectionTools.some(t=>t.name===p.name)&&Object.keys(p.arguments).length)throw error('This tool accepts no arguments.');
        if(p.name==='riff_connect_runtime')return respond(textResult(await relay.pair(owner)));
        if(p.name==='riff_disconnect_runtime')return respond(textResult(await relay.disconnect(owner)));
        if(p.name==='riff_runtime_status') {
          const s=await relay.ownerSession(owner),hb=s?await relay.get('heartbeat/'+s.value.id):null;
          return respond(textResult({paired:!!s,online:!!hb&&relay.clock()-hb.value.at<FRESH_MS,expires:s?.value.expires||null}));
        }
        return respond(await relay.call(owner,p.name,p.arguments));
      }catch(e){return respond(textResult({error:e.message,status:e.status||400},true));}
    }catch(e){return json({error:e instanceof SyntaxError?'Invalid JSON.':e.message},e.status||400);}
  }};
}
