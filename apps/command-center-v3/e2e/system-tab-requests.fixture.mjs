/** Actual SystemHub + real useApi on isolated synthetic GETs; no HTTP server or provider access. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
import {build} from 'esbuild'
import {chromium,expect} from '@playwright/test'
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const input=path.join(app,'e2e/fixtures/systemTabRequests.fixture.json'), f=JSON.parse(fs.readFileSync(input,'utf8'))
const output=process.argv[2]; assert(output,'Explicit evidence directory required')
const bundle=await build({metafile:true,stdin:{contents:`import React,{useEffect} from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,useNavigate}from'react-router-dom';import SystemHub from './src/pages/SystemHub';import './src/styles/tokens.css';import './src/index.css';function Fixture(){const navigate=useNavigate();useEffect(()=>{window.fixtureNavigate=navigate},[navigate]);return <SystemHub onDrill={()=>{}}/>};createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Fixture/></BrowserRouter>);`,resolveDir:app,sourcefile:'system-tab-fixture.tsx',loader:'tsx'},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files=[...Object.keys(bundle.metafile.inputs).map(name=>path.resolve(app,name)).filter(name=>name.startsWith(path.join(app,'src')+path.sep)),input,fileURLToPath(import.meta.url),path.join(app,'package.json'),path.join(app,'package-lock.json')]
const sourceHashes=Object.fromEntries(files.map(file=>[file,sha(file)]))
const testedSource={head:execFileSync('git',['rev-parse','HEAD'],{cwd:app,encoding:'utf8'}).trim(),working_patch_sha256:crypto.createHash('sha256').update(execFileSync('git',['diff','HEAD'],{cwd:app})).digest('hex'),file_sha256:sourceHashes}
const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script'), css=bundle.outputFiles.find(file=>file.path.endsWith('.css'))?.text||''
fs.mkdirSync(output,{recursive:true})
const browser=await chromium.launch({headless:true}), receipts=[]
try {
  for(const width of [1440,412]) {
    const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage()
    const traffic={reads:[],mutations:[],external:[],unexpected:[],errors:[]}, phases=[]
    page.on('pageerror',e=>traffic.errors.push(String(e)))
    await page.clock.install({time:new Date(f.clock)})
    await page.routeWebSocket('**/*',ws=>{traffic.external.push(ws.url());ws.close()})
    await page.route('**/*',route=>{
      const request=route.request(),u=new URL(request.url())
      if(u.origin!=='http://system-tab-fixture.test'){traffic.external.push(u.origin+u.pathname);return route.abort()}
      if(request.method()!=='GET'){traffic.mutations.push(request.method()+' '+u.pathname);return route.abort()}
      if(request.isNavigationRequest())return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{background:var(--bg-0);color:var(--text-0);margin:0}#root{padding:20px}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
      traffic.reads.push(u.pathname)
      if(!Object.hasOwn(f.responses,u.pathname)){traffic.unexpected.push(u.pathname);return route.abort()}
      return route.fulfill({contentType:'application/json',body:JSON.stringify(f.responses[u.pathname])})
    })
    const hub=page.getByTestId('system-hub'), tabs=page.getByTestId('system-tabs')
    const scope=async(tab,since)=>{
      await expect(hub).toHaveAttribute('data-active-tab',tab)
      await expect(tabs.getByRole('button',{name:tab,exact:true})).toHaveAttribute('aria-pressed','true')
      const expected=f.tabs[tab]
      await expect.poll(()=>expected.every(endpoint=>traffic.reads.slice(since).includes(endpoint))).toBe(true)
      await page.waitForLoadState('networkidle')
      const allowed=[f.header,...expected], started=traffic.reads.slice(since)
      assert(started.every(endpoint=>allowed.includes(endpoint)),JSON.stringify({tab,started,allowed}))
      const pollStart=traffic.reads.length
      await page.clock.runFor(180_100)
      await page.waitForLoadState('networkidle')
      const polled=traffic.reads.slice(pollStart)
      assert(polled.includes(f.header),'Visible shared header must keep polling')
      assert(polled.every(endpoint=>allowed.includes(endpoint)),JSON.stringify({tab,polled,allowed}))
      phases.push({tab,started,polled})
      await page.evaluate(()=>document.activeElement instanceof HTMLElement&&document.activeElement.blur())
      await page.screenshot({path:path.join(output,`impl-system-tabs-${tab.toLowerCase()}-${width}.png`),fullPage:true,animations:'disabled'})
    }
    await page.goto('http://system-tab-fixture.test/v3/system?tab=pipeline&query=first-fixture&focus=fixture-context&source=report')
    await scope('Pipeline',0)
    await expect(hub).toContainText('11 timers · 7 crons · 5 services · 3 LLM jobs')
    const firstCount=traffic.reads.length
    await tabs.getByRole('button',{name:'LLM',exact:true}).click()
    await scope('LLM',firstCount)
    let url=new URL(page.url()); assert.equal(url.searchParams.get('tab'),'LLM'); assert.equal(url.searchParams.get('query'),'first-fixture'); assert.equal(url.searchParams.get('focus'),'fixture-context');assert.equal(url.searchParams.get('source'),'report')
    await page.goBack();await expect(hub).toHaveAttribute('data-active-tab','Pipeline')
    await page.goForward();await expect(hub).toHaveAttribute('data-active-tab','LLM')
    const appsStart=traffic.reads.length
    await page.evaluate(()=>window.fixtureNavigate('/system?tab=apps&query=second-fixture&focus=fixture-context&source=report'))
    await scope('Apps',appsStart)
    await expect(hub.getByText(/Focused from Reports:/)).toContainText('second-fixture')
    for(const tab of ['Crons','SIEM','Access','Queue','Jobs','Admin','Brokers']){
      const since=traffic.reads.length;await tabs.getByRole('button',{name:tab,exact:true}).click();await scope(tab,since)
    }
    await page.evaluate(()=>window.fixtureNavigate('/system?tab=Pipeline&focus=youtube-cookies&query=cookie-status-fixture'))
    await expect(hub).toHaveAttribute('data-active-tab','Pipeline')
    await expect(page.getByPlaceholder('# Netscape HTTP Cookie File…')).toBeVisible()
    await expect(hub.getByText(/Focused from Reports:/)).toContainText('cookie-status-fixture')
    await tabs.getByRole('button',{name:'LLM',exact:true}).click();await expect(hub).toHaveAttribute('data-active-tab','LLM')
    assert.equal(new URL(page.url()).searchParams.get('focus'),'youtube-cookies')
    assert.deepEqual({...traffic,reads:[]},{reads:[],mutations:[],external:[],unexpected:[],errors:[]})
    receipts.push({width,phases,url_state:{back_forward:true,live_query:true,cookie_focus:true,preserved_context:true},traffic})
    await context.close()
  }
} finally {await browser.close()}
for(const [file,digest] of Object.entries(sourceHashes))assert.equal(sha(file),digest,`Source changed during proof:${file}`)
fs.writeFileSync(path.join(output,'system-tab-receipts.json'),JSON.stringify({fixture:true,clock:f.clock,tested_source:testedSource,input_sha256:sha(input),cases:receipts},null,2)+'\n')
console.log(`System actual-component request proof:${receipts.length} viewports ×10 tab phases passed; no unexpected/external/mutating traffic`)
