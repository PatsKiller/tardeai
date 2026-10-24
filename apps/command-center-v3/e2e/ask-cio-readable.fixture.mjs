/** Actual header/MyQuestions, canonical root-generated copied-ledger responses, intercepted transport only. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
import {build} from 'esbuild'
import {chromium,expect} from '@playwright/test'
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const input=process.argv[2]||path.join(app,'e2e/fixtures/askCioReadable.fixture.json'),out=process.argv[3]
assert(out,'Explicit screenshot/receipt directory required');assert(fs.existsSync(input),'Root-generated canonical copied-ledger fixture required; no sample prose fallback')
const f=JSON.parse(fs.readFileSync(input,'utf8')),unwrap=value=>value?.data??value
const result=unwrap(f.ask_response),quick=unwrap(f.quick_thread).thread??unwrap(f.quick_thread),deep=unwrap(f.deep_thread).thread??unwrap(f.deep_thread)
assert.equal(result.thread_id,quick.thread_id);assert.equal(quick.thread_id,deep.thread_id)
const current=(thread)=>[...thread.turns.find(turn=>turn.ask_id===result.ask_id).answers].filter(a=>a.status!=='deep_pending').sort((a,b)=>b.version-a.version)[0]
assert.equal(result.answer_text,f.telegram_quick_text);assert.equal(current(deep).summary,f.telegram_deep_text)
assert(current(deep).version>current(quick).version,'Deep fixture must have a new durable answer version')
assert.equal(typeof f.question,'string');assert(f.clock&&f.list_quick&&f.list_deep)
const bundle=await build({metafile:true,stdin:{contents:`import React,{useEffect} from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Route,Routes,useNavigate}from'react-router-dom';import AskCioBar from'./src/components/AskCioBar';import MyQuestions from'./src/pages/MyQuestions';import'./src/styles/tokens.css';import'./src/index.css';function Fixture(){const navigate=useNavigate();useEffect(()=>{window.fixtureNavigate=navigate},[navigate]);return <><AskCioBar/><div style={{padding:20}}><Routes><Route path="/cio/questions" element={<MyQuestions/>}/><Route path="/cio/questions/:threadId" element={<MyQuestions/>}/><Route path="*" element={<div>Isolated host</div>}/></Routes></div></>};createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Fixture/></BrowserRouter>);`,loader:'tsx',sourcefile:'ask-cio-readable-fixture.tsx',resolveDir:app},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files=[...Object.keys(bundle.metafile.inputs).map(name=>path.resolve(app,name)).filter(file=>file.startsWith(path.join(app,'src')+path.sep)),input,fileURLToPath(import.meta.url),path.join(app,'package.json'),path.join(app,'package-lock.json')]
const hashes=Object.fromEntries(files.map(file=>[file,sha(file)])),source={head:execFileSync('git',['rev-parse','HEAD'],{cwd:app,encoding:'utf8'}).trim(),working_patch_sha256:crypto.createHash('sha256').update(execFileSync('git',['diff','HEAD'],{cwd:app})).digest('hex'),file_sha256:hashes}
const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script'),css=bundle.outputFiles.find(file=>file.path.endsWith('.css'))?.text||''
fs.mkdirSync(out,{recursive:true})
const browser=await chromium.launch({headless:true}),receipts=[]
try{
 for(const width of [1440,412])for(const mode of ['combined','header-only','wrong-identity']){
  const context=await browser.newContext({viewport:{width,height:1100}}),page=await context.newPage(),traffic={reads:[],posts:[],unexpected:[],external:[],errors:[],navigations:[]},geometries=[]
  let phase='quick',holdOther,otherRequested=false
  const otherReply=new Promise(resolve=>{holdOther=resolve})
  await page.clock.install({time:new Date(f.clock)})
  page.on('pageerror',e=>traffic.errors.push(String(e)))
  await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url())
   if(url.origin!=='http://ask-readable-fixture.test'){traffic.external.push(url.origin+url.pathname);return route.abort()}
   if(request.isNavigationRequest()){traffic.navigations.push(url.pathname);return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})}
   if(request.method()!=='GET'){
    if(request.method()!=='POST'||url.pathname!=='/api/v2/cio/ask'){traffic.unexpected.push(request.method()+' '+url.pathname);return route.abort()}
    const body=request.postDataJSON();assert.equal(body.question,f.question);assert.equal(body.depth,'deep');traffic.posts.push({path:url.pathname,body})
    return route.fulfill({contentType:'application/json',body:JSON.stringify(f.ask_response)})
   }
   traffic.reads.push(url.pathname)
   let payload
   if(url.pathname==='/api/v2/cio/asks/tracked')payload={tracked:[]}
   else if(url.pathname==='/api/v2/cio/asks')payload={threads:unwrap(phase==='quick'?f.list_quick:f.list_deep).threads??unwrap(phase==='quick'?f.list_quick:f.list_deep)}
   else if(url.pathname===`/api/v2/cio/asks/${result.thread_id}`)payload={thread:['quick','regressed'].includes(phase)?quick:mode==='wrong-identity'?{...deep,thread_id:'fixture-wrong-source-thread'}:deep}
   else if(url.pathname==='/api/v2/cio/asks/fixture-unavailable-thread'){otherRequested=true;await otherReply;payload={thread:deep}}
   if(!payload){traffic.unexpected.push(url.pathname);return route.abort()}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(payload)})
  })
  const threadPath=`/api/v2/cio/asks/${result.thread_id}`
  await page.goto(`http://ask-readable-fixture.test/v3/${mode==='header-only'?'fixture-empty':`cio/questions/${result.thread_id}`}`)
  const turn=page.getByTestId('ask-thread').locator(`[data-ask-id=${JSON.stringify(result.ask_id)}]`)
  const capture=async(state,screenshot=false)=>{const geometry=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert(geometry.document<=geometry.viewport+1,JSON.stringify({state,...geometry}));geometries.push({state,...geometry});if(screenshot)await page.screenshot({path:path.join(out,`impl-${state}-${width}.png`),fullPage:true,animations:'disabled'})}
  if(mode!=='header-only'){await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(current(quick).summary);await capture('questions-quick',mode==='combined')}
  await page.getByTestId('ask-cio-input').fill(f.question);await page.getByTestId('ask-cio-deep').check();await page.getByTestId('ask-cio-submit').click()
  const answer=page.getByTestId('ask-cio-answer-text')
  await expect(answer).toHaveText(f.telegram_quick_text);assert.equal(await answer.textContent(),f.telegram_quick_text)
  await page.evaluate(()=>document.activeElement instanceof HTMLElement&&document.activeElement.blur())
  await capture('ask-quick',mode==='combined')
  phase='deep';await page.clock.runFor(5_100)
  if(mode==='wrong-identity'){
   await page.waitForLoadState('networkidle');assert.equal(await answer.textContent(),f.telegram_quick_text,'Wrong thread cannot replace this answer')
   await page.getByRole('button',{name:'Close',exact:true}).click()
   await page.evaluate(()=>window.fixtureNavigate('/cio/questions/fixture-unavailable-thread'));await expect.poll(()=>otherRequested).toBe(true)
   await expect(page.getByTestId('ask-thread')).toHaveCount(0)
   holdOther();await expect(page.getByText(/^Thread unavailable/)).toBeVisible();await expect(page.getByTestId('ask-cio-thread-answer-text')).toHaveCount(0)
  }else{
   await expect(answer).toHaveText(f.telegram_deep_text);assert.equal(await answer.textContent(),f.telegram_deep_text)
   assert(!/\*\*|Went outside:|Sources:|Legend:|backup_provider:|\b\d+\.\d{6,}\b/.test(await answer.textContent()),'Canonical prose must not contain raw diagnostic/float formatting')
   if(mode==='combined'){
    await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(f.telegram_deep_text)
    assert.equal(await turn.getByTestId('ask-cio-thread-answer-text').first().textContent(),f.telegram_deep_text)
    await expect(page.getByTestId(`q-${result.thread_id}`)).not.toContainText('Deep research pending')
    for(const details of await page.getByTestId('ask-answer-sources').all())await expect(details).not.toHaveAttribute('open','')
    await capture('ask-deep',true)
    phase='regressed';await page.clock.runFor(31_000);await page.waitForLoadState('networkidle')
    assert.equal(await answer.textContent(),f.telegram_deep_text,'Older saved response must not roll back a newer answer')
    assert.equal(await turn.getByTestId('ask-cio-thread-answer-text').first().textContent(),f.telegram_deep_text)
    phase='deep';await page.clock.runFor(31_000);await page.waitForLoadState('networkidle')
    await expect(page.getByText('The update could not advance this thread — showing its newer saved version.')).toHaveCount(0)
   }
   await page.getByRole('button',{name:'Close',exact:true}).click()
   if(mode==='combined')await capture('questions-deep',true)
   await page.evaluate(()=>window.fixtureNavigate('/fixture-empty'));await page.waitForLoadState('networkidle')
   const reads=traffic.reads.filter(p=>p===threadPath).length
   await page.clock.runFor(61_000);await page.waitForLoadState('networkidle')
   assert.equal(traffic.reads.filter(p=>p===threadPath).length,reads,'Closed answer must stop polling')
  }
  assert.equal(traffic.posts.length,1,'Rendering/completion never resubmits research')
  assert.equal(traffic.navigations.length,1,'Answer completion must not reload the document')
  assert.deepEqual({...traffic,reads:[],posts:[],navigations:[]},{reads:[],posts:[],unexpected:[],external:[],errors:[],navigations:[]})
  const geometry=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert(geometry.document<=geometry.viewport+1,JSON.stringify(geometry))
  receipts.push({width,mode,geometry,geometries,canonical_text_equal:true,traffic});await context.close()
 }
}finally{await browser.close()}
for(const[file,digest]of Object.entries(hashes))assert.equal(sha(file),digest,`Source changed during proof:${file}`)
fs.writeFileSync(path.join(out,'ask-readable-receipts.json'),JSON.stringify({fixture:true,clock:f.clock,source,input_sha256:sha(input),source_evidence:f.source_evidence,cases:receipts},null,2)+'\n')
console.log(`Ask canonical/live proof:${receipts.length} cases passed; identical text, no reload/send/provider calls`)
