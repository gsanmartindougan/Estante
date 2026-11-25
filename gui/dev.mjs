import {createServer} from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import {watch} from 'node:fs';
import {resolve,extname,sep} from 'node:path';
const root=process.cwd();
const clients=new Set();
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'};
export function safePath(url){const path=resolve(root,'.'+decodeURIComponent(new URL(url,'http://localhost').pathname));return path.startsWith(root+sep)||path===root?path:null;}
const server=createServer(async(req,res)=>{
 if(req.url==='/__reload'){res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'});res.write(': connected\n\n');clients.add(res);req.on('close',()=>clients.delete(res));return;}
 try{
  let file=safePath(req.url);
  if(!file){res.writeHead(403);res.end();return;}
  if(file===root)file=resolve(root,'index.html');
  if(!(await stat(file)).isFile()){res.writeHead(404);res.end();return;}
  let body=await readFile(file);
  const type=types[extname(file)]||'application/octet-stream';
  if(type==='text/html')body=body.toString().replace('</body>','<script>new EventSource("/__reload").onmessage=()=>location.reload();</script></body>');
  res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-cache'});res.end(body);
 }catch{res.writeHead(404);res.end('Not found');}
});
if(process.argv[1]===resolve(root,'dev.mjs')){
 let timer;watch(root,(_,file)=>{if(!file||!['.html','.css','.js'].includes(extname(file)))return;clearTimeout(timer);timer=setTimeout(()=>{for(const client of clients)client.write('data: reload\n\n');},150);});
 server.listen(Number(process.env.PORT)||5173,'0.0.0.0',()=>console.log(`Local: http://localhost:${server.address().port}`));
}
