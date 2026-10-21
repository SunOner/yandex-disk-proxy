const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'dist/requests.html'),'utf8');
const code=fs.readFileSync(path.join(root,'dist/requests.js'),'utf8');
const elements=new Map(),requests=[],rendered=[], languageListeners=[];
const translations=require('./i18n_stub.cjs')();
translations.onChange=fn=>languageListeners.push(fn);
function element(){return {options:[],value:'',checked:false,disabled:false,hidden:false,textContent:'',children:[],classList:{toggle(){}},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(){},querySelectorAll(){return [];}};}
function get(id){assert.ok(html.includes(`id="${id}"`),id);if(!elements.has(id))elements.set(id,element());return elements.get(id);}
const context=vm.createContext({
  I18n: translations,console,Intl,URLSearchParams,AbortSignal,queueMicrotask,Toasts:{show(){},problem(){}},location:{hash:''},setInterval(){},setTimeout(){},window:{addEventListener(){}},document:{getElementById:get,createElement:element},rendered,
fetch(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));}});
const state={nonce:'local-test',session:{phase:'active',ca_trusted:false},tls:{client:{ok:true},upstream:{ok:true}}};
const metadata={labels:{other:'Другая операция',download:'Скачивание'},anomaly_labels:{unknown:'Неизвестная операция'},since:1,totals:{http:12},operations:[],endpoints:[],retained:2,evicted:0,active:0};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function respond(request,value){request.resolve({ok:true,json:async()=>value});}
async function respondPair(){respond(requests.shift(),state);respond(requests.shift(),metadata);await tick();}
async function main(){
vm.runInContext(fs.readFileSync(path.join(root,'dist/list-motion.js'),'utf8'),context);
vm.runInContext(code,context);vm.runInContext('render = rows => rendered.push(rows)',context);
vm.runInContext('$("operation").value="other"; refresh()',context);
await respondPair();
const old=requests.shift();assert.equal(new URLSearchParams(old.url.split('?')[1]).get('operation'),'');respond(old,{rows:['stale'],total:1,offset:0});await tick();
assert.equal(rendered.length,0,'Stale operation filter must not replace current results');
await respondPair();const fresh=requests.shift();assert.equal(new URLSearchParams(fresh.url.split('?')[1]).get('operation'),'other');respond(fresh,{rows:['current'],total:1,offset:0});await tick();
assert.equal(rendered[0][0],'current');
vm.runInContext('selected="private"; $("mask").checked=false; details()',context);
respond(requests.shift(),{id:'private',request_headers:[['Authorization','SECRET']]});await tick();
assert.ok(get('original').textContent.includes('SECRET'));
vm.runInContext('$("mask").checked=true; details()',context);
assert.equal(get('original').textContent,'');
languageListeners.forEach(fn=>fn());
assert.equal(get('original').textContent,'','Locale changes cannot restore raw headers while a masked request is pending');
respond(requests.shift(),{id:'private',request_headers:[['Authorization','[hidden]']]});await tick();
languageListeners.forEach(fn=>fn());
assert.ok(!get('original').textContent.includes('SECRET'));
vm.runInContext('selected="different"; details()',context);
languageListeners.forEach(fn=>fn());
assert.equal(get('original').textContent,'','Locale changes cannot restore headers from a previous selection');
respond(requests.shift(),{id:'different'});await tick();
vm.runInContext('switchView("summary")',context);await respondPair();
assert.equal(get('summary').hidden,false);assert.equal(get('workspace').hidden,true);assert.equal(get('mask-label').hidden,true);assert.equal(get('summary-total').textContent,'12');
vm.runInContext('refresh()',context);requests.shift().reject(Error('offline'));await tick();assert.equal(get('export').disabled,true);
console.log('Journal UI: stale filters rejected, summary rendered, originals hidden in summary, export disabled offline.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
