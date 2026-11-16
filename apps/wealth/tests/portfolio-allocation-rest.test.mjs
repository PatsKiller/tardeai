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
export {normalizeBook} from './src/pages/portfolio/analyticsAdapter'
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
test('allocation render: reconciliation renders its computed verdict, match and differs (FE review L2-8)',()=>{
  const s=html(h(a.AllocationPage,{book:a.FIXTURE_BOOK}))
  assert.match(s,/data-recon="match"/,'same rows, same basis: match is rendered')
  const t=text(s.slice(s.indexOf('data-recon=')))
  assert.ok(t.includes('Reconciles to the Holdings total')&&!t.includes('difference'),'match prints no difference')
  const rows=a.normalizeBook(a.FIXTURE_BOOK),base=a.drill.reconcileWithHoldings(rows,0,{valued:0,total:0}).holdingsTotal
  assert.equal(typeof base,'number')
  const ok=a.drill.reconcileWithHoldings(rows,base,a.drill.reconcileWithHoldings(rows,base,{valued:0,total:0}).holdingsCoverage)
  assert.equal(ok.status,'match'); assert.equal(ok.difference,0)
  const off=a.drill.reconcileWithHoldings(rows,base+500,ok.holdingsCoverage)
  assert.equal(off.status,'differs'); assert.equal(off.difference,500); assert.ok(off.text.startsWith('Does not reconcile'))
  const fewer=a.drill.reconcileWithHoldings(rows,base,{valued:ok.holdingsCoverage.valued-1,total:ok.holdingsCoverage.total})
  assert.equal(fewer.status,'differs','same total over different coverage is not a match')
  const none=html(h(a.AllocationPage,{book:{...a.FIXTURE_BOOK,rows:a.FIXTURE_BOOK.rows.map(r=>({...r,marketValue:null}))}}))
  assert.match(none,/data-recon="unknown"/,'nothing valued renders unknown, never match')
})

// ---- Retirement ----
const env=(data,o={})=>({ok:true,data,error:null,fetchedAt:'2040-01-01T12:00:00Z',lastGoodAt:null,...o})
// Shaped like api_v2 retirement() when holdings.json has a total, the roadmap stores no golden window, years
// or loan days, and dividend_calendar.json is missing (FE review L2-8). Synthetic values only.
//   total = canonical_total (so snapshot_delta = 0), start_age 68.5 and annual_conversion 50000 are producer
//   defaults, years_available / days_remaining / annual_total / yield_pct are zero-fills, end_age is a date string.
const SERVED={ok:true,data:{as_of:'2040-01-01',snapshot_source:'synthetic (generated 2039-12-30T00:00:00Z)',current_age:60,key_dates:{},
  accounts:{total:123456,roth:0,traditional:0,taxable:0},canonical_total:123456,snapshot_delta:0.0,
  loan:{balance:0,deadline:'',days_remaining:0,monthly_to_payoff:0},
  golden_window:{start_age:68.5,end_age:'2045-06-01',start_year:null,end_year:2045,annual_conversion:50000,bracket_ceiling:'',years_available:0,optimal_annual_conversion:50000,projected_roth_at_start:0,narrative:''},
  dividend_income:{annual:0,annual_total:0,monthly_avg:0,yield_pct:0.0,qualified_annual:0,current_month:{},top_payers:[]},
  timeline:[{year:2041,age:61,milestone:'Synthetic milestone'}],
  intelligence_brief:['Portfolio: $123,456 FIXED GROWTH TEXT'],projections:{base:999999}}}
const row=(t,k)=>{const m=t.match(new RegExp('<tr><th[^>]*>'+k.replace(/[()]/g,'\\$&')+'</th><td[^>]*>(.*?)</td></tr>'));return m?text(m[1]).trim():'absent'}
test('retirement adapter: producer defaults and zero-fills are Unknown, never their placeholder; withheld items are named',()=>{
  const s=a.ret.adaptRetirement(env(SERVED),Date.parse('2040-01-02T00:00:00Z'))
  assert.equal(s.kind,'ok'); const m=s.model
  assert.equal(m.accounts.roth.state,'unknown'); assert.equal(m.loan.balance.state,'unknown')
  assert.equal(m.accounts.total.state,'served'); assert.equal(m.ageDays,3)
  for(const f of [m.goldenWindow.startAge,m.goldenWindow.annualConversion,m.goldenWindow.yearsAvailable,m.loan.storedDaysRemaining,m.dividend.yieldPct,m.dividend.annualTotal,m.snapshotDelta])assert.equal(f.state,'unknown')
  assert.match(m.goldenWindow.startAge.reason,/default/); assert.match(m.snapshotDelta.reason,/withheld/)
  assert.deepEqual(m.goldenWindow.endAge,{state:'served',value:'2045-06-01 (served as a date, not an age)'})
  assert.ok(m.withheld.length>=5&&m.withheld.some(w=>/start age and annual conversion/.test(w)))
  // a served non-zero is still served
  const real=a.ret.adaptRetirement(env({...SERVED,data:{...SERVED.data,golden_window:{...SERVED.data.golden_window,end_age:70,years_available:4},loan:{...SERVED.data.loan,days_remaining:12},dividend_income:{annual_total:120,monthly_avg:10,yield_pct:0.1}}}),0).model
  assert.equal(real.goldenWindow.endAge.value,70); assert.equal(real.goldenWindow.yearsAvailable.value,4); assert.equal(real.loan.storedDaysRemaining.value,12); assert.equal(real.dividend.yieldPct.value,0.1)
  // yield with no served annual total is Unknown even if a yield is served
  assert.equal(a.ret.adaptRetirement(env({...SERVED,data:{...SERVED.data,dividend_income:{yield_pct:2}}}),0).model.dividend.yieldPct.state,'unknown')
})
test('retirement render: producer-shaped payload prints Unknown for defaults and zero-fills, the date as served, no delta row; withholds brief and projections',()=>{
  const ok=a.ret.adaptRetirement(env(SERVED),Date.parse('2040-01-02T00:00:00Z'))
  const s=html(h(a.RetirementPage,{retirement:ok,research:{kind:'loading'}})),t=text(s)
  assert.ok(/data-state="served"/.test(s)); assert.ok(t.includes('Not served, so not shown'))
  assert.ok(t.includes('2039-12-30')&&t.includes('read 2040-01-01'))
  for(const k of ['Start age','Annual conversion input','Years available','Days remaining (as stored at build, not recounted)','Yield on the served total','Roth','Balance'])
    assert.match(row(s,k),/^Unknown/,k+' renders Unknown (got '+row(s,k)+')')
  assert.equal(row(s,'End age'),'2045-06-01 (served as a date, not an age)')
  assert.match(row(s,'Portfolio total (holdings, or roadmap as fallback; which one is not served)'),/123,456/)
  assert.equal(row(s,'Roadmap minus holdings total'),'absent','structurally-zero difference is not rendered')
  assert.ok(!t.includes('68.5')&&!t.includes('50,000')&&!/\b0(\.0+)?%/.test(t),'no producer default or zero-fill printed')
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
  assert.ok(t.includes('2 sources'))
  const r0=a.ret.adaptResearch(env({ok:true,data:{as_of:'2040-01-01T00:00:00Z',advisory_only:true,total:1,themes:[{theme:'Synthetic theme',items:[{topic:'QZ topic'}]}]}}))
  const t0=text(html(h(a.RetirementPage,{retirement:{kind:'loading'},research:r0})))
  assert.ok(t0.includes('count not served')&&t0.includes('sources not served')&&!/\b0 sources/.test(t0),'missing counts are not served, never 0')
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

test('levels: cold BUILDING is not empty for bare and canonical wrapped replies',()=>{
  const cold={ok:true,status:'BUILDING',symbol:'QZAA',levels:[],reason:'Stored levels are not built yet'}
  for(const body of [cold,{ok:true,data:cold}]){
    const state=a.lv.adaptLevels('QZAA',env(body)); assert.equal(state.kind,'building')
    const s=page(state),t=text(s)
    assert.match(s,/data-state="building"/); assert.match(s,/role="status"/)
    assert.ok(t.includes('BUILDING')&&t.includes(cold.reason)&&t.includes('QZAA'))
    assert.ok(!s.includes('data-state="empty"')&&!s.includes('data-state="served"'))
    assert.ok(t.includes('not a known-empty or zero result'))
    assert.ok(!t.includes('fetches market data from an external provider'))
  }
})
test('levels: BUILDING never prints accidental cached values and wrapped served reply preserves levels',()=>{
  const raw={ok:true,symbol:'QZAA',levels:[{type:'pivot_p',label:'Synthetic pivot',price:123.45}]}
  const building=a.lv.adaptLevels('QZAA',env({...raw,status:'BUILDING'}))
  assert.equal(building.kind,'building'); assert.ok(!text(page(building)).includes('$123.45'))
  const served=a.lv.adaptLevels('QZAA',env({ok:true,data:raw}))
  assert.equal(served.kind,'ok'); assert.ok(text(page(served)).includes('$123.45'))
  assert.equal(a.lv.adaptLevels('QZAA',env({ok:true,data:{ok:true,levels:[]}})).kind,'empty')
  assert.equal(a.lv.adaptLevels('QZAA',env({ok:true,data:{ok:false,error:'Stored source unavailable'}})).kind,'error')
  for(const nested of [raw,{ok:true,levels:[]}]){
    const refused=a.lv.adaptLevels('QZAA',env({ok:false,error:'Synthetic outer refusal',data:nested}))
    assert.equal(refused.kind,'error'); assert.match(text(page(refused)),/Synthetic outer refusal/)
    assert.ok(!page(refused).includes('data-state="served"')&&!page(refused).includes('data-state="empty"'))
  }
})
