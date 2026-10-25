/** Operator-run fixture proof. BLOCKED in the agent: do not run/relocate/escalate the browser here.
 * Uses an ordinary bounded localhost fixture server, with every API request intercepted.
 * No production API, proxy, credential, broker, sender or job is reachable.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium,expect} from '@playwright/test'

const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const output=process.argv[2]
assert(output,'Explicit fresh evidence directory required')
fs.mkdirSync(output,{recursive:false})
const clock='2026-10-23T14:00:00Z'
const fixturesBuild=await build({stdin:{contents:`import{FIXTURE}from'./src/fixtures/watchProspects.fixture';import{WATCH_LISTS_FIXTURE}from'./src/fixtures/watchLists.fixture';export const fixture={prospects:FIXTURE.prospects,alerts:FIXTURE.alerts,curation:WATCH_LISTS_FIXTURE.curation};`,resolveDir:app,loader:'ts'},bundle:true,write:false,format:'esm',platform:'node',logLevel:'silent'})
const {fixture}=await import(`data:text/javascript;base64,${Buffer.from(fixturesBuild.outputFiles[0].text).toString('base64')}`)
const bundle=await build({stdin:{contents:`import React from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,useLocation}from'react-router-dom';import ActiveTraderHub from'./src/pages/ActiveTraderHub';import CommunicationsHub from'./src/pages/CommunicationsHub';import WatchProspects from'./src/pages/WatchProspects';import WatchMyList from'./src/pages/WatchMyList';import WatchSuggests from'./src/pages/WatchSuggests';import WatchpoolHub from'./src/pages/WatchpoolHub';import'./src/styles/tokens.css';import'./src/index.css';function Fixture(){const p=useLocation().pathname;return <main style={{padding:12,minWidth:0}}><div style={{marginBottom:8}}>Isolated W2 fixture · synthetic/captured inputs</div>{p==='/communications'?<CommunicationsHub/>:p==='/prospects'?<WatchProspects/>:p==='/mine'?<WatchMyList/>:p==='/suggests'?<WatchSuggests/>:p==='/pool'?<WatchpoolHub onDrill={()=>{}}/>:<ActiveTraderHub/>}</main>}createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Fixture/></BrowserRouter>);`,resolveDir:app,sourcefile:'site-load-fixture.tsx',loader:'tsx'},bundle:true,write:false,metafile:true,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const html=`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${bundle.outputFiles.find(f=>f.path.endsWith('.css'))?.text||''}body{margin:0;background:var(--bg0);color:var(--text0)}</style><div id="root"></div><script>${bundle.outputFiles.find(f=>f.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script')}</script>`
const server=http.createServer((req,res)=>{if(req.url.startsWith('/api/')){res.writeHead(503,{'Content-Type':'application/json'});res.end('{"ok":false,"error":"fixture interceptor required"}')}else{res.writeHead(200,{'Content-Type':'text/html'});res.end(html)}})
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve)})
const origin=`http://127.0.0.1:${server.address().port}`
const sha=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')
const sourceFiles=[...Object.keys(bundle.metafile.inputs).map(n=>path.resolve(app,n)),fileURLToPath(import.meta.url),path.resolve(app,'src/fixtures/watchProspects.fixture.ts'),path.resolve(app,'src/fixtures/watchLists.fixture.ts'),path.join(app,'package.json'),path.join(app,'package-lock.json'),path.resolve(app,'../../scripts/lib/site_payload_reads.py')]
const hashes=Object.fromEntries(sourceFiles.filter(f=>fs.existsSync(f)).map(f=>[path.relative(app,f),sha(f)]))
const flows=[],traffic=[],unexpected=[],blockedExternal=[],errors=[]
let browser
let passed=false
const facts={source_observation_state:'CURRENT_SESSION',passed_count:1,required_count:5,policy_path:'fixture',pillars:[],social_scout:{reported_count:null},catalyst:{text:'Synthetic fixture catalyst',publication_state:'CURRENT_SESSION',verification_status:'UNVERIFIED',reported_verified:false}}
const candidates=Array.from({length:40},(_,i)=>({candidate_id:`fixture-${i}`,symbol:`FX${i}`,session_date:'2026-10-23',sources:['TRADE_AI','ACTIVE_TRADER'],classification:'PENDING',conflicts:i%2?[]:['fixture disagreement'],reconciliation_status:'IDENTITY_OR_EVENT_UNRESOLVED',trade_ai:{status:'AVAILABLE',session_state:'CURRENT_SESSION',verdicts:['WAIT'],observations:Array.from({length:4},(_,j)=>({verdict:'WAIT',observed_at:clock,run_id:`fixture-${j}`,setup_evidence:facts}))},active_trader:{status:'AVAILABLE',session_state:'CURRENT_SESSION',verdicts:[],observations:[]}}))
const message={event_id:'fixture-message',direction:'OUTBOUND',event_type:'fixture',message_class:'advisory',severity:'INFO',producer:'fixture',subject_key:'fixture',headline:'Fixture research update',short_summary:'Read-only fixture message',body:'Fixture body',symbols:[],retention_class:'operational',knowledge_status:'accepted',created_at:clock,ttl_remaining_s:3600,category:'attention',priority:'normal',lifecycle_status:'active'}
const pageOf=(rows,q,limit=25)=>{const offset=Number(q.get('offset')||0),n=Number(q.get('limit')||limit),items=rows.slice(offset,offset+n);return {items,pagination:{offset,limit:n,returned:items.length,total:rows.length,next_offset:offset+items.length<rows.length?offset+items.length:null,has_more:offset+items.length<rows.length}}}
function response(u,request){
  const p=u.pathname,q=u.searchParams
  if(request.method()!=='GET'){
    if(p==='/api/v2/communications/events/bulk'){assert.equal(request.postDataJSON().confirm,false);return {ok:true,needs_confirm:true,preview:{action:'acknowledge',target:'fixture-message',old_value:'unseen',new_value:'seen'}}}
    if(p.includes('/review-request')||p==='/api/v3/watch/commands/mine'||p==='/api/v3/watch/commands/suggest-dismiss'||p==='/api/v3/watch/commands/suggest-restore')return {ok:true,data:{ok:true}}
    unexpected.push(`${request.method()} ${p}`);return {ok:false,error:'Unregistered fixture mutation'}
  }
  if(p==='/api/v2/trade-ai/candidates'){
    const mode=q.get('filter')||'ACTIONABLE',id=q.get('candidate_id')
    const all=id?candidates.filter(r=>r.candidate_id===id):mode==='CONFLICT'?candidates.filter(r=>r.conflicts.length):candidates
    if(id){const row=all[0];if(!row)return {schema:'SharedMomentumCandidates@v1',candidates:[],payload_gap:{reason:'candidate_not_in_snapshot'}};const key=q.get('history_source')==='ACTIVE_TRADER'?'active_trader':'trade_ai',pg=pageOf(row[key].observations,q,10);return {schema:'SharedMomentumCandidates@v1',history_source:key.toUpperCase(),candidates:[{...row,trade_ai:{...row.trade_ai,observations:key==='trade_ai'?pg.items:[]},active_trader:{...row.active_trader,observations:key==='active_trader'?pg.items:[]}}],pagination:pg.pagination}}
    const page=pageOf(all,q,20)
    return {schema:'SharedMomentumCandidates@v1',snapshot_id:'fixture',session_date:'2026-10-23',generated_at:clock,status:'AVAILABLE',candidate_count:40,filter_counts:{ALL:40,ACTIONABLE:40,CURRENT:40,CONFLICT:20},source_metadata:{TRADE_AI:{status:'OK'},ACTIVE_TRADER:{status:'OK'}},candidates:page.items.map(r=>({...r,trade_ai:{...r.trade_ai,observation_count:4,observations:id?r.trade_ai.observations:r.trade_ai.observations.slice(0,1)}})),pagination:page.pagination}
  }
  if(p==='/api/v3/active-trader/alerts')return {decisions:[],your_trades:[],session_date:'2026-10-23'}
  if(p==='/api/v3/active-trader/permission-queue')return {data_state:'EMPTY_LIVE_QUEUE',signals:[],actionable_count:0}
  if(p==='/api/v3/active-trader/scalp/setups')return {setup_registry:{setups:[],registry_hash:'fixture'}}
  if(p==='/api/v2/watch/alerts/list')return fixture.alerts?.data||fixture.alerts
  if(p==='/api/v3/data-broker/watch-prospects'){
    const result=structuredClone(fixture.prospects),lane=q.get('lane')||'actionable'
    result.lane_membership=Object.fromEntries(result.lanes.flatMap(l=>[...l.items.map(r=>[r.symbol,l.id]),...l.overflow.map(s=>[s,l.id])]))
    for(const l of result.lanes){const pg=pageOf(l.items,q);l.items=l.id===lane?pg.items:[];if(l.id===lane)result.pagination=pg.pagination}
    return result
  }
  if(p==='/api/v3/data-broker/watch-curation'){
    const result=structuredClone(fixture.curation),mine=q.get('mine')||''
    const original=result.my_watchlist.rows
    result.my_watchlist.kind_counts={all:original.length,starred:original.filter(r=>r.starred).length}
    if(mine)result.my_watchlist.rows=original.filter(r=>mine==='starred'?r.starred:r.membership.some(m=>m.kind===mine))
    result.suggests.rows=result.suggests.rows.filter(r=>r.lane!=='expired'&&!['expired','invalidated'].includes(r.stage))
    result.suggests.universe_note='Eligible research universe; Prospects is a capped stage view.'
    for(const key of ['my_watchlist','suggests']){const pg=pageOf(result[key].rows,q);result[key].rows=pg.items;result[key].pagination=pg.pagination;result[key].count=pg.pagination.total}
    return result
  }
  if(p==='/api/v2/communications/health')return {mode:'SHADOW',ledger:{source:'fixture'},delivery_owned:false,owned_classes:[]}
  if(p==='/api/v2/communications/board')return {panels:[]}
  if(p==='/api/v2/communications/events')return {events:[message],hub:true,total:1,facets:{},categories:[],source:'fixture'}
  if(p==='/api/v2/communications/events/fixture-message')return {ok:true,event:message}
  if(p==='/api/v2/communications/deliveries/summary')return {schema:'CommunicationsDeliverySummary@v1',source:'fixture',as_of:clock,total:0}
  if(p==='/api/v2/communications/deliveries')return {deliveries:[],source:'fixture'}
  if(p==='/api/v2/communications/subjects')return {subjects:[],source:'fixture'}
  if(p==='/api/v2/communications/agents')return {subscriptions:[],receipts:[]}
  if(p==='/api/v2/communications/retention-summary')return {status:'ok',scope:'all_retained_ledger_rows',total:1300,byClass:{operational:1300},byKnowledge:{accepted:1300},categories:[]}
  if(p==='/api/v2/watch-directives')return {directives:[{id:7,kind:'ticker',label:'Fixture watch',status:'active',created_at:clock}],directive_count:1200,desk_suggestions:[],recent_hits:[],desk_suggestions_count:900,recent_hits_count:7000,hermes_staging:{total:900,undrained:900},pagination:{offset:0,limit:50,returned:1,total:1200,next_offset:1,has_more:true}}
  if(p==='/api/v2/watchpool'){const all=Array.from({length:120},(_,i)=>({id:i+1,symbol:`FX${i}`,strategy_id:'fixture strategy',current_status:i%2?'EXPIRED':'ACTIVE',origin_system:'fixture',bucket:'review'})),status=q.get('status')||'all',pg=pageOf(status==='all'?all:all.filter(r=>r.current_status===status),q,50);return {rows:pg.items,count:120,by_status:{ACTIVE:60,EXPIRED:60},pagination:pg.pagination}}
  if(p==='/api/v2/watch/directives/detail')return {directive:{id:7,label:'Fixture watch',kind:'ticker',status:'active',created_at:clock},hit_timeline_90d:[],alpha_events:[],children:[]}
  if(p==='/api/v2/watch/two-way-curation'||p==='/api/v2/watch/directives/merge-plan'||p==='/api/v2/screener-finds/candidates')return {}
  // Active Trader's motion strip (pre-existing read); the UI fails closed on an unavailable snapshot.
  if(p==='/api/v3/active-trader/motion')return {status:'unavailable',reason:'fixture: no motion snapshot'}
  unexpected.push(`GET ${p}`);return {ok:false,error:'Unregistered fixture read'}
}
try{
  browser=await chromium.launch({headless:true})
  for(const [width,height] of [[412,915],[390,844],[1440,1000]]){
    const context=await browser.newContext({viewport:{width,height},isMobile:width<820,hasTouch:width<820})
    const page=await context.newPage()
    page.on('pageerror',e=>errors.push(String(e)))
    await page.clock.install({time:new Date(clock)})
    await page.route('**/*',async route=>{
      const u=new URL(route.request().url())
      if(u.origin!==origin){blockedExternal.push(u.href);return route.abort()}
      if(!u.pathname.startsWith('/api/'))return route.continue()
      traffic.push({width,path:u.pathname,query:u.search,method:route.request().method()})
      return route.fulfill({contentType:'application/json',body:JSON.stringify(route.request().method()==='GET'?{ok:true,data:response(u,route.request())}:response(u,route.request()))})
    })
    const visible=async loc=>{await expect(loc).toBeVisible();const b=await loc.boundingBox();assert(b&&b.x>=-1&&b.y>=-1&&b.x+b.width<=width+1&&b.y+b.height<=height+1,JSON.stringify(b))}
    const tap=async loc=>{await loc.scrollIntoViewIfNeeded();await visible(loc);const b=await loc.boundingBox();if(width<820)assert(b.width>=44&&b.height>=44,JSON.stringify({target:await loc.innerText(),box:b}));if(width<820)await loc.tap();else await loc.click()}
    const shot=async name=>{await page.waitForLoadState('networkidle');const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert(!overflow,`Horizontal page scroll: ${name}/${width}`);await page.screenshot({path:path.join(output,`impl-w2-${name}-${width}.png`),fullPage:true,animations:'disabled'})}
    await page.goto(`${origin}/v3/active-trader?tab=Alerts`);await page.waitForLoadState('networkidle')
    assert(!traffic.some(r=>r.width===width&&r.path==='/api/v2/trade-ai/candidates'))
    await tap(page.getByRole('button',{name:'Review',exact:true}));await expect(page.getByTestId('shared-momentum-candidates')).toBeVisible()
    await tap(page.getByRole('button',{name:'Observation history',exact:true}).first());const history=page.getByRole('dialog',{name:'Candidate observation history'});await visible(history)
    assert(await history.evaluate(el=>el.contains(document.activeElement)))
    await shot('active-history');await page.goBack();await expect(history).toHaveCount(0)
    await tap(page.getByTestId('shared-candidates-filter-ALL'));await tap(page.getByLabel('List pages').getByRole('button',{name:'Next',exact:true}));await expect(page.locator('[data-symbol="FX20"]')).toBeVisible()
    await tap(page.getByTestId('shared-candidates-filter-CONFLICT'));await expect(page.locator('[data-symbol="FX0"]')).toBeVisible();await shot('active-filter')
    await tap(page.getByRole('button',{name:'Setups',exact:true}));const start=traffic.length;await page.clock.runFor(65_100);await page.waitForLoadState('networkidle');assert(!traffic.slice(start).some(r=>r.path==='/api/v2/trade-ai/candidates'))
    flows.push({width,page:'active',detail:true,browser_back:true,filter:true,primary_action:'observation history',inactive_poll_stopped:true})
    await page.goto(`${origin}/v3/communications?tab=events`);await page.locator('[data-feed-card]').first().waitFor()
    await tap(page.locator('[data-feed-card]').first());const drawer=page.getByTestId('comms-drawer');await visible(drawer);await shot('comms-detail')
    await tap(drawer.getByTestId('comms-drawer-actions').getByRole('button',{name:/^Acknowledge /}));await visible(page.getByText('Confirm: Acknowledge — 1 message',{exact:true}));await page.getByRole('button',{name:'Cancel',exact:true}).click()
    await tap(drawer.getByRole('button',{name:'Back to messages',exact:true}));await expect(drawer).toHaveCount(0)
    await tap(page.getByRole('button',{name:'Retention',exact:true}));await expect(page.getByText('1300',{exact:true}).first()).toBeVisible();const commStart=traffic.length;await page.clock.runFor(65_100);await page.waitForLoadState('networkidle');assert(!traffic.slice(commStart).some(r=>['/api/v2/communications/events','/api/v2/communications/deliveries','/api/v2/communications/agents'].includes(r.path)));await shot('comms-retention')
    flows.push({width,page:'comms',detail:true,back:true,filter:'URL tab',primary_action:'acknowledge opens confirmation',inactive_poll_stopped:true})
    for(const name of ['prospects','mine','suggests']){
      await page.goto(`${origin}/v3/${name}`)
      const open=page.locator('.watch-card-company button[title^="Open the "]').first();await open.waitFor();await tap(open)
      const detail=page.locator('.watch-card-detail:visible, [role="dialog"].mobile-detail-sheet:visible');await expect(detail).toBeVisible();await visible(width<820?detail:detail.locator('[data-testid="watch-detail"] > div').first());await shot(`${name}-detail`)
      const review=detail.getByTestId('watch-ask-cio'),hadReview=await review.count();if(hadReview){await tap(review);await expect(detail).toContainText(/queued|already/i)}
      await page.goBack();if(width<820)await expect(page.locator('.watch-card-detail:visible, [role="dialog"].mobile-detail-sheet:visible')).toHaveCount(0)
      if(name==='prospects'){const lane=page.getByTestId('watch-lane-forming');await tap(lane);await expect(lane).toHaveAttribute('aria-pressed','true')}
      if(name==='mine'){await tap(page.getByTestId('mine-kind-starred'));await expect(page.getByTestId('mine-kind-starred')).toHaveAttribute('aria-pressed','true')}
      if(name==='suggests'){const select=page.locator('select').first();await select.selectOption('10');await expect(select).toHaveValue('10')}
      await shot(`${name}-filter`);flows.push({width,page:name,detail:true,browser_back:true,filter:true,primary_action:hadReview?'review request':'view record'})
    }
    await page.goto(`${origin}/v3/pool`);await tap(page.locator('[data-directive-row]').first());const directive=page.getByRole('dialog',{name:'Watch directive'});await visible(directive);await shot('pool-detail');await page.goBack();await expect(directive).toHaveCount(0)
    const filterStart=traffic.length;await tap(page.getByRole('button',{name:'60 active',exact:true}));await expect.poll(()=>traffic.slice(filterStart).some(r=>r.path==='/api/v2/watchpool'&&r.query.includes('status=ACTIVE'))).toBe(true);await shot('pool-filter');flows.push({width,page:'pool',detail:true,browser_back:true,filter:true,primary_action:'open directive'})
    await context.close()
  }
  assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[])
  passed=true
}finally{
  if(browser)await browser.close()
  await new Promise(resolve=>server.close(resolve))
  fs.writeFileSync(path.join(output,'impl-w2-tap-receipt.json'),JSON.stringify({passed,browser_executed:Boolean(browser),clock,viewports:[[412,915],[390,844],[1440,1000]],flows,traffic,unexpected,blockedExternal,errors,source_hashes:hashes,production_requests:0,all_pages_server_rss_proven:false},null,2)+'\n')
}
