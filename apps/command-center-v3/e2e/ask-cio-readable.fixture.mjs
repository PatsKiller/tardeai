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
const input=path.resolve(process.argv[2]||path.join(app,'e2e/fixtures/askCioReadable.fixture.json')),out=process.argv[3]
assert(out,'Explicit screenshot/receipt directory required');assert(fs.existsSync(input),'Root-generated canonical copied-ledger fixture required; no sample prose fallback')
const f=JSON.parse(fs.readFileSync(input,'utf8')),unwrap=value=>value?.data??value
const result=unwrap(f.ask_response),quick=unwrap(f.quick_thread).thread??unwrap(f.quick_thread),deep=unwrap(f.deep_thread).thread??unwrap(f.deep_thread)
assert.equal(result.thread_id,quick.thread_id);assert.equal(quick.thread_id,deep.thread_id)
const current=(thread)=>[...thread.turns.find(turn=>turn.ask_id===result.ask_id).answers].filter(a=>a.status!=='deep_pending').sort((a,b)=>b.version-a.version)[0]
assert.equal(result.answer_text,f.telegram_quick_text);assert.equal(current(deep).summary,f.telegram_deep_text)
assert(current(deep).version>current(quick).version,'Deep fixture must have a new durable answer version')
assert.equal(typeof f.question,'string');assert(f.clock&&f.list_quick&&f.list_deep)
const bundle=await build({metafile:true,stdin:{contents:`import React,{useEffect} from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Route,Routes,useNavigate}from'react-router-dom';import AskCioBar from'./src/components/AskCioBar';import MyQuestions from'./src/pages/MyQuestions';import'./src/styles/tokens.css';import'./src/index.css';function Fixture(){const navigate=useNavigate();useEffect(()=>{window.fixtureNavigate=navigate},[navigate]);return <><AskCioBar/><div style={{padding:20}}><Routes><Route path="/cio/questions" element={<MyQuestions/>}/><Route path="/cio/questions/:threadId" element={<MyQuestions/>}/><Route path="*" element={<div>Isolated host</div>}/></Routes></div></>};createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Fixture/></BrowserRouter>);`,loader:'tsx',sourcefile:'ask-cio-readable-fixture.tsx',resolveDir:app},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
if(process.env.ASK_FIXTURE_VALIDATE_ONLY==='1'){console.log('Ask readable fixture compiled; browser execution skipped by explicit validation-only mode');process.exit(0)}
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files=[...Object.keys(bundle.metafile.inputs).map(name=>path.resolve(app,name)).filter(file=>file.startsWith(path.join(app,'src')+path.sep)),input,fileURLToPath(import.meta.url),path.join(app,'package.json'),path.join(app,'package-lock.json')]
const hashes=Object.fromEntries(files.map(file=>[file,sha(file)])),source={head:execFileSync('git',['rev-parse','HEAD'],{cwd:app,encoding:'utf8'}).trim(),working_patch_sha256:crypto.createHash('sha256').update(execFileSync('git',['diff','HEAD'],{cwd:app})).digest('hex'),file_sha256:hashes}
const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script'),css=bundle.outputFiles.find(file=>file.path.endsWith('.css'))?.text||''
fs.mkdirSync(out,{recursive:true})
const browser=await chromium.launch({headless:true}),receipts=[]
try{
 for(const [width,height] of [[1440,1100],[412,915],[390,844]])for(const mode of ['combined','header-only','wrong-identity']){
  const mobile=width<=820, taps=[],targets=[]
  const context=await browser.newContext({viewport:{width,height},isMobile:mobile,hasTouch:mobile}),page=await context.newPage(),traffic={reads:[],posts:[],unexpected:[],external:[],errors:[],navigations:[]},geometries=[]
  let phase='quick',holdOther,otherRequested=false
  const otherReply=new Promise(resolve=>{holdOther=resolve})
  await page.clock.install({time:new Date(f.clock)})
  page.on('pageerror',e=>traffic.errors.push(String(e)))
  await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url())
   if(url.origin!=='http://ask-readable-fixture.test'){traffic.external.push(url.origin+url.pathname);return route.abort()}
   if(request.isNavigationRequest()){traffic.navigations.push(url.pathname);return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})}
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
  await page.goto(`http://ask-readable-fixture.test/v3/${mode==='header-only'?'fixture-empty':mobile?'cio/questions':`cio/questions/${result.thread_id}`}`)
  const turn=page.getByTestId('ask-thread').locator(`[data-ask-id=${JSON.stringify(result.ask_id)}]`)
  const capture=async(state,screenshot=false)=>{if(mobile){const areas=await page.evaluate(()=>{const sheets=[...document.querySelectorAll('[data-phone-sheet="true"]')].sort((a,b)=>Number(getComputedStyle(b).zIndex)-Number(getComputedStyle(a).zIndex));const roots=sheets.length?[sheets[0]]:[document.querySelector('[data-testid="ask-cio-bar"]'),document.querySelector('[data-testid="my-questions"]')].filter(Boolean);return roots.flatMap(root=>[...root.querySelectorAll('button,a[href],input,textarea,summary')]).filter(node=>!node.disabled).map(node=>{const target=node.matches('input[type=checkbox]')?node.closest('label'):node;const r=target?.getBoundingClientRect();return r&&r.width&&r.height&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth?{name:target.getAttribute('aria-label')||target.textContent?.slice(0,70)||target.tagName,width:r.width,height:r.height}:null}).filter(Boolean)});for(const area of areas)assert(area.width>=44&&area.height>=44,`${state}: small target ${JSON.stringify(area)}`);targets.push({state,areas})}const geometry=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert(geometry.document<=geometry.viewport+1,JSON.stringify({state,...geometry}));geometries.push({state,...geometry});if(screenshot)await page.screenshot({path:path.join(out,`impl-${state}-${width}.png`),fullPage:true,animations:'disabled'})}
  const tap=async(locator,name)=>{await locator.scrollIntoViewIfNeeded();const rect=await locator.boundingBox();assert(rect&&rect.x>=0&&rect.y>=0&&rect.x+rect.width<=width+1&&rect.y+rect.height<=height+1,`${name} outside viewport`);if(mobile){assert(rect.width>=44&&rect.height>=44,`${name} target ${JSON.stringify(rect)}`);await locator.tap();taps.push({name,...rect})}else await locator.click()}
  const phoneSheet=async(testid)=>{const sheet=page.getByTestId(testid);await expect(sheet).toBeVisible();const box=await sheet.boundingBox();assert(box&&box.x===0&&box.y===0&&Math.abs(box.width-width)<=1&&Math.abs(box.height-height)<=1);assert(await sheet.evaluate(node=>node.contains(document.activeElement)),`${testid} must receive focus`);targets.push({sheet:testid,...box})}
  if(!mobile&&mode!=='header-only'){await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(current(quick).summary);await capture('questions-quick',mode==='combined')}
  if(mobile&&mode==='combined'){await expect(page.getByTestId(`q-${result.thread_id}`)).toBeVisible();await capture('questions-quick',true)}
  await tap(page.getByTestId('ask-cio-input'),'question input');await page.getByTestId('ask-cio-input').fill(f.question);await tap(page.getByTestId('ask-cio-deep').locator('..'),'deep option');await tap(page.getByTestId('ask-cio-submit'),'Ask primary action')
  const answer=page.getByTestId('ask-cio-answer-text')
  await expect(answer).toHaveText(f.telegram_quick_text);assert.equal(await answer.textContent(),f.telegram_quick_text)
  if(mobile)await phoneSheet('ask-cio-answer')
  await page.evaluate(()=>document.activeElement instanceof HTMLElement&&document.activeElement.blur())
  await capture('ask-quick',mode==='combined')
  phase='deep';await page.clock.runFor(5_100)
  if(mode==='wrong-identity'){
   await page.waitForLoadState('networkidle');assert.equal(await answer.textContent(),f.telegram_quick_text,'Wrong thread cannot replace this answer')
   await tap(page.getByTestId('ask-cio-close'),'answer Back')
   await page.evaluate(()=>window.fixtureNavigate('/cio/questions/fixture-unavailable-thread'));await expect.poll(()=>otherRequested).toBe(true)
   await expect(page.getByTestId('ask-thread')).toHaveCount(0)
   holdOther();await expect(page.getByText(/^Thread unavailable/)).toBeVisible();await expect(page.getByTestId('ask-cio-thread-answer-text')).toHaveCount(0)
  }else{
   await expect(answer).toHaveText(f.telegram_deep_text);assert.equal(await answer.textContent(),f.telegram_deep_text)
   assert(!/\*\*|Went outside:|Sources:|Legend:|backup_provider:|\b\d+\.\d{6,}\b/.test(await answer.textContent()),'Canonical prose must not contain raw diagnostic/float formatting')
   if(mode==='combined'){
    if(!mobile)await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(f.telegram_deep_text)
    if(!mobile)assert.equal(await turn.getByTestId('ask-cio-thread-answer-text').first().textContent(),f.telegram_deep_text)
    await expect(page.getByTestId(`q-${result.thread_id}`)).not.toContainText('Deep research pending')
    for(const details of await page.getByTestId('ask-answer-sources').all())await expect(details).not.toHaveAttribute('open','')
    await capture('ask-deep',true)
    phase='regressed';await page.clock.runFor(31_000);await page.waitForLoadState('networkidle')
    assert.equal(await answer.textContent(),f.telegram_deep_text,'Older saved response must not roll back a newer answer')
    if(!mobile)assert.equal(await turn.getByTestId('ask-cio-thread-answer-text').first().textContent(),f.telegram_deep_text)
    phase='deep';await page.clock.runFor(31_000);await page.waitForLoadState('networkidle')
    await expect(page.getByText('The update could not advance this thread — showing its newer saved version.')).toHaveCount(0)
   }
   if(mobile&&mode==='combined'){
    const disclosure=page.getByTestId('ask-cio-answer').getByTestId('ask-answer-sources')
    await tap(disclosure.locator('summary'),'How I know this disclosure');await expect(disclosure).toHaveAttribute('open','')
    await tap(disclosure.locator('summary'),'Collapse sources');await expect(disclosure).not.toHaveAttribute('open','')
    await tap(page.getByTestId('ask-cio-open-thread'),'Open thread primary action')
    await expect(page).toHaveURL(new RegExp(`/cio/questions/${result.thread_id}$`));await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(f.telegram_deep_text)
    await phoneSheet('ask-thread-sheet');await capture('questions-deep',true)
    await tap(page.getByTestId('ask-thread-back'),'thread Back');await expect(page.getByTestId('ask-thread')).toHaveCount(0)
    const filter=page.getByRole('textbox',{name:'Filter questions'})
    await tap(filter,'Filter questions');await filter.fill('fixture-unmatched-filter');await expect(page.getByTestId('my-questions-list').locator('li')).toHaveCount(0);await expect(page).toHaveURL(/q=fixture-unmatched-filter/)
    await filter.fill('Tesla');await tap(page.getByTestId(`q-${result.thread_id}`),'Open filtered question')
    await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(f.telegram_deep_text);await phoneSheet('ask-thread-sheet')
    await page.goBack();await expect(page.getByTestId('ask-thread')).toHaveCount(0);await expect(filter).toHaveValue('Tesla');await capture('questions-back-filter',true)
    await page.goForward();await expect(turn.getByTestId('ask-cio-thread-answer-text').first()).toHaveText(f.telegram_deep_text);await phoneSheet('ask-thread-sheet');await page.goBack();await expect(page.getByTestId('ask-thread')).toHaveCount(0)
   }else{
    await tap(page.getByTestId('ask-cio-close'),'answer Back')
    if(mode==='combined')await capture('questions-deep',true)
   }
   await page.evaluate(()=>window.fixtureNavigate('/fixture-empty'));await page.waitForLoadState('networkidle')
   const reads=traffic.reads.filter(p=>p===threadPath).length
   await page.clock.runFor(61_000);await page.waitForLoadState('networkidle')
   assert.equal(traffic.reads.filter(p=>p===threadPath).length,reads,'Closed answer must stop polling')
  }
  assert.equal(traffic.posts.length,1,'Rendering/completion never resubmits research')
  assert.equal(traffic.navigations.length,1,'Answer completion must not reload the document')
  assert.deepEqual({...traffic,reads:[],posts:[],navigations:[]},{reads:[],posts:[],unexpected:[],external:[],errors:[],navigations:[]})
  const geometry=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert(geometry.document<=geometry.viewport+1,JSON.stringify(geometry))
  receipts.push({width,height,mode,geometry,geometries,taps,targets,canonical_text_equal:true,traffic});await context.close()
 }

 // Hourly lifecycle UI: one synthetic thread shown under two securities, one refresh request.
 if(f.hourly_ui)for(const [width,height] of [[1440,1100],[412,915],[390,844]]){
  const fixture=f.hourly_ui,thread=fixture.thread,mobile=width<=820
  const context=await browser.newContext({viewport:{width,height},isMobile:mobile,hasTouch:mobile}),page=await context.newPage()
  const traffic={posts:[],unexpected:[],external:[],errors:[]};let blocked=false,releaseRefresh
  const refreshResponse=new Promise(resolve=>{releaseRefresh=resolve})
  await page.clock.install({time:new Date(fixture.clock)})
  page.on('pageerror',error=>traffic.errors.push(String(error)))
  await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
  const lifecycle=()=>blocked?{...thread.lifecycle,state:'blocked',reason:fixture.blocked_reason,next_check_at:null,next_eligible_at:'2031-03-10T16:00:00Z'}:thread.lifecycle
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url())
   if(url.origin!=='http://ask-readable-fixture.test'){traffic.external.push(url.origin+url.pathname);return route.abort()}
   if(request.isNavigationRequest())return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
   if(request.method()!=='GET'){
    if(request.method()!=='POST'||url.pathname!==`/api/v2/cio/asks/${thread.thread_id}/deep`){traffic.unexpected.push(request.method()+' '+url.pathname);return route.abort()}
    const body=request.postDataJSON();assert.equal(typeof body.request_id,'string');assert(body.request_id.length>0);traffic.posts.push(body)
    await refreshResponse;blocked=true
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,data:{status:'blocked',request_id:body.request_id,reason:fixture.blocked_reason,lifecycle:lifecycle()}})})
   }
   let payload
   if(url.pathname==='/api/v2/cio/asks/tracked')payload={tracked:[]}
   else if(url.pathname===`/api/v2/cio/asks/${thread.thread_id}`)payload={thread:{...thread,lifecycle:lifecycle()}}
   else if(url.pathname==='/api/v2/cio/asks'){
    const summary={...thread,turns:thread.turns.length,last_answer_excerpt:thread.turns[0].answers[0].summary,lifecycle:lifecycle()}
    payload={threads:[summary]}
    if(url.searchParams.has('group_by'))payload.grouped={group_by:url.searchParams.get('group_by'),q:url.searchParams.get('q')||'',channel:url.searchParams.get('channel'),counts:{groups:2,questions:1,threads:1},group_bys:[{id:'security',available:true,reason:null}],groups:thread.entities.map(entity=>({key:entity.key,label:entity.symbol,sub:null,symbol:entity.symbol,security_guid:entity.key,symbols:[entity.symbol],thread_ids:[thread.thread_id],counts:{questions:1,threads:1,names:1},memory:fixture.memory,lifecycle:lifecycle(),questions:[{ask_id:thread.turns[0].ask_id,thread_id:thread.thread_id,question:thread.turns[0].question,asked_at:thread.turns[0].asked_at,channel:'cc',depth:'deep'}]}))}
   }
   if(!payload){traffic.unexpected.push(url.pathname);return route.abort()}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(payload)})
  })
  await page.goto('http://ask-readable-fixture.test/v3/cio/questions')
  const groups=page.getByTestId('my-questions-groups'),receiptsUI=groups.getByTestId('ask-research-lifecycle')
  await expect(groups.getByTestId('mq-group')).toHaveCount(2)
  for(const receipt of await receiptsUI.all()){
   await expect(receipt).toContainText('Checked — no material change');await expect(receipt).toContainText('Last checked: Mar 10');await expect(receipt).toContainText('Last answer: Mar 9');await expect(receipt).toContainText('Next check: Mar 10');await expect(receipt).toContainText('Question memory: saved')
  }
  for(const memory of await groups.getByTestId('mq-group-memory').all())await expect(memory).toContainText('Current stance: unavailable (shadow record)')
  const capture=async state=>{const geometry=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert(geometry.document<=geometry.viewport+1);await page.screenshot({path:path.join(out,`impl-hourly-${state}-${width}.png`),fullPage:true,animations:'disabled'});return geometry}
  const geometry=await capture('current')
  const refreshes=groups.getByTestId(`ask-refresh-${thread.thread_id}`).getByRole('button')
  await expect(refreshes).toHaveCount(2)
  if(mobile)await refreshes.first().tap();else await refreshes.first().click()
  await expect.poll(()=>traffic.posts.length).toBe(1)
  for(const button of await refreshes.all())await expect(button).toBeDisabled()
  // A duplicate event on the second representation cannot create another job.
  await refreshes.nth(1).evaluate(button=>button.click());assert.equal(traffic.posts.length,1)
  releaseRefresh()
  for(const receipt of await groups.getByTestId(`ask-refresh-${thread.thread_id}`).all())await expect(receipt).toContainText(fixture.blocked_reason)
  await capture('blocked')
  await groups.getByTestId(`gq-${thread.turns[0].ask_id}`).first().click()
  const detail=page.getByTestId('ask-thread-sheet');await expect(page.getByTestId('ask-thread')).toBeVisible()
  if(mobile){const bounds=await detail.boundingBox();assert(bounds&&bounds.x===0&&bounds.y===0&&Math.abs(bounds.width-width)<=1&&Math.abs(bounds.height-height)<=1)}
  await expect(detail.getByTestId('ask-research-lifecycle')).toContainText('Last answer: Mar 9')
  await expect(detail.getByTestId('ask-research-lifecycle')).toContainText('Next eligible: Mar 10')
  await expect(detail.getByTestId('ask-cio-thread-answer-text')).toHaveText(thread.turns[0].answers[0].summary)
  const button=detail.getByTestId(`ask-refresh-${thread.thread_id}`).getByRole('button');assert((await button.boundingBox()).height>=44)
  await capture('thread')
  assert.equal(traffic.posts.length,1);assert.deepEqual(traffic.errors,[]);assert.deepEqual(traffic.unexpected,[]);assert.deepEqual(traffic.external,[])
  receipts.push({width,height,mode:'hourly',geometry,one_shared_refresh:true,separate_check_and_answer_clocks:true,traffic})
  await context.close()
 }
}finally{await browser.close()}
for(const[file,digest]of Object.entries(hashes))assert.equal(sha(file),digest,`Source changed during proof:${file}`)
fs.writeFileSync(path.join(out,'ask-readable-receipts.json'),JSON.stringify({fixture:true,clock:f.clock,source,input_sha256:sha(input),source_evidence:f.source_evidence,cases:receipts},null,2)+'\n')
console.log(`Ask canonical/live proof:${receipts.length} cases passed; identical text, no reload/send/provider calls`)
