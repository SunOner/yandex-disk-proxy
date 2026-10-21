const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'dist/index.html'), 'utf8');
const code = fs.readFileSync(path.join(root, 'dist/app.js'), 'utf8');
const elements = new Map();
const requests = [];
const rendered = [];
function element(id) {
  assert.ok(html.includes(`id="${id}"`), `Removed element still used: ${id}`);
  if (!elements.has(id)) elements.set(id, {
    value:'', disabled:false, hidden:false, textContent:'', className:'',
    addEventListener(){}, replaceChildren(){},
  });
  return elements.get(id);
}
const context = vm.createContext({
  console, URLSearchParams, Intl, AbortSignal, queueMicrotask,
  setTimeout(){return 0;}, clearTimeout(){}, setInterval(){return 0;},
  document:{getElementById:element, querySelector(){return null;}, querySelectorAll(){return [];}, activeElement:null},
  fetch(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));},
  rendered,
});
const state = phase => ({session:{phase},mode:'defer',pending:1,pending_bytes:100,counts:{local:2},downloads:{count:1,bytes:10,since:'2026-01-01T00:00:00Z'},counters:{},root:'disk',events:[],nonce:'local-test'});
const tick = () => new Promise(resolve=>setImmediate(resolve));
function respond(request, value){request.resolve({ok:true,json:async()=>value});}
async function main() {
  vm.runInContext(code,context);
  vm.runInContext('renderRows = data => rendered.push(data.rows);',context);
  vm.runInContext("setFilter('errors')",context);
  respond(requests.shift(),state('idle'));
  await tick();
  const oldFiles=requests.shift();
  assert.equal(new URLSearchParams(oldFiles.url.split('?')[1]).get('status'),'pending');
  respond(oldFiles,{offset:0,total:1,rows:['old-pending-result']});
  await tick();
  assert.equal(rendered.length,0,'Old filter result must be ignored');
  respond(requests.shift(),state('idle'));
  await tick();
  const freshFiles=requests.shift();
  assert.equal(new URLSearchParams(freshFiles.url.split('?')[1]).get('status'),'errors');
  respond(freshFiles,{offset:0,total:1,rows:['current-error-result']});
  await tick();
  assert.equal(rendered.length,1);
  assert.equal(rendered[0][0],'current-error-result');
  vm.runInContext('refresh()',context);
  requests.shift().reject(new Error('offline'));
  await tick();
  assert.equal(element('session-title').textContent,'Нет связи с панелью');
  for(const id of ['start','stop','settings','mode','rescan']) assert.equal(element(id).disabled,true);
  vm.runInContext('refresh()',context);
  respond(requests.shift(),state('active'));
  await tick();
  respond(requests.shift(),{offset:0,total:0,rows:[]});
  await tick();
  assert.equal(element('session-title').textContent,'Прокси включён');
  assert.equal(element('stop').disabled,false);
  assert.equal(element('mode').disabled,false);
  vm.runInContext("sessionView({session:{phase:'active',ca_trusted:false},tls:{client:{ok:true},upstream:{ok:true}},mode:'defer'})",context);
  assert.equal(element('tls-warning').hidden,true,'A verified client TLS connection must not be shown as disconnected');
  vm.runInContext("sessionView({session:{phase:'active',ca_trusted:false},tls:{client:{ok:false}},mode:'defer'})",context);
  assert.equal(element('tls-warning').hidden,false);
  assert.equal(element('repair-ca').hidden,false);
  vm.runInContext("sessionView({session:{phase:'active'},mode:'defer',configured:true,inventory:{scanning:true}})",context);
  assert.equal(element('rescan').disabled,true);
  assert.equal(element('rescan').textContent,'Обновление списка…');
  vm.runInContext("sessionView({session:{phase:'active'},mode:'defer',configured:true,inventory:{scanning:false,updated_at:1792574000}})",context);
  assert.equal(element('rescan').disabled,false);
  console.log('UI: stale results rejected; offline controls disabled; reconnect recovered; removed elements unused.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
