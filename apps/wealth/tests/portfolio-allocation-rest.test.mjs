// Allocation drilldown + Retirement + Levels partial pages — synthetic acceptance (audit 2026-11-16 G1, D2).
// Component renders use react-dom/server; click behaviour is covered by the pure reducers here and by Playwright.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const src=`export {AllocationPage} from './src/pages/allocation/AllocationPage'
export * as drill from './src/pages/allocation/drillView'
export {FIXTURE_BOOK} from './src/pages/portfolio/fixtures'
export {RetirementPage} from './src/pages/portfolio/retirement/RetirementPage'
export * as ret from './src/pages/portfolio/retirement/retirementAdapter'
export {LevelsPage} from './src/pages/portfolio/levels/LevelsPage'
export * as lv from './src/pages/portfolio/levels/levelsAdapter'`
const code=buildSync({stdin:{contents:src,resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
const filename=path.join(APP,'portfolio-allocation-rest.cjs'),module=new Module(filename);module.filename=filename;module.paths=Module._nodeModulePaths(APP);module._compile(code,filename)
const a=module.exports
const React=require('react'),{renderToStaticMarkup:html}=require('react-dom/server')
const h=React.createElement
const text=s=>s.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ')

// ---- Allocation: reducers ----
test('drill: sleeve and account clicks toggle; reset lifts every filter',()=>{
  assert.equal(a.drill.toggleSector('','Technology'),'Technology')
  assert.equal(a.drill.toggleSector('Technology','Technology'),'')
  assert.equal(a.drill.toggleSector('Technology','Energy'),'Energy')
  assert.equal(a.drill.toggleAccount('ALL','SYN_A'),'SYN_A')
  assert.equal(a.drill.toggleAccount('SYN_A','SYN_A'),'ALL')
  assert.equal(a.drill.isDrilled(a.drill.NO_DRILL),false)
  assert.equal(a.drill.isDrilled({...a.drill.NO_DRILL,query:'  '}),false)
  assert.equal(a.drill.isDrilled({...a.drill.NO_DRILL,sector:'X'}),true)
  const chips=a.drill.drillChips({sector:'Tech',scope:'SYN_A',query:'qz'},k=>k,k=>'Acct '+k)
  assert.deepEqual(chips.map(c=>c.kind),['sleeve','account','search'])
})
test('drill: weight is null (never 0) when a side is unknown',()=>{
  assert.equal(a.drill.weightOf(null,100,true),null)
  assert.equal(a.drill.weightOf(10,0,true),null)
  assert.equal(a.drill.weightOf(10,100,false),null)
  assert.equal(a.drill.weightOf(10,100,true),0.1)
})

// ---- Allocation: render ----
test('allocation render: basis labels named, no bare percentage header',()=>{
  const s=text(html(h(a.AllocationPage,{book:a.FIXTURE_BOOK})))
  assert.ok(s.includes(a.drill.WEIGHT_BASIS.book),'book weight basis named')
  assert.ok(/reconcil/i.test(s),'reconciliation statement present')
  assert.ok(!/raw account/i.test(s))
})
test('allocation render: a drilled page shows the chip, a visible reset and fewer rows',()=>{
  const full=html(h(a.AllocationPage,{book:a.FIXTURE_BOOK}))
  const drilled=html(h(a.AllocationPage,{book:a.FIXTURE_BOOK,initialSector:'Energy'}))
  assert.ok(/data-reset="drill"/.test(drilled),'reset present when drilled')
  assert.ok(/data-chip="sleeve"/.test(drilled),'sleeve chip present')
  assert.ok(!/data-reset="drill"/.test(full),'no reset when not drilled')
  const n=x=>(x.match(/data-row="/g)||[]).length
  assert.ok(n(full)>0,'rows panel renders rows'); assert.ok(n(drilled)>0&&n(drilled)<n(full),'drill narrows the rows')
  assert.ok(text(drilled).includes(a.drill.WEIGHT_BASIS.selected))
  assert.ok(/aria-pressed="true"/.test(drilled),'active sleeve is pressed')
})
test('allocation: reconciliation verdict is computed, unknown when nothing valued',()=>{
  const r=a.drill.reconcileWithHoldings([],null,{valued:0,total:0})
  assert.equal(r.status,'unknown'); assert.equal(r.difference,null)
  assert.ok(r.text.includes('Cannot reconcile'))
})

// ---- Retirement ----
const env=(data,o={})=>({ok:true,data,error:null,fetchedAt:'2040-01-01T12:00:00Z',lastGoodAt:null,...o})
const SERVED={ok:true,data:{as_of:'2040-01-01',snapshot_source:'synthetic (generated 2039-12-30T00:00:00Z)',current_age:60,
  accounts:{total:1000,roth:0,traditional:600,taxable:400},canonical_total:990,snapshot_delta:10,
  loan:{balance:0,deadline:'2041-01-01',days_remaining:365,monthly_to_payoff:0},
  golden_window:{start_age:60,end_age:65,years_available:5,annual_conversion:0,bracket_ceiling:'22%'},
  dividend_income:{annual_total:120,monthly_avg:10,yield_pct:1.2},timeline:[{year:2041,age:61,milestone:'Synthetic milestone'}],
  intelligence_brief:'FIXED GROWTH TEXT',projections:{base:999999}}}
test('retirement adapter: served 0 is Unknown, never $0; withheld items are named',()=>{
  const s=a.ret.adaptRetirement(env(SERVED),Date.parse('2040-01-02T00:00:00Z'))
  assert.equal(s.kind,'ok')
  assert.equal(s.model.accounts.roth.state,'unknown'); assert.equal(s.model.loan.balance.state,'unknown')
  assert.equal(s.model.accounts.total.state,'served'); assert.equal(s.model.ageDays,3)
  assert.ok(s.model.withheld.length>=3)
})
test('retirement render: served state prints Unknown, clocks and the missing-contract note; withholds brief and projections',()=>{
  const ok=a.ret.adaptRetirement(env(SERVED),Date.parse('2040-01-02T00:00:00Z'))
  const s=html(h(a.RetirementPage,{retirement:ok,research:{kind:'loading'}})),t=text(s)
  assert.ok(/data-state="served"/.test(s)); assert.ok(t.includes('Unknown')); assert.ok(t.includes('Not served, so not shown'))
  assert.ok(t.includes('2039-12-30')&&t.includes('read 2040-01-01'))
  assert.ok(!t.includes('FIXED GROWTH TEXT')&&!t.includes('999')&&!t.includes('$0'))
  assert.equal((s.match(/<h1/g)||[]).length,0,'page renders no h1')
  assert.ok(/<h2>Retirement roadmap/.test(s))
})
test('retirement render: error and unavailable states print no figure and keep last-good out of "current"',()=>{
  const bad=a.ret.adaptRetirement(env(null,{ok:false,error:'HTTP 502',lastGoodAt:'2040-01-01T00:00:00Z'}),0)
  const s=html(h(a.RetirementPage,{retirement:bad,research:a.ret.adaptResearch(env({ok:false}))})),t=text(s)
  assert.equal(bad.kind,'error'); assert.ok(/data-state="error"/.test(s)); assert.ok(t.includes('not shown as current'))
  assert.ok(!/\$\d/.test(t))
  assert.equal(a.ret.adaptRetirement(env({ok:false}),0).kind,'error')
})
test('retirement: research themes render; advisory flag is stated',()=>{
  const r=a.ret.adaptResearch(env({ok:true,data:{as_of:'2040-01-01T00:00:00Z',advisory_only:true,total:1,themes:[{theme:'Synthetic theme',count:1,items:[{topic:'QZ topic',status:'open',confidence:0.5,at:'2040-01-01',source_count:2}]}]}}))
  assert.equal(r.kind,'ok')
  const t=text(html(h(a.RetirementPage,{retirement:{kind:'loading'},research:r})))
  assert.ok(t.includes('Synthetic theme')&&t.includes('advisory'))
})

// ---- Levels ----
test('levels: symbol validation builds a path only for valid symbols',()=>{
  assert.equal(a.lv.levelsPathFor('qzaa'),'/api/v2/indicators/levels?symbol=QZAA')
  assert.equal(a.lv.levelsPathFor('a b'),null); assert.equal(a.lv.levelsPathFor(''),null)
})
const page=st=>html(h(a.LevelsPage,{state:st,draft:'',onDraft(){},onSubmit(){}}))
test('levels render: idle, served (grouped, freshness Unknown), empty, error; valuation always not wired',()=>{
  const idle=page({kind:'idle'}); assert.ok(/data-state="idle"/.test(idle)); assert.ok(/data-missing="valuation"/.test(idle))
  const ok=a.lv.adaptLevels('QZAA',env({ok:true,symbol:'QZAA',levels:[{type:'fib_0.5',label:'Fib 50.0%',price:10.5,color:'#fff'},{type:'stop',label:'Stop',price:9},{type:'bb_upper',label:'BB Upper',price:0}]}))
  assert.equal(ok.kind,'ok'); assert.equal(ok.model.levels.length,2,'price 0 is dropped, not shown')
  const s=page(ok),t=text(s)
  assert.ok(t.includes('Fibonacci')&&t.includes('$10.50')&&t.includes('freshness is Unknown'))
  assert.equal(a.lv.adaptLevels('QZAA',env({ok:true,levels:[]})).kind,'empty')
  const er=a.lv.adaptLevels('QZAA',env(null,{ok:false,error:'HTTP 500'}))
  assert.equal(er.kind,'error'); assert.ok(/data-state="error"/.test(page(er)))
  assert.equal(a.lv.adaptLevels('QZAA',env({ok:false,error:'symbol required'})).kind,'error')
  assert.ok(!/cheap|expensive|undervalued/i.test(t))
})
