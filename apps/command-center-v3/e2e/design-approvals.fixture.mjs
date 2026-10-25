/** Approvals → Designs fixture proof (design workflow, AGENTS.md §28.13 proposed). Synthetic data only: every /api
 * request is intercepted; no production server, ledger, private store, credential, broker or job is reachable.
 *   node e2e/design-approvals.fixture.mjs <fresh evidence dir>
 * Proves at 1440 / 412 / 390: Designs tab lists a PROPOSED version, its three mockups load through the authenticated
 * asset route, one-tap Approve and Reject-with-reason POST the exact version + fingerprint, phone detail is a
 * full-screen sheet with ← Back, tap targets ≥ 44 px, no sideways scroll, Board 19 "Decided recently" shows titles,
 * outcomes and ET dates (no raw ISO in the design panels; the shared DeskPage source clock still prints a raw as_of — pre-existing), and an agent-caller refusal is shown in plain words.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import zlib from 'node:zlib'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium,expect} from '@playwright/test'

const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const output=process.argv[2]
assert(output,'Explicit fresh evidence directory required')
fs.mkdirSync(output,{recursive:false})
const clock='2026-10-26T14:00:00Z'

// A small solid PNG (synthetic mockup stand-in), encoded here so no image file is committed.
function crc32(buf){let c,crc=0xffffffff;for(let n=0;n<buf.length;n++){c=(crc^buf[n])&0xff;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;crc=(crc>>>8)^c}return (crc^0xffffffff)>>>0}
function png(w,h,[r,g,b]){const chunk=(t,d)=>{const len=Buffer.alloc(4);len.writeUInt32BE(d.length);const td=Buffer.concat([Buffer.from(t),d]);const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(td));return Buffer.concat([len,td,crc])}
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(w,0);ihdr.writeUInt32BE(h,4);ihdr[8]=8;ihdr[9]=2
  const raw=Buffer.alloc((w*3+1)*h);for(let y=0;y<h;y++){raw[y*(w*3+1)]=0;for(let x=0;x<w;x++){const o=y*(w*3+1)+1+x*3;raw[o]=r;raw[o+1]=g;raw[o+2]=b}}
  return Buffer.concat([Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]),chunk('IHDR',ihdr),chunk('IDAT',zlib.deflateSync(raw)),chunk('IEND',Buffer.alloc(0))])}
const images={1440:png(144,90,[40,60,90]),412:png(41,91,[40,90,60]),390:png(39,84,[90,60,40])}

const bundle=await build({stdin:{contents:`import React from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';import ApprovalsHub from'./src/pages/ApprovalsHub';import'./src/styles/tokens.css';import'./src/index.css';createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><div className="app-shell cc-terminal-ui" data-theme="dark"><main style={{padding:12,minWidth:0}}><Routes><Route path="approvals" element={<ApprovalsHub/>}/><Route path="approvals/:id" element={<ApprovalsHub/>}/></Routes></main></div></BrowserRouter>);`,resolveDir:app,sourcefile:'design-approvals-fixture.tsx',loader:'tsx'},bundle:true,write:false,outfile:'fixture.js',define:{'process.env.NODE_ENV':'"production"','import.meta.env.DEV':'false'},logLevel:'silent'})
const html=`<!doctype html><html data-theme="dark"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${bundle.outputFiles.find(f=>f.path.endsWith('.css'))?.text||''}body{margin:0;background:var(--bg-0);color:var(--text-0)}</style><div id="root"></div><script>${bundle.outputFiles.find(f=>f.path.endsWith('.js')).text.replace(/<\/script/gi,'<\\/script')}</script>`
const server=http.createServer((req,res)=>{if(req.url.startsWith('/api/')){res.writeHead(503,{'Content-Type':'application/json'});res.end('{"ok":false,"error":"fixture interceptor required"}')}else{res.writeHead(200,{'Content-Type':'text/html'});res.end(html)}})
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve)})
const origin=`http://127.0.0.1:${server.address().port}`

const FP='f'.repeat(64)
const proposed=()=>({id:'design-version:trading/v002',page:'trading',page_title:'Trading',version:'v002',title:'Trading: compact phone header (synthetic fixture)',state:'PROPOSED',fingerprint:FP,created:'2026-10-26',proposed_by:'agent:fixture',
  removals:[{action:'hide',kind:'panel',label:'Scanner'}],spec:'# Trading v002 (fixture)\n\n## Removals, hides and moves\n\n- hide: panel "Scanner" — behind a tap\n',
  images:[1440,412,390].map(w=>({path:`v002/mockups/mockup-${w}.png`,width:w,sha256:String(w).padEnd(64,'0')})),mockup_files:3})
const decided=[{id:'backfill:handoffs/desks-redesign-20261024/SPEC.md',title:'Desk + page mockups (desk boards)',decision:'APPROVE',outcome:'Approved',at:'2026-10-24',actor:'operator',recorded:'recorded in handoff'},
  {id:'backfill:handoffs/site-audit-20261024/SPEC.md',title:'Site fix package',decision:'APPROVE',outcome:'Approved',at:'2026-10-24',actor:'operator',recorded:'recorded in handoff'}]
let scenario='operator',posts=[],traffic=[],unexpected=[],errors=[],flows=[]
function design(){return {proposed:[proposed()],dsn_proposed:[{id:'DSN-20261026-fixture',title:'Fixture design document',path:'docs/designs/DSN-20261026-fixture.md',approval:null,href:'/approvals/design%3ADSN-20261026-fixture'}],
  decided_recently:decided,counts:{proposed:1,dsn_proposed:1},complete:true,gaps:[],as_of:clock,can_decide:scenario!=='reader',signature:'hash-chained ledger row + authenticated operator identity (not a cryptographic signature)'}}
function respond(u,req){
  const p=u.pathname,q=u.searchParams
  if(req.method()==='POST'){
    if(p==='/api/v2/design/decide'){const b=req.postDataJSON();posts.push(b);if(scenario==='agent')return [403,{ok:false,error:'AGENT_CALLER_REFUSED'}]
      return [200,{ok:true,data:{row:{event:'DECIDED',kind:'DESIGN',decision:b.decision},replayed:false,mirror:'pages/trading/v002/decision.json'}}]}
    unexpected.push(`POST ${p}`);return [404,{ok:false,error:'NOT_FOUND'}]
  }
  if(p==='/api/v2/design/approvals')return [200,{ok:true,data:design()}]
  if(p==='/api/v2/design/asset'){const w=Number((q.get('path')||'').match(/(1440|412|390)/)?.[1]);return [200,{ok:true,data:{page:'trading',version:'v002',path:q.get('path'),mime:'image/png',width:w,image:'data:image/png;base64,'+images[w].toString('base64')}}]}
  if(p==='/api/v2/governance/approvals')return [200,{ok:true,data:{items:[],pending_count:0,known_pending_count:0,complete:true,gaps:[],as_of:clock,filtered_count:0,offset:0,
    recent:[{actor:'tailnet:operator',item_id:'policy:1',kind:'POLICY',decision:'REQUEST_CHANGES',document_sha:'a'.repeat(64),at:'2026-10-25T16:30:00+00:00',comment:''}]}}]
  unexpected.push(`GET ${p}`);return [503,{ok:false,error:'Unregistered fixture read'}]
}
let browser,passed=false
try{
  browser=await chromium.launch({headless:true})
  for(const [width,height] of [[1440,1000],[412,915],[390,844]]){
    for(const sc of ['operator','agent']){
      scenario=sc;posts=[]
      const context=await browser.newContext({viewport:{width,height},isMobile:width<820,hasTouch:width<820,colorScheme:'dark'})
      const page=await context.newPage()
      page.on('pageerror',e=>errors.push(String(e)))
      await page.clock.install({time:new Date(clock)})
      await page.route('**/*',async route=>{const u=new URL(route.request().url());if(u.origin!==origin)return route.abort();if(!u.pathname.startsWith('/api/'))return route.continue()
        traffic.push({width,scenario:sc,method:route.request().method(),path:u.pathname});const [status,body]=respond(u,route.request());return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)})})
      const tap=async loc=>{await loc.scrollIntoViewIfNeeded();await expect(loc).toBeVisible();const b=await loc.boundingBox();if(width<820)assert(b.width>=44&&b.height>=44,JSON.stringify({t:await loc.innerText(),b}));if(width<820)await loc.tap();else await loc.click()}
      const noOverflow=async name=>assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`horizontal scroll ${name} ${width}`)
      const noIso=async name=>{const t=(await page.locator("[data-testid=design-approvals],[data-testid=decided-recently],[role=dialog]").allInnerTexts()).join("\n");const m=t.match(/.{0,60}\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.{0,20}/);assert(!m,`raw ISO ${name} ${width}: ${m?.[0]}`)}
      const shot=async name=>{await noOverflow(name);await noIso(name);await page.screenshot({path:path.join(output,`impl-design-approvals-${name}-${width}.png`),fullPage:true,animations:'disabled'})}
      await page.goto(`${origin}/v3/approvals?tab=DESIGN`)
      const list=page.getByTestId('design-approvals');await expect(list.getByTestId('design-card')).toHaveCount(1)
      const recent=page.getByTestId('decided-recently')
      await expect(recent).toContainText('Desk + page mockups (desk boards)');await expect(recent).toContainText('Oct 24');await expect(recent).toContainText('recorded in handoff')
      await expect(recent).toContainText('Policy decision');await expect(recent).toContainText('Changes requested')
      await expect(list.getByRole('link',{name:'Read & decide'})).toHaveAttribute('href','/v3/approvals/design%3ADSN-20261026-fixture')
      if(sc==='operator')await shot('list')
      await tap(list.getByRole('button',{name:'Review v002'}))
      const detail=width<820?page.getByRole('dialog',{name:'Trading v002'}):page.getByTestId('design-detail')
      await expect(detail).toBeVisible()
      if(width<820){const b=await detail.boundingBox();assert(b.x<=1&&b.y<=1&&b.width>=width-2&&b.height>=height-2,'phone detail must be a full-screen sheet '+JSON.stringify(b))}
      const imgs=detail.locator('img');await expect(imgs).toHaveCount(3)
      for(let i=0;i<3;i++)await expect.poll(()=>imgs.nth(i).evaluate(el=>el.complete&&el.naturalWidth>0)).toBe(true)
      await expect(detail).toContainText('hide panel “Scanner”')
      if(sc==='operator'){
        await shot('detail')
        await tap(detail.getByRole('button',{name:'Reject…'}))
        const reject=detail.getByRole('button',{name:'Reject v002'});await expect(reject).toBeDisabled()
        await detail.getByLabel('Reject reason').fill('Header still covers the list')
        await tap(reject);await expect(page.getByTestId('design-decided-notice')).toHaveText('Trading v002 rejected and recorded in the decisions ledger.')
        assert.deepEqual(posts.at(-1),{...posts.at(-1),page:'trading',version:'v002',fingerprint:FP,decision:'REJECT',reason:'Header still covers the list'})
        assert.match(posts.at(-1).request_id,/^design-[A-Za-z0-9-]{8,}$/)
        if(width<820)await expect(page.getByRole('dialog',{name:'Trading v002'})).toHaveCount(0)
        await tap(list.getByRole('button',{name:'Review v002'}))  // the fixture keeps serving the card; production removes it
        const d2=width<820?page.getByRole('dialog',{name:'Trading v002'}):page.getByTestId('design-detail')
        await tap(d2.getByRole('button',{name:'Approve v002'}))
        await expect.poll(()=>posts.length).toBe(2)
        await expect(page.getByTestId('design-decided-notice')).toHaveText('Trading v002 approved and recorded in the decisions ledger.')
        assert.equal(posts[1].decision,'APPROVE');assert.equal(posts[1].reason,'');assert.equal(posts[1].fingerprint,FP)
        await shot('decided')
        flows.push({width,scenario:sc,reject_with_reason:true,approve_one_tap:true,images_loaded:3})
      } else {
        await tap(detail.getByRole('button',{name:'Approve v002'}))
        await expect(detail.getByRole('alert')).toContainText('Only your authenticated operator session can record a decision.')
        await shot('agent-refused')
        if(width<820){await tap(page.getByRole('button',{name:'← Back'}));await expect(page.getByRole('dialog',{name:'Trading v002'})).toHaveCount(0);await expect(list.getByTestId('design-card')).toBeVisible()}
        flows.push({width,scenario:sc,refusal_shown:true,back:width<820})
      }
      await context.close()
    }
  }
  assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[])
  passed=true
}finally{
  if(browser)await browser.close()
  await new Promise(resolve=>server.close(resolve))
  fs.writeFileSync(path.join(output,'impl-design-approvals-receipt.json'),JSON.stringify({passed,clock,viewports:[[1440,1000],[412,915],[390,844]],flows,traffic,unexpected,errors,synthetic_data_only:true,production_requests:0},null,2)+'\n')
}
console.log(passed?'design-approvals fixture: PASS':'design-approvals fixture: FAIL')
