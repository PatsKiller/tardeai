// Portfolio repair 2026-11-16, lane population-contracts: synthetic acceptance for population (A1–A4), account
// identity (F2), the D2 weight basis and Holdings freshness. No network, no portfolio data: every symbol is a
// synthetic QZ* ticker and every account a syn_* key.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const code=buildSync({stdin:{contents:"export {adaptHoldings,accountsFrom} from './src/pages/portfolio/adapter'; export {detailHeading,detailFields,weightFields} from './src/pages/portfolio/detail'; export * from './src/pages/portfolio/accountLabel'; export {populationLines} from './src/pages/portfolio/format'; export {holdingsProps} from './src/pages/portfolio/liveProps'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
const filename=path.join(APP,'portfolio-population.cjs'),module=new Module(filename);module.filename=filename;module.paths=Module._nodeModulePaths(APP);module._compile(code,filename)
const a=module.exports

const row=(o={})=>({symbol:'QZA',name:'Synthetic A Corp',account:'syn_roth',account_key:'syn_roth',account_label:'syn_roth',is_cash:false,asset_type:'EQUITY',
  shares:10,price:30,price_as_of:'2040-01-02T15:00:00Z',market_value:300,portfolio_pct:30,...o})
const DERIVED={source:'derived_at_read',value_field:'market_value',value_usd:200,denominator_field:'portfolio_totals.total_value',denominator_usd:1000,snapshot_field:'price_as_of',snapshot_at:'2040-01-02T15:00:00Z'}
const STORED={source:'repricer_stored',value_field:'holdings[].market_value at the repricer pass',value_usd:null,denominator_field:'sum(account_summaries[].total_value) at the repricer pass',denominator_usd:null,snapshot_field:'last_repriced',snapshot_at:'2040-01-02T14:45:00Z'}
const NONE={source:'not_computed',value_field:null,value_usd:null,denominator_field:null,denominator_usd:null,snapshot_field:null,snapshot_at:null}
const holdings=()=>[
  row({portfolio_pct_basis:STORED}),
  row({symbol:'QZB',account:'syn_roth_ira',account_key:'syn_roth_ira',account_label:'Synthetic Roth',market_value:200,portfolio_pct:20,portfolio_pct_basis:DERIVED}),
  row({symbol:'QZC',account:'syn_taxable',account_key:'syn_taxable',account_label:'syn_taxable',market_value:0,portfolio_pct:0,portfolio_pct_basis:NONE}),
  row({symbol:'QZC',account:'syn_taxable',account_key:'syn_taxable',account_label:'syn_taxable',market_value:50,portfolio_pct:5,portfolio_pct_basis:{...DERIVED,value_usd:49.5,denominator_usd:1000}}),
  row({symbol:'QZD',account:'syn_9876',account_key:'syn_9876',account_label:'syn_9876',market_value:400,portfolio_pct:40}),
]
const IDENTITY={account_aliases:{syn_roth:'syn_roth_ira'},account_labels:{syn_roth_ira:'Synthetic Roth',syn_taxable:'Syn Taxable'},account_label_source:{syn_roth_ira:'registry',syn_taxable:'derived'}}
const data=(o={})=>({holdings:holdings(),as_of:'2040-01-02T15:00:00Z',scope_coverage:{min_position_usd:100,rows_read:6,scopes:{'holdings.all_rows':5},
  priceable:{row_count:9,measured_rows:7},scope:{accounts:['syn_roth','syn_taxable','syn_gone']},excluded:[]},...IDENTITY,...o})
const book=(d=data(),root={})=>{const r=a.adaptHoldings({ok:true,data:d,_swr:{as_of:'2040-01-02T15:00:00Z',age_s:5,stale:false},...root});assert.ok(r.book,r.error);return r.book}
const RAW=['syn_roth','syn_taxable','syn_9876','syn_gone','syn_roth_ira']
const noRaw=(text,what)=>{for(const k of RAW)assert.ok(!text.includes(k),`${what} leaks ${k}: ${text}`)}

test('A1: the read count comes from rows_read and names its basis; the gap is an omission with no invented rule',()=>{
  const b=book()
  assert.equal(b.population.readRows,6); assert.equal(b.population.readRowsBasis,'scope_coverage.rows_read')
  assert.equal(b.population.renderedRows,5)
  assert.equal(b.population.excluded.reduce((t,e)=>t+e.count,0),1)
  assert.match(b.population.excluded[0].rule,/no rule/)
  const noRead=book(data({scope_coverage:{min_position_usd:100,priceable:{row_count:9,measured_rows:7}}}))
  assert.equal(noRead.population.readRowsBasis,'rendered')
  assert.match(noRead.coverageNote,/no read count/,'an unsized read is named as unknown')
})

test('A2: the measure population is shown beside the read with its basis and never subtracted from it',()=>{
  const b=book(),m=b.population.measurePopulation
  assert.equal(m.rowCount,9); assert.equal(m.measuredRows,7); assert.equal(m.differenceFromRead,0)
  assert.match(m.basis,/priceable\.row_count/)
  assert.equal(b.population.excluded.reduce((t,e)=>t+e.count,0),1,'the measure count (9) never inflates the omission')
  const lines=a.populationLines(b.population).join(' | ')
  assert.match(lines,/6 rows read/); assert.match(lines,/9 rows/); assert.ok(!/−3|-3|3 more|3 fewer/.test(lines),lines)
})

test('A3: one account reached through a registry alias is one account; never two',()=>{
  const b=book()
  const roth=b.rows.filter(r=>r.symbol==='QZA'||r.symbol==='QZB')
  assert.deepEqual([...new Set(roth.map(r=>r.accountKey))],['syn_roth_ira'])
  assert.deepEqual([...new Set(roth.map(r=>r.accountLabel))],['Synthetic Roth'])
  assert.equal(roth[0].accountLabelBasis,'registry')
  const al=b.population.aliasedAccounts
  assert.equal(al.length,1); assert.equal(al[0].basis,'registry'); assert.equal(al[0].label,'Synthetic Roth')
  assert.equal(al[0].scopeKey,a.stableAccountRef('syn_roth')); assert.equal(al[0].rowKey,a.stableAccountRef('syn_roth_ira'))
  noRaw(JSON.stringify(al),'aliasedAccounts')
  assert.equal(b.population.scopeAccountsWithoutRows.length,1)
  noRaw(b.population.scopeAccountsWithoutRows[0],'scopeAccountsWithoutRows')
  assert.ok(b.population.scopeAccountsWithoutRows[0].includes(a.stableAccountRef('syn_gone')))
  // An older backend (no alias map): the client heuristic is used and labelled as such.
  const sc=data().scope_coverage
  const old=book(data({account_aliases:undefined,account_labels:undefined,account_label_source:undefined,scope_coverage:{...sc,scope:{accounts:['syn_taxable_live']}}}))
  assert.equal(old.population.aliasedAccounts[0]?.basis,'key-prefix')
  assert.equal(old.population.aliasedAccounts[0]?.rowKey,a.stableAccountRef('syn_taxable'))
  noRaw(JSON.stringify(old.population.aliasedAccounts),'heuristic aliasedAccounts')
})

test('A3: duplicate account/security rows are listed with their count, not merged and not subtracted',()=>{
  const b=book()
  assert.equal(b.rows.length,5)
  assert.deepEqual(b.population.duplicateRows.map(d=>[d.symbol,d.rows,d.accountLabel]),[['QZC',2,'Syn Taxable']])
  assert.match(b.coverageNote,/more than one row/)
  assert.equal(b.counts.allRows,5)
})

test('A4: broker completeness stays BROKER_COMPLETENESS_UNVERIFIED and reads as unverified',()=>{
  const b=book()
  assert.equal(b.population.completeness,'BROKER_COMPLETENESS_UNVERIFIED')
  assert.ok(a.populationLines(b.population).some(l=>/unverified/i.test(l)))
})

test('F2: labels resolve registry vs derived vs fallback, and a number-like key is never shown',()=>{
  const b=book(),by=s=>b.rows.find(r=>r.symbol===s)
  assert.equal(by('QZA').accountLabelBasis,'registry')
  assert.equal(by('QZC').accountLabel,'Syn Taxable'); assert.equal(by('QZC').accountLabelBasis,'derived')
  const d=by('QZD')
  assert.equal(d.accountLabelBasis,'fallback'); assert.equal(d.accountLabel,`Account label unavailable · ${a.stableAccountRef('syn_9876')}`)
  // An older backend with a row label equal to the key: fallback ref, never the key.
  const old=book(data({account_aliases:undefined,account_labels:undefined,account_label_source:undefined}))
  assert.equal(old.rows.find(r=>r.symbol==='QZC').accountLabelBasis,'fallback')
  assert.equal(old.rows.find(r=>r.symbol==='QZB').accountLabelBasis,'served')
  for(const r of [...b.rows,...old.rows]){noRaw(r.accountLabel,'row label');noRaw(a.detailHeading(r).eyebrow,'drawer eyebrow')
    noRaw(a.detailFields(r).map(f=>`${f.value} ${f.source}`).join(' '),'drawer')}
  assert.match(a.detailFields(by('QZA')).find(f=>f.label==='Account').source,/account registry/)
  assert.match(a.detailFields(by('QZC')).find(f=>f.label==='Account').source,/not in the account registry/)
})

test('F2: the accounts block keeps its legacy label and adds a display label that is never a key',()=>{
  const d={reconciliation:{accounts:[{account:'syn_roth',end_equity:{value_usd:1}},{account:'syn_9876',end_equity:{value_usd:1}}]},...IDENTITY}
  const acc=a.accountsFrom(d,[])
  assert.equal(acc[0].displayLabel,'Synthetic Roth'); assert.equal(acc[0].labelBasis,'registry')
  assert.equal(acc[1].labelBasis,'fallback'); noRaw(acc.map(x=>x.displayLabel).join(' '),'accounts displayLabel')
})

test('D2: the drawer shows the basis, reconciles only on the same value, and says "not served" when absent',()=>{
  const b=book(),by=s=>b.rows.find(r=>r.symbol===s&&(s!=='QZC'||r.marketValue===50))
  const w=r=>Object.fromEntries(a.weightFields(r).map(f=>[f.label,f]))
  // derived_at_read on this row's own market value: the division is shown and checked.
  const qzb=w(by('QZB'))
  assert.equal(qzb['Weight basis'].value,'$200.00 ÷ $1,000.00 = 20.00%'); assert.match(qzb['Weight basis'].source,/reconciles to the served percent/)
  // derived on a different value: "bases differ", and no derived number.
  const diff=w(by('QZC'))
  assert.equal(diff['Weight basis'].value,'bases differ'); assert.ok(!/\d+\.\d+%/.test(diff['Weight basis'].source),diff['Weight basis'].source)
  // repricer_stored: the clock is named and reconciliation is refused, not invented.
  const st=w(by('QZA'))
  assert.match(st['Weight basis'].value,/not reconcilable/); assert.match(st['Weight basis'].source,/2040-01-02T14:45:00Z/)
  // not_computed: the 0 placeholder is never shown as a 0% weight.
  const zero=w(b.rows.find(r=>r.symbol==='QZC'&&r.marketValue===0))
  assert.ok(!/^0(\.0+)?%$/.test(zero['Weight of book'].value),zero['Weight of book'].value)
  // absent (older backend): "basis not served".
  const absent=w(by('QZD'))
  assert.match(absent['Weight basis'].value,/not served/); assert.equal(by('QZD').portfolioPctBasis,null)
  const odd=w({...by('QZD'),portfolioPctBasis:{source:'unrecognized',valueField:null,valueUsd:null,denominatorField:null,denominatorUsd:null,snapshotField:null,snapshotAt:null}})
  assert.match(odd['Weight basis'].value,/not recognised/)
})

test('Freshness: an unknown clock is never fresh',()=>{
  const r=a.adaptHoldings({ok:true,data:data()})
  assert.equal(r.book.freshness.stale,true,'a missing _swr block is stale, not fresh')
  const unk=a.adaptHoldings({ok:true,data:data(),_swr:{as_of:'2040-01-02T15:00:00Z',age_s:5}})
  assert.equal(unk.book.freshness.stale,true,'a missing stale boolean is not fresh')
  const row0=book().rows.find(r=>r.symbol==='QZD')
  assert.equal(row0.priceAsOf,'2040-01-02T15:00:00Z')
  const noClock=book(data({holdings:[row({price_as_of:null})]})).rows[0]
  assert.equal(noClock.priceAsOf,null)
  assert.match(a.detailFields(noClock).find(f=>f.label==='Price').source,/no quoted clock/)
})
