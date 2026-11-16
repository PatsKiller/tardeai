// Portfolio audit 2026-11-16 (F2/F3): Income against the /api/v2/dividends contract. Synthetic QZ*/syn_* only.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),{MemoryRouter}=require('react-router-dom')
const a={inc:(()=>{const c=buildSync({stdin:{contents:"export * from './src/pages/portfolio/income/incomeAdapter'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'}).outputFiles[0].text
  const f=path.join(APP,'income-model.cjs'),m=new Module(f);m.filename=f;m.paths=Module._nodeModulePaths(APP);m._compile(c,f);return m.exports})()}

// ---- F2/F3 against the /api/v2/dividends contract (account_label_source, per-leg months, unplaced) ----------
const incPayer=(o)=>({symbol:'QZA',account:'syn_reg',annual_income:40.01,monthly_amort:3.33,yield_pct:2,frequency:'quarterly',months:[3,6,9,12],...o})
const incBody=(extra={})=>({has_data:true,account_attribution:'holdings_mv_share',total_annual:57.01,monthly_average:4.75,last_updated:'2040-01-01 12:00',
  payers:[incPayer(),incPayer({symbol:'QZB',account:'syn_der',annual_income:10,frequency:'quarterly',months:[1,4,7,10]}),incPayer({symbol:'QZC',account:'syn_der',annual_income:7,frequency:null,months:[]})],
  monthly_summary:Array.from({length:12},(_,i)=>({month:i+1,month_name:'M'+(i+1),total:([3,6,9,12].includes(i+1)?10:0)+([1,4,7,10].includes(i+1)?2.5:0),symbols:[]})),
  unplaced:[{symbol:'QZC',annual_income:7}],unplaced_annual:7,monthly_summary_basis:'observed ex-date months',
  account_labels:{syn_reg:'Synthetic Registry',syn_der:'Syn Der'},account_label_source:{syn_reg:'registry',syn_der:'derived'},...extra})

test('F2: only a registry name is a resolved name; a derived label prints the stable fallback ref',()=>{
  const m=a.inc.incomeModel(incBody())
  const reg=m.accounts.find(x=>x.label==='Synthetic Registry'),der=m.accounts.find(x=>x.ref===a.inc.stableAccountRef('syn_der'))
  assert.equal(reg.nameSource,'registry')
  assert.equal(der.nameSource,'fallback'); assert.match(der.label,/^Account label unavailable · acct-[0-9a-f]{8}$/)
  assert.doesNotMatch(JSON.stringify(m.accounts),/syn_reg|syn_der|Syn Der/)
  // Live 661a serves neither map: no name, so every account is the stable fallback, never a key.
  const live=a.inc.incomeModel(incBody({account_labels:undefined,account_label_source:undefined}))
  assert.ok(live.accounts.every(x=>x.nameSource==='fallback'))
  // A producer label without provenance is shown but marked as unverified provenance.
  const served=a.inc.incomeModel(incBody({account_label_source:undefined}))
  assert.equal(served.accounts.find(x=>x.label==='Synthetic Registry').nameSource,'served')
})

test('F3: annual = placed + not placed; twelve months = annual − not placed, with the rounding gap retained',()=>{
  const s=a.inc.incomeScope(a.inc.incomeModel(incBody()),'household')
  assert.ok(s.placementKnown)
  assert.equal(s.placedAnnual,50.01); assert.equal(s.unplacedAnnual,7)
  assert.equal(Math.round((s.placedAnnual+s.unplacedAnnual)*100)/100,57.01)
  assert.equal(s.monthsSum,50); assert.equal(s.placedExpected,50.01); assert.equal(s.monthsGap,-0.01)
  assert.equal(s.difference,0)
  // Account scope: the derived account's legs split by placement; no household months are attributed.
  const acct=a.inc.incomeScope(a.inc.incomeModel(incBody()),a.inc.stableAccountRef('syn_der'))
  assert.equal(acct.placedAnnual,10); assert.equal(acct.unplacedAnnual,7); assert.equal(acct.monthsSum,null)
  // Older payload (no months on legs): placement unknown, frequency split is the stated fallback.
  const old=a.inc.incomeScope(a.inc.incomeModel(incBody({payers:incBody().payers.map(({months,...p})=>p),unplaced:undefined,unplaced_annual:undefined})),'household')
  assert.equal(old.placementKnown,false); assert.equal(old.monthsGap,null)
})

const incPage=(()=>{const c=buildSync({stdin:{contents:"export {IncomePage} from './src/pages/portfolio/income/IncomePage'; export {DrawerProvider} from './src/components/Drawer'; export {incomeState} from './src/pages/portfolio/income/incomeAdapter'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
  const f=path.join(APP,'income-page.cjs'),m=new Module(f);m.filename=f;m.paths=Module._nodeModulePaths(APP);m._compile(c,f);return m.exports})()
const incomeHtml=body=>{const now=Date.parse('2040-01-01T12:05:00Z'),read=incPage.incomeState({data:body,error:null,lastGood:null,spec:{path:'/api/v2/dividends'}},now)
  return renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(incPage.DrawerProvider,null,React.createElement(incPage.IncomePage,{read}))))}

test('F wired: the Income page prints placement, the registry name and the fallback-ref note',()=>{
  const html=incomeHtml(incBody())
  assert.match(html,/Placed in a month \$50\.01 a year · not placed \$7\.00 \(QZC\)/)
  assert.match(html,/<option value="acct-[0-9a-f]{8}">Synthetic Registry<\/option>/)
  assert.match(html,/Account label unavailable · acct-[0-9a-f]{8}/)
  assert.match(html,/shown by a stable reference/)
  assert.doesNotMatch(html,/syn_reg|syn_der|Syn Der/)
})
