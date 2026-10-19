/* A protocol host fixture, not a Riff API mock. tools/call reaches real stdio MCP. */
const { spawn } = require('node:child_process');
const { createServer } = require('node:http');
const { mkdtemp, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { once } = require('node:events');

const ROOT = path.resolve(__dirname, '../../../..');
const PLUGIN = path.join(ROOT, 'plugins/riff-chatgpt');
const PYTHON = process.env.RIFF_PYTHON || 'python3';

async function firstJSON(child, diagnostics) {
  return new Promise((resolve, reject) => {
    let data = '';
    const timer = setTimeout(() => reject(new Error('The upstream fixture did not start: ' + diagnostics())), 20000);
    const onData = chunk => {
      data += chunk;
      if (!data.includes('\n')) return;
      clearTimeout(timer);
      child.stdout.removeListener('data', onData);
      try { resolve(JSON.parse(data.split('\n')[0])); } catch (error) { reject(error); }
    };
    child.stdout.on('data', onData);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`Upstream exited ${code}: ${diagnostics()}`)); });
  });
}

async function stop(child) {
  if (!child || child.exitCode !== null) return;
  child.stdin.end();
  let timer;
  await Promise.race([once(child, 'exit'), new Promise(resolve => { timer = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 5000); })]);
  clearTimeout(timer);
}

async function startHost() {
  const workspace = await mkdtemp(path.join(tmpdir(), 'riff-mcp-browser-'));
  let upstreamLog = '', mcpLog = '', upstream, mcp, server, nextId = 1;
  const pending = new Map();
  const cleanup = async () => { if (server) await new Promise(resolve => server.close(resolve)); await stop(mcp); await stop(upstream); await rm(workspace, { recursive: true, force: true }); };
  try {
    mcp = spawn(PYTHON, ['-u', path.join(__dirname, 'mcp_fixture.py'),
      '--workspace', workspace, '--ui-file', path.join(PLUGIN, 'dist/studio.html')], { cwd: ROOT });
    mcp.stderr.on('data', data => mcpLog += data);
    const fixture = await firstJSON(mcp, () => mcpLog);
    let stdout = '';
    mcp.stdout.on('data', chunk => {
      stdout += chunk;
      for (let i; (i = stdout.indexOf('\n')) >= 0;) {
        const line = stdout.slice(0, i); stdout = stdout.slice(i + 1);
        if (!line.trim()) continue;
        let message; try { message = JSON.parse(line); } catch { continue; }
        const call = pending.get(message.id); if (!call) continue;
        pending.delete(message.id); clearTimeout(call.timer);
        if (message.error) call.reject(new Error(message.error.message)); else call.resolve(message.result);
      }
    });
    mcp.on('exit', code => {
      for (const call of pending.values()) { clearTimeout(call.timer); call.reject(new Error(`MCP exited ${code}: ${mcpLog}`)); }
      pending.clear();
    });
    const rpc = (method, params = {}) => new Promise((resolve, reject) => {
      const id = nextId++, timer = setTimeout(() => { pending.delete(id); reject(new Error(`MCP timeout: ${method}: ${mcpLog}`)); }, 120000);
      pending.set(id, { resolve, reject, timer });
      mcp.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
    await rpc('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'Riff browser acceptance host', version: '1' } });
    const tools = (await rpc('tools/list')).tools;
    const resources = (await rpc('resources/list')).resources;
    const resource = (await rpc('resources/read', { uri: resources[0].uri })).contents[0];
    const entry = await rpc('tools/call', { name: 'riff_open_studio', arguments: {} });
    if (entry.isError) throw new Error(JSON.stringify(entry));
    const configuration = JSON.stringify({ html: resource.text, entry, trackId: fixture.track_id }).replace(/</g, '\\u003c');
    const hostHTML = `<!doctype html><html><head><meta charset="utf-8"><title>Riff MCP Apps acceptance host</title><style>html,body{margin:0;background:#eee}iframe{border:0;width:100%;height:1200px;display:block}</style></head><body><script>
      const config=${configuration};
      window.hostTrace=[];window.hostDownloads=[];window.hostMessages=[];window.hostContexts=[];window.hostLinks=[];
      const frame=document.createElement('iframe');frame.name='riff-studio';frame.title='Riff studio';
      frame.setAttribute('sandbox','allow-scripts allow-forms allow-modals');frame.setAttribute('allow','autoplay; clipboard-write');
      window.sendRiff=(method,params,id)=>frame.contentWindow.postMessage({jsonrpc:'2.0',method,params,...(id===undefined?{}:{id})},'*');
      window.addEventListener('message',async event=>{
        if(event.source!==frame.contentWindow||event.data?.jsonrpc!=='2.0')return;
        const m=event.data;if(m.method)hostTrace.push({method:m.method,name:m.params?.name,path:m.params?.arguments?.path,offset:m.params?.arguments?.offset,final:m.params?.arguments?.final});
        if(!Object.hasOwn(m,'id'))return;
        if(!m.method){window.lastHostResponse=m;return;}
        let result={};
        try{
          if(m.method==='ui/initialize')result={protocolVersion:'2026-01-26',hostInfo:{name:'Riff test host',version:'1'},hostCapabilities:{downloadFile:{},updateModelContext:{},openLinks:{},message:{}},hostContext:{displayMode:'inline',availableDisplayModes:['inline','fullscreen'],'openai/deepLink':{url:'/?recording='+config.trackId}}};
          else if(m.method==='tools/call'){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(m.params)});result=await r.json();}
          else if(m.method==='ui/download-file'){if(window.denyDownload)result={isError:true};else hostDownloads.push(m.params.contents[0].resource);}
          else if(m.method==='ui/update-model-context')hostContexts.push(m.params);
          else if(m.method==='ui/message'){if(window.denyMessage)result={isError:true};else hostMessages.push(m.params);}
          else if(m.method==='ui/open-link')hostLinks.push(m.params.url);
          else if(m.method==='ui/request-display-mode'){result={mode:m.params.mode};window.sendRiff('ui/notifications/host-context-changed',{displayMode:m.params.mode});}
          else if(m.method!=='ui/notifications/size-changed')throw new Error('Unsupported host method '+m.method);
          frame.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,result},'*');
          if(m.method==='ui/initialize')setTimeout(()=>window.sendRiff('ui/notifications/tool-result',config.entry),0);
        }catch(error){frame.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,error:{code:-32603,message:error.message}},'*');}
      });
      const csp="default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; worker-src blob:; connect-src 'none'; font-src data:; form-action 'none'";
      frame.srcdoc=config.html.replace('<head>','<head><meta http-equiv="Content-Security-Policy" content="'+csp+'">');document.body.append(frame);
    </script></body></html>`;
    server = createServer(async (req, res) => {
      if (req.url === '/rpc' && req.method === 'POST') {
        let text = '';
        try {
          for await (const chunk of req) { text += chunk; if (text.length > 3 * 1024 * 1024) throw new Error('Host request is too large'); }
          const params = JSON.parse(text); const result = await rpc('tools/call', params);
          res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result));
        } catch (error) { res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ isError: true, content: [{ type: 'text', text: error.message }] })); }
      } else { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(hostHTML); }
    });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    return { url: `http://127.0.0.1:${server.address().port}`, fixture, tools, resource, workspace, rpc,
      diagnostics: () => ({ upstream: upstreamLog, mcp: mcpLog }), close: cleanup };
  } catch (error) { await cleanup(); throw error; }
}
module.exports = { startHost, ROOT, PLUGIN };
