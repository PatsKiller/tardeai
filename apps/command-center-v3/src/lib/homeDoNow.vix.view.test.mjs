// Rendering test for FQ-086 (finding 3): the DEFAULT Home route must carry the VIX clock contract.
//
// App.tsx's index route renders HomeHub, whose default branch is HomeDoNow, not the Board 14 desk page. Before this,
// HomeDoNow printed `Regime …, VIX <value>.` for every clock, so a stale, undated or future reading read exactly like a
// confident current one on the operator's default landing page (review cx-openai-3 F3 on PR #2654). This mounts the real
// route through the real router and asserts the rendered sentence for each clock class.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// One SSR warning per component, each stack line a multi-megabyte data: URL. Expected on the server; drop it only.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const { MemoryRouter } = require('react-router-dom')

globalThis.window = globalThis.window ?? {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  innerWidth: 1400, scrollTo() {}, location: { search: '' },
  localStorage: { getItem: () => null, setItem: () => {} },
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    .replace(/import \{([^}]*)\} from (['"][^'"]+['"])/g, (whole, names, spec) => {
      const list = names.split(',').map(s => s.trim()).filter(Boolean)
      const kept = list.filter(n => n !== 'useApi' && n !== 'useGovernance')
      const stubs = []
      if (list.includes('useApi')) stubs.push('const useApi = (...a: any[]): any => (globalThis as any).__apiFixture(String(a[0] ?? ""), a[2])')
      if (list.includes('useGovernance')) stubs.push('const useGovernance = (...a: any[]): any => (globalThis as any).__govFixture(...a)')
      const imp = kept.length ? `import { ${kept.join(', ')} } from ${spec}` : ''
      return [imp, ...stubs].filter(Boolean).join('\n')
    })
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, { compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, removeComments: true } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (existsSync(target) && statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture dependency index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { default: HomeHub } = await import(compile(join(app, 'src/pages/HomeHub.tsx')))

const NOW = Date.now()
const ago = (h) => new Date(NOW - h * 3600_000).toISOString()

let tradeAi = null
globalThis.__apiFixture = (url) => {
  const u = String(url)
  if (u.includes('/api/v2/trade-ai')) return { data: tradeAi, loading: false, error: null, stale: false, receivedAt: NOW }
  if (u.includes('/api/v2/risk-regime/latest')) return { data: { regime_label: 'calm' }, loading: false, error: null, stale: false, receivedAt: NOW }
  return { data: null, loading: false, error: null, stale: false, receivedAt: NOW }
}

// App.tsx's index route: HomeHub with no ?view=classic renders HomeDoNow.
const render = () => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(HomeHub, { onDrill: () => {} })))
const strip = (m) => m.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"')
  .replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/\s+/g, ' ').trim()
const vixState = (m) => /data-testid="home-market"[^>]*data-vix-state="([^"]*)"/.exec(m)?.[1] ?? '(absent)'

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

function rendered(reading) {
  tradeAi = { vix: 17.4, vix_source: 'trade_ai_run_summary', run_label: '1730', market_regime: 'calm', ...reading }
  const markup = render()
  return { markup, text: strip(markup), state: vixState(markup) }
}

// Fresh: the current, confident sentence is allowed and reads as before.
{
  const r = rendered({ vix_observation_time: ago(0.25) })
  check('a fresh reading states the current VIX on the default Home route',
    r.state === 'FRESH' && /Regime\s+calm\s*,\s*VIX 17\.4\./.test(r.text), `${r.state} :: ${r.text.slice(0, 300)}`)
  check('a fresh reading does not claim the age is unknown', !/observation time not recorded/.test(r.text), r.text.slice(0, 300))
}

// Stale 48h: never a bare confident number; the sentence says it is not current.
{
  const r = rendered({ vix_observation_time: ago(48) })
  check('a 48 h reading is STALE on the default Home route', r.state === 'STALE', r.state)
  check('a stale reading never renders a bare confident VIX sentence', !/VIX 17\.4\./.test(r.text), r.text.slice(0, 400))
  check('a stale reading says it is past the limit and not current',
    /past the 36 h limit — not current/.test(r.text), r.text.slice(0, 400))
}

// Future: the clock is unreadable, not the freshest reading.
{
  const r = rendered({ vix_observation_time: new Date(NOW + 3600_000).toISOString() })
  check('a future reading is UNDATED on the default Home route', r.state === 'UNDATED', r.state)
  check('a future reading says its age cannot be read', /observation time is in the future/.test(r.text), r.text.slice(0, 400))
  check('a future reading never renders a bare confident VIX sentence', !/VIX 17\.4\./.test(r.text), r.text.slice(0, 400))
}

// Undated: no clock at all is unknown, not current.
{
  const r = rendered({ vix_observation_time: null })
  check('a reading with no clock is UNDATED on the default Home route', r.state === 'UNDATED', r.state)
  check('an undated reading admits the age is unknown', /observation time not recorded/.test(r.text), r.text.slice(0, 400))
  check('an undated reading never renders a bare confident VIX sentence', !/VIX 17\.4\./.test(r.text), r.text.slice(0, 400))
}

// The visible sentence never carries the producer token; the raw source may live in the title (stripped here).
{
  const r = rendered({ vix_observation_time: ago(48) })
  check('the raw producer source token is not in the visible sentence', !/trade_ai_run_summary/.test(r.text), r.text.slice(0, 400))
}

const out = { schema: 'HomeDoNowVixView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0
