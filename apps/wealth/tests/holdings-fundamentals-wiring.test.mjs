// Portfolio audit 2026-11-16 (B, B-parity, C, C-mixed, D/H5, H): render the REAL routed pages
// (HoldingsPage -> HoldingsWorkspace, FundamentalsPage) with react-dom/server and prove each feature is on screen.
// Synthetic only: QZ* tickers, SYN_* accounts.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const load=(src,name)=>{const c=buildSync({stdin:{contents:src,resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
  const fn=path.join(APP,name),m=new Module(fn);m.filename=fn;m.paths=Module._nodeModulePaths(APP);m._compile(c,fn);return m.exports}
const m=load("export {HoldingsPage} from './src/pages/portfolio/HoldingsPage'; export {FundamentalsPage} from './src/pages/fundamentals/FundamentalsPage'; export {DrawerProvider} from './src/components/Drawer'; export {FIXTURE_BOOK} from './src/pages/portfolio/fixtures'",'hf-wiring.cjs')
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),{MemoryRouter}=require('react-router-dom')

const base=m.FIXTURE_BOOK.rows.find(r=>r.kind==='SECURITY')
const prot=(o={})=>({state:'PROTECTED',stop:90,basis:'synthetic',asOf:'2040-01-01T12:00:00Z',stale:false,nextStep:'Inspect recorded stop',reason:'Synthetic recorded resting stop',...o})
const row=(o={})=>({...structuredClone(base),symbol:'QZBIG',name:'Synthetic Big',accountKey:'SYN_A',accountLabel:'Synthetic A',kind:'SECURITY',assetType:'EQUITY',marketValue:5000,shares:50,avgCost:80,price:100,gainLoss:1000,gainLossPct:25,dayChange:10,fundamentals:{sector:'Technology'},protection:prot(),...o})
const SMALL=['QZSA','QZSB','QZSC']
const rows=[row(),
  row({symbol:'QZDUP',accountKey:'SYN_A',marketValue:2000}),
  row({symbol:'QZDUP',accountKey:'SYN_B',accountLabel:'Synthetic B',marketValue:3000,protection:{state:'GAP',stop:null,basis:null,asOf:null,stale:null,nextStep:'Place a stop',reason:'no resting stop'}}),
  ...SMALL.map((s,i)=>row({symbol:s,name:'Synthetic small '+i,marketValue:10+i,gainLoss:1,shares:1})),
  row({symbol:'QZPEND',marketValue:900,protection:prot({reason:'Pending activation'})}),
  row({symbol:'QZSTALE',marketValue:800,protection:prot({stale:true})}),
  row({symbol:'QZCASH',name:'Synthetic sweep',kind:'CASH',assetType:'CASH',marketValue:700,protection:null}),
  row({symbol:'QZOWN',marketValue:600,fundamentals:{sector:'Technology',instOwnPct:101.3}})]
const book={...m.FIXTURE_BOOK,rows}
const el=(C,props,q)=>React.createElement(MemoryRouter,{initialEntries:[q]},React.createElement(m.DrawerProvider,null,React.createElement(C,props)))
const holdings=(q,b=book)=>renderToStaticMarkup(el(m.HoldingsPage,{book:b},'/wealth/portfolio/holdings'+q))
const fund=(q,b=book)=>renderToStaticMarkup(el(m.FundamentalsPage,{book:b},'/wealth/portfolio/fundamentals'+q))
const status=(html,cls)=>(html.match(new RegExp('class="'+cls+'"[^>]*role="status">([\\s\\S]*?)<button'))||html.match(new RegExp('class="[^"]*'+cls+'[^"]*" role="status">([\\s\\S]*?)<button'))||[])[1]||''
const hvStatus=h=>(h.match(/hv-disclosure" role="status">([\s\S]*?)<button/)||[])[1]||''
const fvStatus=h=>(h.match(/fv-disclosure" role="status">([\s\S]*?)<button/)||[])[1]||''
const has=(h,s)=>h.includes('>'+s+'</strong>')

test('Holdings page: disclosure names collapsed symbols; Show all and search reveal them',()=>{
  const d=holdings('')
  for(const s of [...SMALL,'QZCASH'])assert.ok(hvStatus(d).includes(s),s+' named in disclosure')
  assert.ok(!has(d,'QZSA')&&!has(d,'QZCASH'),'collapsed by default')
  assert.match(d,/>Show all rows</)
  const all=holdings('?hv_show=all')
  for(const s of [...SMALL,'QZCASH'])assert.ok(has(all,s),s+' rendered with hv_show=all')
  assert.ok(!/collapsed \(/.test(hvStatus(all))); assert.match(all,/>Collapse summaries</)
  const q=holdings('?hv_query=QZSB')
  assert.ok(has(q,'QZSB')&&!/collapsed \(/.test(hvStatus(q)),'hv_query reveals the collapsed row')
  assert.ok(!has(holdings('?hv_show=yes'),'QZSA'),'only hv_show=all is accepted')
})

test('Holdings page: protection filter is normalized; legacy PROTECTED is active only; unknown value matches nothing',()=>{
  const legacy=holdings('?hv_protection=PROTECTED&hv_show=all')
  assert.ok(has(legacy,'QZBIG'))
  for(const s of ['QZPEND','QZSTALE','QZCASH'])assert.ok(!has(legacy,s),s+' is not active')
  assert.match(legacy,/<option value="active" selected="">/)
  assert.ok(has(holdings('?hv_protection=pending&hv_show=all'),'QZPEND')&&!has(holdings('?hv_protection=pending&hv_show=all'),'QZBIG'))
  assert.ok(has(holdings('?hv_protection=stale&hv_show=all'),'QZSTALE'))
  assert.ok(has(holdings('?hv_protection=gap&hv_show=all'),'QZDUP'))
  const none=holdings('?hv_protection=bogus&hv_show=all')
  assert.ok(!has(none,'QZBIG')&&!has(none,'QZDUP')&&!has(none,'QZPEND'),'unknown value returns nothing')
  assert.match(none,/No rows match these filters/)
  for(const c of ['active','pending','stale','gap','unknown','n/a'])assert.ok(holdings('').includes('<option value="'+c+'"'),c)
})

test('Holdings page: mixed-account parent shows the badge with counts and per-account states',()=>{
  const h=holdings('?hv_show=all')
  assert.match(h,/hv-mixed[^>]*>[\s\S]*?Mixed · 1 active · 1 gap/)
  assert.ok(h.includes('Synthetic A: active · Synthetic B: gap'))
})

test('Holdings page: "past the limit" only when age exceeds the limit',()=>{
  const served=(ageSeconds)=>({...book,freshness:{...book.freshness,served:{...m.FIXTURE_BOOK.freshness.served,status:'STALE',stale:true,ageSeconds,limitSeconds:1800,gap:'stops clock missing'}}})
  const inside=holdings('',served(180)),over=holdings('',served(2400))
  assert.ok(!/past the/.test(inside)&&/within the 30 min limit/.test(inside))
  assert.ok(/past the 30 min limit/.test(over))
})

test('Fundamentals page: disclosure names collapsed rows; Show all and search reveal them (parity)',()=>{
  const d=fund('')
  for(const s of [...SMALL,'QZCASH'])assert.ok(fvStatus(d).includes(s),s+' named in disclosure')
  assert.match(d,/>Show all positions</); assert.match(d,/aria-expanded="false"/)
  const all=fund('?fv_show=all')
  assert.ok(!/collapsed \(/.test(fvStatus(all))); assert.match(all,/>Collapse small and cash</)
  assert.ok(all.includes('QZSA')&&all.includes('QZCASH'))
  assert.ok(!d.includes('>QZSA<')&&!d.includes('QZSA</'),'collapsed rows are absent by default')
  const q=fund('?fv_query=QZSB')
  assert.ok(q.includes('QZSB')&&!/collapsed \(/.test(fvStatus(q)))
  const none=fund('?fv_query=QZNOPE')
  assert.match(none,/No holdings match this view/); assert.ok(/0 of \d+ account positions match/.test(fvStatus(none)))
})

test('Fundamentals page: ownership above 100% is shown as published with the explanation',()=>{
  const risk=fund('?fv_lens=risk&fv_show=all')
  assert.ok(risk.includes('101.30%')); assert.ok(risk.includes('above 100%, as published')); assert.ok(risk.includes('not clamped'))
  assert.ok(!fund('?fv_lens=risk&fv_query=QZBIG').includes('above 100%, as published'))
})

test('Fundamentals page: forced-open controls are truthfully disabled with the reason (no dead Collapse buttons)',()=>{
  const btn=(h,re)=>(h.match(new RegExp('<button[^>]*'+re+'[^>]*>'))||[])[0]||''
  // Normal state: the controls are live and say Expand.
  const d=fund('')
  assert.ok(btn(d,'Expand QZDUP account positions')&&!/disabled/.test(btn(d,'Expand QZDUP account positions')),'group expander is live by default')
  assert.ok(!/fv-forced/.test(d))
  // Show all: group + section buttons cannot do anything, so they are disabled and the page says why.
  const all=fund('?fv_show=all')
  assert.ok(/disabled/.test(btn(all,'QZDUP account positions \\(expanded because Show all is on\\)')),'group button disabled under show all')
  assert.ok(!/aria-label="Collapse QZDUP/.test(all),'no Collapse label that cannot collapse')
  assert.ok(all.includes('Expanded because Show all is on.'))
  assert.ok(all.includes('Shown because Show all is on.')&&/disabled=""[^>]*aria-expanded="true">▾ Small positions/.test(all)||/<button[^>]*disabled[^>]*>▾ Small positions/.test(all),'small section button disabled')
  assert.ok(/<button[^>]*disabled[^>]*>▾ Cash/.test(all),'cash section button disabled')
  // Search: forced sections are disabled with the search reason, matching rows stay visible, group expanders stay live.
  const q=fund('?fv_query=QZSB')
  assert.ok(q.includes('QZSB')&&!/collapsed \(/.test(fvStatus(q)))
  assert.ok(q.includes('Shown because a search is active'))
  assert.ok(/<button[^>]*disabled[^>]*>▾ Small positions/.test(q))
  const qd=fund('?fv_query=QZDUP')
  assert.ok(qd.includes('QZDUP')&&!/disabled=""[^>]*>[^<]*QZDUP/.test(qd),'group expander for a matching group stays live under search')
})
