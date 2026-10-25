/** Actual Journey presentation, generated broker-projection fixture, intercepted transport only. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
import {build} from 'esbuild'
import {chromium,expect} from '@playwright/test'
import {TRADE_JOURNEYS_FIXTURE} from '../src/fixtures/tradeJourneys.fixture.ts'

const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),out=process.argv[2]
assert(out,'Explicit screenshot/receipt directory required')
const input=process.argv[3]?path.resolve(process.argv[3]):path.join(app,'src/fixtures/tradeJourneys.fixture.ts')
const raw=process.argv[3]?JSON.parse(fs.readFileSync(input,'utf8')):TRADE_JOURNEYS_FIXTURE
const payload=raw.journeys?.fresh??raw
assert.equal(payload.schema,'TradeJourneys@v1');assert(payload.journeys.length>1&&payload.as_of)
const chosen=payload.journeys.find(j=>!j.chart)??payload.journeys[payload.journeys.length-1]
const other=payload.journeys.find(j=>j.trade_id!==chosen.trade_id&&j.chart)??payload.journeys.find(j=>j.trade_id!==chosen.trade_id)
const bundle=await build({metafile:true,stdin:{contents:`import React from'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';import TradeJourney from'./src/pages/TradeJourney';import'./src/styles/tokens.css';import'./src/index.css';createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><TradeJourney/></BrowserRouter>);`,loader:'tsx',sourcefile:'journey-phone-fixture.tsx',resolveDir:app},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files=[...Object.keys(bundle.metafile.inputs).map(name=>path.resolve(app,name)).filter(file=>file.startsWith(path.join(app,'src')+path.sep)),input,fileURLToPath(import.meta.url)]
const hashes=Object.fromEntries(files.map(file=>[file,sha(file)]))
const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script'),css=bundle.outputFiles.find(file=>file.path.endsWith('.css'))?.text||''
fs.mkdirSync(out,{recursive:true})
const browser=await chromium.launch({headless:true}),cases=[]
try{
 for(const[width,height]of[[1440,1100],[412,915],[390,844]])for(const mode of ['navigation','direct-link','wrong-detail']){
  const phone=width<=820,context=await browser.newContext({viewport:{width,height},hasTouch:phone,isMobile:phone}),page=await context.newPage()
  const traffic={reads:[],unexpected:[],external:[],mutations:[],errors:[]},taps=[],geometry=[]
  await page.clock.setFixedTime(new Date(payload.as_of));page.on('pageerror',e=>traffic.errors.push(String(e)))
  await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
  await page.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url())
   if(u.origin!=='http://journey-mobile-fixture.test'){traffic.external.push(u.origin+u.pathname);return route.abort()}
   if(req.method()!=='GET'){traffic.mutations.push(req.method()+' '+u.pathname);return route.abort()}
   if(req.isNavigationRequest())return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:16px;box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
   traffic.reads.push(u.pathname)
   let body
   if(u.pathname==='/api/v3/data-broker/trade-journeys')body=payload
   else if(u.pathname.startsWith('/api/v3/data-broker/trade-journeys/')){
    const id=decodeURIComponent(u.pathname.slice('/api/v3/data-broker/trade-journeys/'.length))
    const journey=payload.journeys.find(j=>j.trade_id===id)
    if(journey)body={...payload,journeys:undefined,journey:mode==='wrong-detail'?other:journey}
   }
   if(!body){traffic.unexpected.push(u.pathname);return route.abort()}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(body)})
  })
  const activate=async(locator,name)=>{await locator.scrollIntoViewIfNeeded();const r=await locator.boundingBox();assert(r&&r.x>=0&&r.y>=0&&r.x+r.width<=width+1&&r.y+r.height<=height+1,name+' outside viewport');if(phone){assert(r.width>=44&&r.height>=44,JSON.stringify({name,...r}));await locator.tap();taps.push({name,...r})}else await locator.click()}
  const capture=async(state)=>{if(phone){const areas=await page.evaluate(()=>{const sheet=document.querySelector('[data-testid="tj-detail-sheet"]');const root=sheet&&getComputedStyle(sheet).display!=='none'?sheet:document.querySelector('[data-testid="trade-journey"]');return [...root.querySelectorAll('button:not(:disabled),a[href],summary')].map(node=>{const r=node.getBoundingClientRect();return r.width&&r.height&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth?{name:node.textContent?.slice(0,60),width:r.width,height:r.height}:null}).filter(Boolean)});for(const area of areas)assert(area.width>=44&&area.height>=44,JSON.stringify({state,...area}));geometry.push({state,areas})}const g=await page.evaluate(()=>({width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth}));assert(g.document<=g.width+1,JSON.stringify(g));geometry.push({state,...g});await page.evaluate(()=>document.activeElement instanceof HTMLElement&&document.activeElement.blur());await page.waitForTimeout(350);await page.screenshot({path:path.join(out,`impl-journeys-mobile-${mode}-${state}-${width}.png`),fullPage:!phone,animations:'disabled'})}
  const query=new URLSearchParams({tab:'journeys',keep:'retained'});if(mode!=='navigation')query.set('trade',chosen.trade_id)
  await page.goto(`http://journey-mobile-fixture.test/v3/journal?${query}`)
  await expect(page.getByTestId('tj-row')).toHaveCount(payload.journeys.length)
  const sheet=page.getByTestId('tj-detail-sheet')
  if(mode==='navigation'){
   if(phone){await expect(sheet).toBeHidden();assert(!traffic.reads.some(p=>p.startsWith('/api/v3/data-broker/trade-journeys/')),'Phone list must not silently select a trade')}
   const row=page.locator(`[data-testid="tj-row"][data-trade-id=${JSON.stringify(chosen.trade_id)}]`)
   await activate(row.getByTestId('tj-open-journey'),'Journey primary action')
  }
  assert.equal(new URL(page.url()).searchParams.get('trade'),chosen.trade_id);assert.equal(new URL(page.url()).searchParams.get('keep'),'retained')
  await expect(sheet).toBeVisible();await expect(page.getByTestId('tj-detail')).toContainText(`${chosen.symbol} · ${chosen.account_label||'Unlabelled account'}`)
  if(mode==='wrong-detail'){
   await expect(page.getByText('Detail update could not be matched to this trade — showing its recorded list facts.')).toBeVisible()
   await expect(page.getByTestId('tj-chart')).toHaveCount(chosen.chart?1:0)
  }
  if(phone){const r=await sheet.boundingBox();assert(r&&r.x===0&&r.y===0&&r.width===width&&r.height===height);assert(await sheet.evaluate(node=>node.contains(document.activeElement)),'Focus must enter the phone detail');await expect(sheet).toHaveAttribute('aria-modal','true')}
  await capture('detail')
  if(phone){
   await activate(page.getByTestId('tj-detail-back'),'Detail Back');await expect(sheet).toBeHidden();assert.equal(new URL(page.url()).searchParams.get('trade'),null);assert.equal(new URL(page.url()).searchParams.get('keep'),'retained')
   if(mode==='navigation'){
    await page.goForward();await expect(sheet).toBeVisible();await page.goBack();await expect(sheet).toBeHidden()
    const expected=payload.journeys.filter(j=>j.status==='open')
    await activate(page.getByTestId('tj-filter-open'),'Open filter');await expect(page.getByTestId('tj-row')).toHaveCount(expected.length);assert.equal(new URL(page.url()).searchParams.get('filter'),'open')
    if(expected.length){const row=page.getByTestId('tj-row').first();await activate(row.getByTestId('tj-open-journey'),'Filtered Journey');await expect(sheet).toBeVisible();await activate(page.getByTestId('tj-detail-back'),'Filtered Back');await expect(sheet).toBeHidden();await expect(page.getByTestId('tj-filter-open')).toHaveAttribute('aria-pressed','true')}
   }
   await capture('back')
  }
  assert.deepEqual({...traffic,reads:[]},{reads:[],unexpected:[],external:[],mutations:[],errors:[]})
  cases.push({width,height,mode,taps,geometry,source_rows:payload.journeys.length,selected_trade:chosen.trade_id,traffic});await context.close()
 }
}finally{await browser.close()}
for(const[file,digest]of Object.entries(hashes))assert.equal(sha(file),digest,`Source changed during proof:${file}`)
fs.writeFileSync(path.join(out,'impl-journeys-mobile-receipts.json'),JSON.stringify({fixture:true,boundary:'Presentation/navigation fixture proof only; not final A/C integration or production acceptance',input,input_sha256:sha(input),source:{head:execFileSync('git',['rev-parse','HEAD'],{cwd:app,encoding:'utf8'}).trim(),file_sha256:hashes},cases},null,2)+'\n')
console.log(`Journey phone navigation:${cases.length} cases passed; no live/mutating/provider traffic`)
