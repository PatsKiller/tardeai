/**
 * FQ-106 / FQ-108: render the real Risk Market risk panel with synthetic API data.
 * Numeric account budgets must come from budgets_detail, not the names-only engine list.
 * A category's name and source state stay together above its detail when phone grids collapse.
 * Source states and configured thresholds are preserved; no broker or live state is read.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// React's expected SSR layout-effect warning carries huge data: module stacks.
// Match only this known message; every other console.error keeps its original arguments.
const SSR_LAYOUT_WARNING = 'Warning: useLayoutEffect does nothing on the server, because its effect cannot ' +
  "be encoded into the server renderer's output format. This will lead " +
  'to a mismatch between the initial, non-hydrated UI and the intended ' +
  'UI. To avoid this, useLayoutEffect should only be used in ' +
  'components that render exclusively on the client. ' +
  'See https://reactjs.org/link/uselayouteffect-ssr for common fixes.'
const __origConsoleError = console.error
console.error = (...args) => {
  if (args[0] === SSR_LAYOUT_WARNING || args[0] === SSR_LAYOUT_WARNING + '%s') return
  __origConsoleError(...args)
}
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8').replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__conflictFixture')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { MemoryRouter } = require('react-router-dom')
globalThis.fetch = () => { throw new Error('Network forbidden in synthetic Risk rendering tests') }
const { W7RiskMarketRisk } = await import(compile(join(app, 'src/components/W7RiskPanels.tsx')))
const results=[]
function check(name,fn){try{fn();results.push({name,passed:true})}catch(e){results.push({name,passed:false,assertion:e.message.split('\n')[0]})}}
const category=(name,state,score,detail)=>({name,state,score,detail,as_of:'2030-01-07T20:00:00Z'})
const fixture={state:'evaluated',tier:'RED',score:58,as_of:'2030-01-07T20:00:00Z',stale:false,contributors:[],categories:[],book:{budgets:[{budget:'single_sector_pct',scope:'account',breached:true}]},budgets_detail:[
 {account_label:'Account Alpha',budget:'single_sector_pct',actual:62,limit:25,unit:'%',actual_usd:620,drivers:[]},
 {account_label:'Account Beta',budget:'single_sector_pct',actual:6,limit:12,unit:'%',actual_usd:60,drivers:[]},
]}
const render=mr=>renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(W7RiskMarketRisk,{data:{regime:{}},mr})))
check('FQ-106: numeric account rows replace names-only rows, with measured bar fills',()=>{
 const h=render(fixture);for(const t of ['Account Alpha','Account Beta','62%','25%','6%','12%'])assert.ok(h.includes(t),t)
 assert.ok(!h.includes('% / %'));assert.match(h,/width:100%/);assert.match(h,/width:50%/)
})
check('FQ-106: zero is measured; missing and nonfinite numbers have no numeric bar',()=>{
 const z=render({...fixture,budgets_detail:[{...fixture.budgets_detail[0],actual:0}]});assert.match(z,/0%/);assert.doesNotMatch(z,/Actual unavailable/)
 const m=render({...fixture,budgets_detail:[{...fixture.budgets_detail[0],actual:null}]});assert.match(m,/Actual unavailable/);assert.doesNotMatch(m,/data-testid="risk-market-budget-bar"/)
 const i=render({...fixture,budgets_detail:[{...fixture.budgets_detail[0],actual:NaN,limit:Infinity}]});assert.match(i,/Actual unavailable/);assert.match(i,/Limit unavailable/);assert.doesNotMatch(i,/data-testid="risk-market-budget-bar"/)
})
check('FQ-106: names-only breaches are retained with an explicit missing-number notice',()=>{
 const h=render({...fixture,budgets_detail:[]});assert.match(h,/single sector/);assert.match(h,/Budget numbers unavailable/);assert.ok(!h.includes('% / %'))
})
check('FQ-108: state belongs beside its category name, before its detail',()=>{
 const cats=[category('Technical','STRESS',80,'Synthetic technical signal'),category('Macro credit','CALM',0,'No stress signal'),category('Extended hours','UNKNOWN',null,'All synthetic proxies are stale')];const h=render({...fixture,categories:cats})
 for(const c of cats){const start=h.indexOf(c.name);assert.ok(start>=0);const tail=h.slice(start);assert.ok(tail.indexOf(c.state)<tail.indexOf(c.detail),`${c.name}: state must precede detail`)}
})
check('FQ-108: positive CALM score explains category warning level without relabelling producer state',()=>{
 const h=render({...fixture,categories:[category('Volatility','CALM',15,'Synthetic VIX 21 exceeds input threshold 20')]});assert.match(h,/CALM/);assert.match(h,/15/);assert.match(h,/below this category/);assert.match(h,/Synthetic VIX 21 exceeds input threshold 20/)
})
check('missing account/category labels are explicit and a zero limit is not a fake zero exposure',()=>{
 const h=render({...fixture,budgets_detail:[{...fixture.budgets_detail[0],account_label:null,limit:0}],categories:[category('', 'UNKNOWN', null, 'Source unavailable')]})
 assert.match(h,/Account scope unavailable/);assert.match(h,/Category name unavailable/);assert.match(h,/0% limit/)
 assert.match(h,/This limit is zero/);assert.doesNotMatch(h,/data-testid="risk-market-budget-bar"/)
})
console.log(JSON.stringify({results,passed:results.filter(x=>x.passed).length,failed:results.filter(x=>!x.passed).length},null,2));if(results.some(x=>!x.passed))process.exit(1)
