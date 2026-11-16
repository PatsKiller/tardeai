// Portfolio audit 2026-11-16 — synthetic acceptance for discoverability (B), protection (C) and population (A).
// No network, no portfolio data: every symbol is a synthetic QZ* ticker and every account a SYN_* key.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const code=buildSync({stdin:{contents:"export * from './src/pages/portfolio/workspaceV2/adapter'; export * from './src/pages/portfolio/workspaceV2/discovery'; export * from './src/pages/portfolio/fixtures'; export {normalizeAccountKey} from './src/pages/portfolio/accountLabel'; export * as fv from './src/pages/fundamentals/modelV2'; export * as inc from './src/pages/portfolio/income/incomeAdapter'; export {OWNERSHIP_OVER_100,detailSections} from './src/pages/portfolio/detail'; export {servedFreshnessLine,lastKnownSentence,overLimitPhrase} from './src/pages/portfolio/format'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
const filename=path.join(APP,'portfolio-audit.cjs'),module=new Module(filename);module.filename=filename;module.paths=Module._nodeModulePaths(APP);module._compile(code,filename)
const a=module.exports

const base=a.FIXTURE_BOOK.rows.find(r=>r.kind==='SECURITY')
const prot=(o={})=>({state:'PROTECTED',stop:90,basis:'synthetic',asOf:'2040-01-01T12:00:00Z',stale:false,nextStep:'Inspect recorded stop',reason:'Synthetic recorded resting stop',...o})
const row=(o={})=>({...structuredClone(base),symbol:'QZBIG',name:'Synthetic Big',accountKey:'SYN_A',accountLabel:'Synthetic A',kind:'SECURITY',assetType:'EQUITY',marketValue:5000,shares:50,avgCost:80,price:100,gainLoss:1000,gainLossPct:25,dayChange:10,fundamentals:{sector:'Technology'},protection:prot(),...o})
// Twelve small securities (the audit's hidden-small population, synthetic), a duplicate symbol in two accounts,
// cash, and a small pinned loser that must stay above the fold.
const SMALL=Array.from({length:12},(_,i)=>'QZS'+String.fromCharCode(65+i))
const rows=[row(),row({symbol:'QZDUP',accountKey:'SYN_A',marketValue:2000}),row({symbol:'QZDUP',accountKey:'SYN_B',accountLabel:'Synthetic B',marketValue:3000,protection:{state:'GAP',stop:null,basis:null,asOf:null,stale:null,nextStep:'Place a stop',reason:'no resting stop'}}),
  ...SMALL.map((s,i)=>row({symbol:s,name:'Synthetic small '+i,marketValue:10+i,gainLoss:1,shares:1})),
  row({symbol:'QZPIN',marketValue:40,gainLoss:-150}),
  row({symbol:'QZCASH',name:'Synthetic sweep',kind:'CASH',assetType:'CASH',marketValue:700,protection:null})]
const book={...a.FIXTURE_BOOK,rows}
const view=(f={})=>a.workspace(book,{...a.DEFAULT,...f})

test('B: default view collapses the twelve small securities and names every one of them',()=>{
  const v=view(),d=a.disclosure(rows.length,v.groups,new Set())
  const small=v.groups.find(g=>g.kind==='small')
  assert.deepEqual(small.rows.map(r=>r.symbol).sort(),SMALL)
  assert.equal(d.collapsed,13) // 12 small + 1 cash
  for(const s of SMALL)assert.ok(d.collapsedSymbols.includes(s),s)
  assert.ok(a.disclosureText(d).includes('collapsed'))
  assert.ok(v.groups.some(g=>g.label==='QZPIN'),'pinned loser stays above the fold')
})

test('B: Show all expands every collapsible group, so every row is visible',()=>{
  const v=view(),keys=a.allGroupKeys(v.groups),d=a.disclosure(rows.length,v.groups,new Set(keys))
  assert.equal(d.collapsed,0); assert.equal(d.visible,rows.length)
  assert.ok(keys.includes('small')&&keys.includes('cash')&&keys.includes('security-QZDUP'))
  const p=a.withShowAll(new URLSearchParams('hv_query=x'),true)
  assert.equal(a.showAllFrom(p),true); assert.equal(a.showAllFrom(a.withShowAll(p,false)),false)
  assert.equal(a.showAllFrom(new URLSearchParams('hv_show=yes')),false)
})

test('B: search reveals the collapsed group that holds the match; empty search reveals nothing',()=>{
  for(const s of SMALL){const v=view({query:s.toLowerCase()});assert.deepEqual(a.queryRevealKeys(v.groups,s.toLowerCase()),['small'],s)}
  assert.deepEqual(a.queryRevealKeys(view({query:'sweep'}).groups,'sweep'),['cash'])
  assert.deepEqual(a.queryRevealKeys(view().groups,'  '),[])
  const none=view({query:'QZNOPE'});assert.equal(none.rows.length,0)
  const d=a.disclosure(rows.length,none.groups,new Set());assert.equal(d.matching,0);assert.equal(d.filteredOut,rows.length)
})

test('B: exact-symbol deep link resolves duplicate symbols per account and combined filters',()=>{
  const v=view({query:'QZDUP'}),t=a.holdingLinkTarget(v.groups,{query:'QZDUP',account:'SYN_B'})
  assert.deepEqual(t.expand,['security-QZDUP'])
  const child=v.groups.find(g=>g.key==='security-QZDUP').children.find(c=>c.key===t.rowKey)
  assert.equal(child.rows[0].accountKey,'SYN_B')
  const combined=view({query:'QZS',account:'SYN_A',size:'small'})
  assert.equal(combined.rows.length,12)
})

test('C: protection classes never promote pending, undated or stale records to active',()=>{
  assert.equal(a.protectionClass(row()),'active')
  assert.equal(a.protectionClass(row({protection:prot({reason:'Recorded · pending activation'})})),'pending')
  assert.equal(a.protectionClass(row({protection:prot({stale:true})})),'stale')
  assert.equal(a.protectionClass(row({protection:prot({asOf:null})})),'stale')
  assert.equal(a.protectionClass(row({protection:prot({stale:null})})),'stale')
  assert.equal(a.protectionClass(row({protection:prot({stop:0})})),'pending')
  assert.equal(a.protectionClass(row({protection:{state:'GAP'}})),'gap')
  assert.equal(a.protectionClass(row({protection:null})),'unknown')
  assert.equal(a.protectionClass(row({kind:'CASH'})),'n/a')
  // A legacy PROTECTED link means verified-active only.
  const pending=row({protection:prot({nextStep:'Await activation'})})
  assert.equal(a.matchesProtection(pending,'PROTECTED'),false)
  assert.equal(a.matchesProtection(pending,'pending'),true)
  assert.equal(a.protectionFilterValue('bogus'),'')
})

test('C: a grouped parent with disagreeing accounts says Mixed with counts',()=>{
  const m=a.protectionMix([row({protection:prot({reason:'pending activation'})}),row({accountLabel:'Synthetic Roth',protection:{state:'GAP'}})])
  assert.equal(m.mixed,true); assert.equal(m.label,'Mixed · 1 pending · 1 gap')
  assert.equal(a.protectionMix([row(),row()]).mixed,false)
})

test('A: alias normalization is unique-prefix only and never guesses',()=>{
  assert.equal(a.normalizeAccountKey('syn_roth_ira',['syn_roth','syn_taxable']),'syn_roth')
  assert.equal(a.normalizeAccountKey('syn_roth',['syn_roth_ira']),'syn_roth_ira')
  assert.equal(a.normalizeAccountKey('syn',['syn_a','syn_b']),null)
  assert.equal(a.normalizeAccountKey('other',['syn_a']),null)
})

const fview=(f={})=>a.fv.viewOf(book,{...a.fv.DEFAULT,...f})
test('B parity: Fundamentals discloses collapsed small/cash rows by name and Show all opens them',()=>{
  const v=fview(),d=a.fv.disclosureFv(rows.length,v,new Set())
  assert.equal(d.matching,rows.length); assert.equal(d.filteredOut,0)
  for(const s of SMALL)assert.ok(d.collapsedSymbols.includes(s),s)
  assert.ok(d.collapsedSymbols.includes('QZCASH')); assert.ok(!d.collapsedSymbols.includes('QZPIN'),'pinned loser stays visible')
  assert.equal(a.fv.disclosureFv(rows.length,v,new Set(['small','cash'])).collapsed,0)
  const p=a.fv.withShowAllFv(new URLSearchParams('fv_query=x'),true)
  assert.equal(a.fv.showAllFv(p),true); assert.equal(a.fv.showAllFv(a.fv.withShowAllFv(p,false)),false)
  assert.ok(a.fv.disclosureTextFv(d).includes('collapsed ('))
})
test('B parity: Fundamentals search opens the section that holds the match; empty search opens nothing',()=>{
  for(const s of SMALL)assert.deepEqual(a.fv.revealSectionsFv(fview({query:s.toLowerCase()}),s),['small'],s)
  assert.deepEqual(a.fv.revealSectionsFv(fview({query:'sweep'}),'sweep'),['cash'])
  assert.deepEqual(a.fv.revealSectionsFv(fview(),''),[])
  const none=fview({query:'QZNOPE'}),d=a.fv.disclosureFv(rows.length,none,new Set())
  assert.equal(d.matching,0); assert.equal(d.filteredOut,rows.length); assert.deepEqual(a.fv.revealSectionsFv(none,'QZNOPE'),[])
})

test('D/H5: "past the limit" only when the served age exceeds the served limit',()=>{
  const sf=(o)=>({status:'STALE',stale:true,clock:'quote',clockLabel:'QUOTE',asOf:'2040-01-01T12:00:00Z',ageSeconds:180,limitSeconds:1800,limitSource:null,gap:'stops clock missing for one account',...o})
  const inside=a.servedFreshnessLine(sf())
  assert.ok(!/past the/.test(inside),inside); assert.ok(inside.includes('within the 30 min limit')&&inside.includes('stops clock missing'),inside)
  assert.ok(/past the 30 min limit/.test(a.servedFreshnessLine(sf({ageSeconds:2400}))))
  assert.ok(/cannot be computed/.test(a.overLimitPhrase(null,1800)))
  const lk=a.lastKnownSentence({withdrawn:false,stale:true,ageSeconds:null,staleAfterSeconds:null,served:sf()})
  assert.ok(!/past the/.test(lk),lk)
})

test('F: account refs are stable across payer order and never positional; unknown frequency is totalled apart',()=>{
  const p=(o)=>({symbol:'QZA',account:'syn_a',annual_income:100,monthly_amort:8.33,yield_pct:2,frequency:'quarterly',...o})
  const payers=[p(),p({symbol:'QZB',account:'syn_b',annual_income:50,frequency:'Unknown'}),p({symbol:'QZC',account:'syn_b',annual_income:25,frequency:''})]
  const m1=a.inc.incomeModel({has_data:true,total_annual:175,payers}),m2=a.inc.incomeModel({has_data:true,total_annual:175,payers:[...payers].reverse()})
  const ref=(m,k)=>m.legs.find(l=>l.symbol===k).scope
  assert.equal(ref(m1,'QZA'),ref(m2,'QZA')); assert.equal(ref(m1,'QZB'),ref(m2,'QZB'))
  assert.doesNotMatch(JSON.stringify(m1.accounts),/\(\d\)|syn_a|syn_b/)
  const s=a.inc.incomeScope(m1,'household')
  assert.equal(s.scheduledAnnual,100); assert.equal(s.unscheduledAnnual,75)
  assert.deepEqual(s.unscheduled.map(l=>l.symbol),['QZB','QZC'])
})

test('H: ownership above 100% is printed as published with an explanation, never clamped',()=>{
  const r=row({fundamentals:{sector:'Technology',instOwnPct:101.3}})
  const flat=JSON.stringify(a.detailSections(r))
  assert.ok(flat.includes('101.30%'),'raw value kept'); assert.ok(flat.includes('not clamped'))
  assert.ok(!JSON.stringify(a.detailSections(row({fundamentals:{sector:'Technology',instOwnPct:70}}))).includes('not clamped'))
})

// ---- Wired page (not just the model): render the real HoldingsWorkspace through the router with URL state. ------
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),{MemoryRouter}=require('react-router-dom')
const ws=(()=>{const c=buildSync({stdin:{contents:"export {HoldingsWorkspace} from './src/pages/portfolio/workspaceV2/Workspace'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
  const fn=path.join(APP,'portfolio-audit-ws.cjs'),m=new Module(fn);m.filename=fn;m.paths=Module._nodeModulePaths(APP);m._compile(c,fn);return m.exports})()
const page=(query,b=book)=>renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/wealth/portfolio/holdings'+query]},React.createElement(ws.HoldingsWorkspace,{book:b,notice:null,evidence:null,onRowOpen:()=>{}})))
const childRows=html=>(html.match(/Evidence &amp; details/g)||[]).length
const status=html=>(html.match(/<p class="hv-note hv-disclosure" role="status">([\s\S]*?)<button/)||[])[1]||''

test('B wired: default page names the collapsed small securities on screen and offers Show all',()=>{
  const html=page('')
  for(const s of SMALL)assert.ok(status(html).includes(s),s)
  assert.match(html,/aria-pressed="false"[^>]*>Show all rows</)
  assert.ok(!html.includes('>QZSA</strong>'),'small child rows stay collapsed by default')
})

test('B wired: ?hv_show=all renders every account row, including each small security and cash',()=>{
  const html=page('?hv_show=all')
  for(const s of [...SMALL,'QZCASH'])assert.ok(html.includes('>'+s+'</strong>'),s)
  assert.ok(!/collapsed \(/.test(status(html)),'nothing reported collapsed')
  assert.match(html,/aria-pressed="true"[^>]*>Collapse summaries</)
  assert.ok(childRows(html)>childRows(page('')))
})

test('B wired: a search for a collapsed symbol opens its section on the page',()=>{
  const html=page('?hv_query=QZSE')
  assert.ok(html.includes('>QZSE</strong>'),'match rendered as its own row')
  assert.ok(!/collapsed \(/.test(status(html)))
})

test('C wired: legacy ?hv_protection=PROTECTED shows verified-active rows only; pending is its own class',()=>{
  const pend=row({symbol:'QZPEND',protection:prot({reason:'Pending activation'})}),stale=row({symbol:'QZSTALE',protection:prot({stale:true})})
  const b={...book,rows:[row(),pend,stale]}
  const legacy=page('?hv_protection=PROTECTED',b)
  assert.ok(legacy.includes('>QZBIG</strong>')&&!legacy.includes('>QZPEND</strong>')&&!legacy.includes('>QZSTALE</strong>'))
  assert.ok(page('?hv_protection=pending',b).includes('>QZPEND</strong>'))
  assert.ok(page('?hv_protection=stale',b).includes('>QZSTALE</strong>'))
  assert.match(legacy,/<option value="active" selected="">Active · verified current<\/option>/)
})

test('C wired: a grouped parent whose accounts disagree shows a Mixed badge with per-account states',()=>{
  const html=page('?hv_show=all')
  assert.match(html,/hv-mixed[\s\S]*?Mixed · 1 active · 1 gap/)
  assert.ok(html.includes('Synthetic A: active · Synthetic B: gap'))
})
