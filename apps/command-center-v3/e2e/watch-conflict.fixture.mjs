/** Shared conflict primitives only. This is not final rulebook or Watch-parent acceptance. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium, expect} from '@playwright/test'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fixturePath = path.join(app, 'e2e/fixtures/conflictEngine.fixture.json')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
const output = process.argv[2]; assert(output, 'Explicit output directory required')
const bundle = await build({metafile: true, stdin: {contents: `
import React,{useState}from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,useSearchParams,Link,Routes,Route}from'react-router-dom';
import ConflictLine from './src/components/conflicts/ConflictLine';import ConflictSheet,{useConflictSheet}from './src/components/conflicts/ConflictSheet';
import './src/styles/tokens.css';const specimen=${JSON.stringify(fixture.section)};
function Fixture(){const selected=useConflictSheet();const[params,setParams]=useSearchParams();const mode=params.get('mode');
const section=mode==='gap'?{findings:[],headline:null,gap:{reason:'engine output is unavailable'}}:mode==='clear'?{findings:[],headline:null,gap:null}:specimen;
return <><h1>Shared conflict UI protocol fixture</h1><p>Schema sample only; final rulebook and Watch integration are separate.</p>
<label>Fixture view <select aria-label="Fixture view" value={mode||'open'} onChange={e=>{const p=new URLSearchParams(params);p.set('mode',e.target.value);setParams(p)}}><option value="open">Open</option><option value="clear">Clear</option><option value="gap">Unavailable</option></select></label>
<ConflictLine section={section} onOpen={selected.open}/>{selected.key&&<ConflictSheet title="Recorded finding" section={section} onBack={selected.close}>
<Link style={{display:'flex',alignItems:'center',minHeight:44,width:'100%'}} to="/evidence">Open recorded evidence</Link></ConflictSheet>}</>}
createRoot(document.getElementById('root')).render(<BrowserRouter><Routes><Route path="/" element={<Fixture/>}/><Route path="/evidence" element={<h1>Recorded evidence route</h1>}/></Routes></BrowserRouter>);
`,resolveDir: app,sourcefile: 'conflict-protocol.tsx',loader: 'tsx'},bundle: true,write: false,outfile: 'fixture.js',define: {'process.env.NODE_ENV': '"production"'},logLevel: 'silent'})
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
const sha = name => crypto.createHash('sha256').update(fs.readFileSync(name)).digest('hex')
const source = Object.fromEntries(Object.keys(bundle.metafile.inputs).map(p => path.resolve(app,p)).filter(p => p.startsWith(path.join(app,'src')+path.sep)).map(p=>[path.relative(app,p),sha(p)]))
fs.mkdirSync(output,{recursive:true})
const browser = await chromium.launch({headless:true}), cases=[]
try {
  for (const width of [1440,412,390]) {
    const height=width===412?915:width===390?844:1000
    const context=await browser.newContext({viewport:{width,height},hasTouch:width<820}),page=await context.newPage()
    const traffic={external:[],mutations:[],unexpected:[],errors:[]}, selectedGets=[]
    let recordState='OPEN'
    const finding=fixture.section.findings[0]
    const savedRecord=()=>({...finding,schema:'ConflictRecord@v1',state:recordState,subject:{kind:'security',id:'fixture-guid-schd',label:'SCHD'},opened_at:fixture.clock,updated_at:fixture.clock,revision:3,decision:recordState==='DECIDED'?{schema:'ConflictDecision@v1',actor_kind:'cio',actor:'CIO',chosen_side:'HOLD',reason:'Fixture decision with recorded evidence',evidence_refs:['fixture:evidence'],expires_at:'2026-10-25T23:00:00Z'}:null,history:[{schema:'ConflictEvent@v1',key:finding.key,event:'opened',at:fixture.clock},...(recordState==='OPEN'?[]:[{schema:'ConflictEvent@v1',key:finding.key,event:'review_queued',at:fixture.clock,request_id:'fixture-request'}])]})
    page.on('pageerror',e=>traffic.errors.push(String(e)))
    await page.clock.install({time:new Date(fixture.clock)})
    await page.route('**/*',route=>{
      const req=route.request(),url=new URL(req.url())
      if(url.origin!=='http://conflict-ui-fixture.test'){traffic.external.push(url.href);return route.abort()}
      if(req.method()!=='GET'){traffic.mutations.push(req.method()+' '+url.pathname);return route.abort()}
      if(url.pathname.startsWith('/api/v3/conflicts/')){
        const key=decodeURIComponent(url.pathname.slice('/api/v3/conflicts/'.length));selectedGets.push(key)
        return route.fulfill({status:key===finding.key?200:404,contentType:'application/json',body:JSON.stringify(key===finding.key?savedRecord():{error:'not found'})})
      }
      if(!req.isNavigationRequest()){traffic.unexpected.push(url.pathname);return route.abort()}
      return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{margin:0;padding:16px;background:var(--bg-0);color:var(--text-0);font:14px sans-serif}select{min-height:44px}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
    })
    const tap=async locator=>{const box=await locator.boundingBox();if(width<820){assert(box&&box.width>=44&&box.height>=44);await locator.tap()}else await locator.click()}
    const inView=async locator=>{await expect(locator).toBeVisible();const b=await locator.boundingBox();assert(b&&b.x>=-1&&b.y>=-1&&b.x+b.width<=width+1&&b.y+b.height<=height+1,JSON.stringify(b))}
    await page.goto('http://conflict-ui-fixture.test/?source=fixture')
    await expect(page.getByTestId('conflict-headline')).toHaveText(fixture.section.headline)
    await tap(page.getByTestId('conflict-line'))
    assert.equal(new URL(page.url()).searchParams.get('conflict'),fixture.section.findings[0].key)
    const dialog=page.getByRole('dialog',{name:'Recorded finding'})
    await inView(dialog)
    await expect(dialog.getByTestId('conflict-record-state')).toHaveAttribute('data-state','OPEN')
    await expect(dialog).toContainText('Schwab Roth IRA')
    await expect(dialog).not.toContainText('schwab_roth_ira')
    await inView(dialog.getByRole('button',{name:'← Back'}))
    assert(await dialog.evaluate(el=>el.contains(document.activeElement)),'Focus enters sheet')
    await page.screenshot({path:path.join(output,`impl-conflict-shared-open-${width}.png`),fullPage:width>=820,animations:'disabled'})
    recordState='UNDER_REVIEW';await page.clock.runFor(15_000)
    await expect(dialog.getByTestId('conflict-record-state')).toHaveText('Review in progress')
    await expect(dialog).toContainText('Review queued')
    recordState='DECIDED';await page.clock.runFor(15_000)
    await expect(dialog.getByTestId('conflict-record-state')).toHaveText('Decision recorded · awaiting engine re-evaluation')
    await expect(dialog).toContainText('Fixture decision with recorded evidence')
    await expect(dialog.getByTestId('conflict-record-state')).not.toContainText('Cleared')
    recordState='CLEARED';await page.clock.runFor(15_000)
    await expect(dialog.getByTestId('conflict-record-state')).toHaveText('Cleared by the engine')
    const evidence=dialog.getByRole('link',{name:'Open recorded evidence'})
    await evidence.scrollIntoViewIfNeeded();await inView(evidence);await tap(evidence)
    await inView(page.getByRole('heading',{name:'Recorded evidence route'}))
    await page.goBack();await inView(page.getByRole('dialog',{name:'Recorded finding'}))
    await page.goBack();await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('combobox',{name:'Fixture view'}).selectOption('clear')
    await expect(page.getByTestId('conflict-line')).toHaveCount(0)
    await expect(page.getByTestId('conflict-gap')).toHaveCount(0)
    await page.getByRole('combobox',{name:'Fixture view'}).selectOption('gap')
    await inView(page.getByTestId('conflict-gap'))
    await expect(page.getByTestId('conflict-line')).toHaveCount(0)
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal page scroll')
    await page.screenshot({path:path.join(output,`impl-conflict-shared-gap-${width}.png`),fullPage:width>=820,animations:'disabled'})
    assert.deepEqual(traffic,{external:[],mutations:[],unexpected:[],errors:[]})
    assert(selectedGets.length>=4&&selectedGets.every(key=>key===finding.key),'Only the selected encoded key is read')
    cases.push({width,height,tap:true,url_key:true,focus:true,back:true,primary_evidence_route:true,gap_not_zero:true,ledger_state_history_decision:true,selected_gets:selectedGets,traffic})
    await context.close()
  }
} finally {await browser.close()}
for(const [file,digest]of Object.entries(source))assert.equal(sha(path.join(app,file)),digest)
fs.writeFileSync(path.join(output,'conflict-ui-receipts.json'),JSON.stringify({scope:fixture.acceptance_scope||'Shared UI protocol only; not policy or Watch acceptance',fixture_sha256:sha(fixturePath),source_sha256:source,cases},null,2)+'\n')
console.log('Shared conflict primitives: 1440/412/390 tap, viewport, focus, URL, Back, evidence and missing-engine gap passed; policy/Watch integration not claimed')
