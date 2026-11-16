// Portfolio audit 2026-11-16 — synthetic acceptance for discoverability (B), protection (C) and population (A).
// No network, no portfolio data: every symbol is a synthetic QZ* ticker and every account a SYN_* key.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const code=buildSync({stdin:{contents:"export * from './src/pages/portfolio/workspaceV2/adapter'; export * from './src/pages/portfolio/workspaceV2/discovery'; export * from './src/pages/portfolio/fixtures'; export {normalizeAccountKey} from './src/pages/portfolio/accountLabel'; export * as fv from './src/pages/fundamentals/modelV2'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
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
