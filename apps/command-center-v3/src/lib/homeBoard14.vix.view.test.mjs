// Rendering test for FQ-086 (Board 14 Home): the VIX clock must come from the producer that actually emits it.
//
// The board receives the CIO page payload. Its `regime` object is built by scripts/lib/cio_truth.py::regime_for, which
// publishes the VIX clock as `vix_as_of` and has no `vix_source` at all. `vix_observation_time` belongs to the separate
// /api/v2/trade-ai projection. The old wiring read `vix_observation_time`, which this payload never carries, so every
// Home render said "observation time not recorded" while a real clock was present (review cc-deepseek-4 / cx-openai-3
// F1 on PR #2654). This test drives the measured producer shape through the REAL component, including a missing clock
// and a future clock, so the discarded clock cannot come back.
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

const { default: HomeBoard14 } = await import(compile(join(app, 'src/components/HomeBoard14.tsx')))

const NOW = Date.now()
const iso = (ms) => new Date(ms).toISOString()
const ago = (h) => iso(NOW - h * 3600_000)

// Exactly the keys scripts/lib/cio_truth.py::regime_for returns (measured at head 056955408): `vix_as_of` is the
// VIX clock; there is no `vix_source` and no `vix_observation_time` under `regime`.
function nativePayload(regime = {}) {
  return {
    regime: {
      age_hours: 0, as_of: ago(0.1), confidence: 0.62, gap: null, label: 'calm',
      parts: { volatility_state: 'low', trend_state: 'up', breadth_state: 'neutral', macro_state: 'neutral' },
      snapshot_id: 'snap-1', source: 'market_regime_snapshots', stale: false, vix: 17.4,
      vix_as_of: ago(0.25),
      ...regime,
    },
    do_now: { items: [], limit: 7, total: 0 },
    stops: {}, approvals: {}, questions: {}, releases: {}, sectors: {},
  }
}

const strip = (m) => m.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"')
  .replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/\s+/g, ' ').trim()
const render = (data) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] }, React.createElement(HomeBoard14, { data })))
const vixState = (m) => /data-testid="home-vix"[^>]*data-vix-state="([^"]*)"/.exec(m)?.[1] ?? '(absent)'

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

// 1. The native producer shape: vix_as_of present, vix_observation_time absent. If the board keeps reading
//    vix_observation_time (the regression), this is UNDATED and the age sentence never appears.
let m = render(nativePayload())
let t = strip(m)
check('native regime.vix_as_of is read as the VIX clock (FRESH at 15 min)',
  vixState(m) === 'FRESH' && /VIX 17\.4, 15 min old/.test(t), `${vixState(m)} :: ${t.slice(0, 300)}`)
check('it no longer says the age is unknown while carrying a real clock',
  !/observation time not recorded/.test(t), t.slice(0, 300))

// 2. Missing clock: the producer can emit vix_as_of=null. That is UNDATED, never an implied-current number.
m = render(nativePayload({ vix_as_of: null }))
t = strip(m)
check('a missing producer clock is UNDATED', vixState(m) === 'UNDATED', vixState(m))
check('and says the age is unknown', /observation time not recorded/.test(t), t.slice(0, 300))

// 3. Future clock: >5 min ahead is unreadable, not the freshest reading (cc-deepseek-6 F1 stays closed).
m = render(nativePayload({ vix_as_of: iso(NOW + 3600_000) }))
t = strip(m)
check('a future producer clock is UNDATED', vixState(m) === 'UNDATED', vixState(m))
check('and says the clock is in the future', /observation time is in the future/.test(t), t.slice(0, 300))

// 4. Stale clock: past the limit, named as not current, value still shown.
m = render(nativePayload({ vix_as_of: ago(48) }))
t = strip(m)
check('a 48 h clock is STALE', vixState(m) === 'STALE', vixState(m))
check('and says it is past the limit, not current', /past the 36 h limit — not current/.test(t), t.slice(0, 300))

// 5. The trade_ai projection key survives only as a documented fallback (a payload that carries it, no vix_as_of).
m = render(nativePayload({ vix_as_of: null, vix_observation_time: ago(0.25) }))
check('the separate trade_ai vix_observation_time is honoured as a fallback',
  vixState(m) === 'FRESH', vixState(m))

// 6. Precedence: when both exist, the producer's own vix_as_of wins over the foreign projection key.
m = render(nativePayload({ vix_as_of: ago(0.25), vix_observation_time: ago(48) }))
check('vix_as_of wins over vix_observation_time when both are present', vixState(m) === 'FRESH', vixState(m))

const out = { schema: 'HomeBoard14VixView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0
