/** Actual Watch pages, legacy 104-row and byte-bounded paged responses. No live traffic. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium, expect} from '@playwright/test'
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),output=process.argv[2]
assert(output,'Explicit evidence directory required')
const specimenPath=path.join(app,'e2e/fixtures/conflictEngine.fixture.json'),specimen=JSON.parse(fs.readFileSync(specimenPath,'utf8'))
const finding=specimen.section.findings[0],clock=specimen.clock
const bundle=await build({metafile:true,stdin:{contents:`
import React from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';
import Mine from'./src/pages/WatchMyList';import Prospects from'./src/pages/WatchProspects';import SymbolIntelligencePage from'./src/pages/SymbolIntelligencePage';
import'./src/styles/tokens.css';import'./src/index.css';
createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Routes><Route path="mine" element={<Mine/>}/><Route path="prospects" element={<Prospects/>}/><Route path="watch/intelligence/:symbol" element={<SymbolIntelligencePage/>}/></Routes></BrowserRouter>);
`,resolveDir:app,loader:'tsx',sourcefile:'watch-resolve-fixture.tsx'},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const js=bundle.outputFiles.find(f=>f.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script'),css=bundle.outputFiles.find(f=>f.path.endsWith('.css'))?.text||''
const digest=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')
const source=Object.fromEntries(Object.keys(bundle.metafile.inputs).map(p=>path.resolve(app,p)).filter(p=>p.startsWith(path.join(app,'src')+path.sep)).map(p=>[path.relative(app,p),digest(p)]))
fs.mkdirSync(output,{recursive:true})
const browser=await chromium.launch({headless:true}),cases=[]
try{
 for(const width of [1440,412,390])for(const surface of ['mine','prospects']){
  const height=width===412?915:width===390?844:1000
  const context=await browser.newContext({viewport:{width,height},hasTouch:width<820}),page=await context.newPage()
  const traffic={reads:[],posts:[],external:[],unexpected:[],mutations:[],errors:[]}
  let state='OPEN',paged=false,missing=false,wrongKey=false
  const section=()=>missing?{findings:[],headline:null,gap:{reason:'engine output unavailable'}}:state==='CLEARED'?{findings:[],headline:null,gap:null}:specimen.section
  const rows=()=>Array.from({length:104},(_,i)=>({symbol:i?'F'+String(i).padStart(3,'0'):'SCHD',company:i?'Fixture company':'Fixture dividend fund',security_guid:i?'fixture-'+i:'fixture-guid-schd',
   lane:'actionable',stage:'actionable',why:'Recorded fixture evidence',summary:'Fixture record summary',conviction:67,conviction_components:[],conviction_missing:[],conviction_source:'CIO record',conviction_as_of:clock,conviction_stale:false,
   stance:'HOLD',whats_missing:[],conflicts:[{kind:'legacy_raw_conflict',summary:'LEGACY RAW CONFLICT MUST NOT BECOME A FLAG',a:{value:'TRIM',source:'raw_c3',at:clock},b:{value:'HOLD',source:'raw_desk',at:clock}}],
   conflict_section:i?{findings:[],headline:null,gap:null}:section(),next_trigger:{label:'Watch recorded levels',level_ref:27,inside:false,distance_pct:null,observed_by:'Fixture'},
   next_action:i||state==='CLEARED'?{kind:'none',label:'No action',reason:'Recorded fixture'}:{kind:'resolve_conflict',label:'Resolve conflict',reason:'Review the recorded disagreement'},
   price:27,price_as_of:clock,rsi:null,held:true,position_state:'held',held_accounts:['schwab_roth_ira'],held_account_labels:['Schwab Roth'],surfaces:[],evidence_at:clock,expires_at:null,stale:false,mine:true,starred:true,membership:[]}))
  const record=()=>({...finding,schema:'ConflictRecord@v1',key:wrongKey?'wrong-security-key':finding.key,state,subject:{kind:'security',id:'fixture-guid-schd',label:'SCHD'},opened_at:clock,updated_at:clock,revision:3,
   decision:state==='DECIDED'?{schema:'ConflictDecision@v1',actor_kind:'cio',actor:'CIO',chosen_side:'HOLD',reason:'Fixture reviewed evidence; decision recorded',evidence_refs:['fixture:evidence'],expires_at:'2026-10-25T23:00:00Z'}:null,
   history:[{schema:'ConflictEvent@v1',key:finding.key,event:'opened',at:clock},...(state==='OPEN'?[]:[{schema:'ConflictEvent@v1',key:finding.key,event:'review_queued',request_id:'fixture-request',at:clock}])]})
  page.on('pageerror',e=>traffic.errors.push(String(e)))
  await page.clock.install({time:new Date(clock)})
  await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
  await page.route('**/*',route=>{
   const req=route.request(),url=new URL(req.url())
   if(url.origin!=='http://watch-resolve-fixture.test'){traffic.external.push(url.href);return route.abort()}
   const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)})
   if(req.method()==='POST'&&url.pathname==='/api/v3/opportunities/SCHD/review-request'){
    traffic.posts.push({path:url.pathname,body:req.postDataJSON()});state='UNDER_REVIEW'
    return json({ok:true,symbol:'SCHD',review:{open:true,request_id:'fixture-request'},already_open:false})
   }
   if(req.method()!=='GET'){traffic.mutations.push(req.method()+' '+url.pathname);return route.abort()}
   if(req.isNavigationRequest())return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:16px;min-width:0}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
   traffic.reads.push(url.pathname+url.search)
   if(url.pathname.startsWith('/api/v3/conflicts/')){
    assert.equal(decodeURIComponent(url.pathname.slice('/api/v3/conflicts/'.length)),finding.key)
    return json(record())
   }
   if(['/api/v3/data-broker/watch-curation','/api/v3/data-broker/watch-prospects'].includes(url.pathname)){
    assert.equal(url.searchParams.get('limit'),'25');const offset=Number(url.searchParams.get('offset')||0)
    const all=rows(),items=paged?all.slice(offset,offset+17):all
    const pagination=paged?{offset,returned:items.length,total:104,next_offset:offset+items.length<104?offset+items.length:null,has_more:offset+items.length<104}:undefined
    if(url.pathname.endsWith('watch-curation'))return json({ok:true,data:{my_watchlist:{rows:items,count:104,unfiltered_count:104,starred:104,kind_counts:{all:104,starred:104},sources:{},pagination}}})
    return json({ok:true,data:{schema:'WatchProspects@v1',source:'fixture',interim:false,generated_at:clock,source_label:'Fixture record',sources:{},counts:{prospects:104,conflicts:state==='CLEARED'?0:1},curation:{one_membership:true,caps:{},sort_order:'Fixture recorded order',expiry:'Fixture'},pagination,
     lanes:['actionable','forming','reentry','manage','expired'].map(id=>({id,label:id==='actionable'?'Actionable':id,hint:'Recorded fixture lane',count:id==='actionable'?104:0,cap:104,items:id==='actionable'?items:[],overflow:[]}))}})
   }
   if(url.pathname==='/api/v2/watch/alerts/list')return json({ok:true,data:{alerts:[]}})
   if(url.pathname==='/api/v3/data-broker/watch-intelligence/SCHD')return json({ok:true,data:{card:{symbol:'SCHD',company:'Fixture dividend fund',last:27},detail:{}}})
   if(url.pathname==='/api/v3/cio/intelligence/SCHD')return json({ok:true,data:{intelligence:{},journal:[]}})
   traffic.unexpected.push(url.pathname);return route.abort()
  })
  const tap=async loc=>{await loc.scrollIntoViewIfNeeded();const b=await loc.boundingBox();if(width<820){assert(b&&b.width>=44&&b.height>=44,'44px tap target '+JSON.stringify(b));await loc.tap()}else await loc.click()}
  const inView=async loc=>{await expect(loc).toBeVisible();const b=await loc.boundingBox();assert(b&&b.x>=-1&&b.y>=-1&&b.x+b.width<=width+1&&b.y+b.height<=height+1,'Viewport '+JSON.stringify(b))}
  const noHorizontal=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal page scroll')
  const start=`http://watch-resolve-fixture.test/v3/${surface}?source=fixture`
  await page.goto(start)
  await expect(page.getByTestId('watch-row')).toHaveCount(104)
  if(surface==='mine'){
   await tap(page.getByTestId('mine-kind-starred'))
   await expect(page.getByTestId('mine-kind-starred')).toHaveAttribute('aria-pressed','true')
   assert.equal(new URL(page.url()).searchParams.get('mine'),'starred')
   await expect.poll(()=>traffic.reads.some(u=>new URL(u,'http://fixture').searchParams.get('mine')==='starred')).toBe(true)
  }else{
   await tap(page.getByTestId('watch-lane-forming'))
   await expect(page.getByTestId('watch-lane-forming')).toHaveAttribute('aria-pressed','true')
   await inView(page.getByText('Nothing in forming right now.',{exact:true}))
   assert.equal(new URL(page.url()).searchParams.get('lane'),'forming')
   await tap(page.getByTestId('watch-lane-actionable'))
   await expect(page.getByTestId('watch-row')).toHaveCount(104)
  }
  const row=page.getByTestId('watch-row').filter({has:page.locator('[title="Open the SCHD record"]')})
  await expect(row.getByTestId('conflict-headline')).toHaveText(specimen.section.headline)
  await expect(page.locator('body')).not.toContainText('LEGACY RAW CONFLICT MUST NOT BECOME A FLAG')
  await noHorizontal()
  await tap(row.getByRole('button',{name:'Resolve conflict',exact:true}))
  const dialog=page.getByRole('dialog',{name:'SCHD · recorded conflict'})
  await inView(dialog);await inView(dialog.getByRole('button',{name:'← Back'}))
  await inView(dialog.getByRole('heading',{name:'What disagrees',exact:true}))
  assert(await dialog.evaluate(el=>el.contains(document.activeElement)),'Focus enters the conflict detail')
  assert.equal(new URL(page.url()).searchParams.get('conflict'),finding.key)
  await expect(dialog).toContainText('Schwab Roth');await expect(dialog).not.toContainText('schwab_roth_ira')
  await expect(dialog.getByTestId('conflict-side')).toHaveCount(finding.sides.length)
  await expect(dialog.getByTestId('conflict-record-state')).toHaveAttribute('data-state','OPEN')
  await page.screenshot({path:path.join(output,`impl-watch-${surface}-conflict-open-${width}.png`),fullPage:false,animations:'disabled'})
  const ask=dialog.getByRole('button',{name:'Ask the CIO to review',exact:true})
  await tap(ask)
  await expect(dialog.getByTestId('watch-review-message')).toContainText('saved history')
  await expect(dialog.getByTestId('conflict-record-state')).toHaveAttribute('data-state','UNDER_REVIEW')
  await expect(dialog).toContainText('Review queued');assert.equal(traffic.posts.length,1)
  await expect(dialog.getByRole('button',{name:'CIO review in progress',exact:true})).toBeDisabled()
  await page.screenshot({path:path.join(output,`impl-watch-${surface}-review-queued-${width}.png`),fullPage:false,animations:'disabled'})
  const evidence=dialog.getByRole('link',{name:'Open evidence →',exact:true})
  await tap(evidence);await inView(page.getByText('SCHD',{exact:true}).first())
  await page.goBack();await inView(page.getByRole('dialog',{name:'SCHD · recorded conflict'}))
  await page.goBack();await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByTestId('watch-row')).toHaveCount(104)
  await tap(row.getByRole('button',{name:'Resolve conflict',exact:true}))
  state='DECIDED';await page.clock.runFor(15_000)
  await expect(dialog.getByTestId('conflict-record-state')).toHaveText('Decision recorded · awaiting engine re-evaluation')
  await expect(dialog.getByTestId('watch-ask-cio')).toHaveCount(0)
  await expect(row.getByTestId('conflict-headline')).toHaveText(specimen.section.headline)
  state='CLEARED';await page.clock.runFor(120_000)
  await expect(dialog.getByTestId('conflict-record-state')).toHaveText('Cleared by the engine')
  await tap(dialog.getByRole('button',{name:'← Back'}))
  await expect(row.getByTestId('conflict-line')).toHaveCount(0)
  await expect(row.getByRole('button',{name:'Resolve conflict',exact:true})).toHaveCount(0)
  assert.equal(new URL(page.url()).searchParams.get('source'),'fixture')
  if(width<820){
   await tap(row.locator('[title="Open the SCHD record"]'))
   const recordDialog=page.getByRole('dialog',{name:surface==='mine'?'SCHD · watch record':'SCHD · prospect record'})
   await inView(recordDialog);await inView(recordDialog.getByRole('button',{name:'← Back'}))
   await page.goBack();await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  // The released W2 pager must use the actual next_offset (17), not limit (25).
  paged=true;await page.goto(start)
  await expect(page.getByTestId('watch-row')).toHaveCount(17)
  await tap(page.getByRole('button',{name:'Next',exact:true}))
  await expect.poll(()=>traffic.reads.some(u=>new URL(u,'http://fixture').searchParams.get('offset')==='17')).toBe(true)
  await expect(page.getByTestId('watch-row').first()).toHaveAttribute('data-symbol','F017')
  await tap(page.getByRole('button',{name:'Previous',exact:true}))
  await expect(page.getByTestId('watch-row').first()).toHaveAttribute('data-symbol','SCHD')
  // Missing engine output and a mismatched selected record never become a clean result or another security's history.
  state='OPEN';missing=true;await page.goto(start)
  await expect(row.getByTestId('conflict-gap')).toContainText('engine output unavailable')
  await expect(row.getByTestId('conflict-line')).toHaveCount(0)
  missing=false;wrongKey=true;await page.goto(start+`&symbol=SCHD&conflict=${encodeURIComponent(finding.key)}`)
  await expect(dialog.getByTestId('conflict-record-gap')).toContainText('selected record was not supplied')
  await expect(dialog.getByTestId('conflict-record-state')).toHaveCount(0)
  await expect(dialog.getByTestId('watch-ask-cio')).toHaveCount(0)
  await noHorizontal()
  assert.deepEqual({external:traffic.external,unexpected:traffic.unexpected,mutations:traffic.mutations,errors:traffic.errors},{external:[],unexpected:[],mutations:[],errors:[]})
  assert.equal(traffic.posts.length,1)
  cases.push({surface,width,height,legacy_104_rows:true,resolve_tap_visible:true,focused_disagreement:true,real_pages:true,filter_taps:true,phone_record_selection:true,queue_post_mock_only:true,ledger_history:true,decided_not_cleared:true,engine_clear_only:true,evidence_route_back:true,actual_next_offset:17,missing_engine_gap:true,selected_key_guard:true,traffic})
  await context.close()
 }
}finally{await browser.close()}
for(const [file,sha]of Object.entries(source))assert.equal(digest(path.join(app,file)),sha,'Source changed during proof: '+file)
fs.writeFileSync(path.join(output,'watch-resolve-receipts.json'),JSON.stringify({scope:'Actual Watch UI using synthetic engine/API records only; not final rulebook or runtime acceptance',fixture_sha256:digest(specimenPath),source_sha256:source,cases},null,2)+'\n')
console.log('Actual My Watchlist/Prospects 1440/412/390: 104-row Resolve, focused sheet, queue/history, DECIDED≠CLEARED, evidence/Back, actual paging, gaps and key guard passed; all traffic intercepted')
