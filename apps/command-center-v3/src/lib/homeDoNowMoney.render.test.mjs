// node --experimental-strip-types src/lib/homeDoNowMoney.render.test.mjs
// FQ-087 (cx-openai-3 block): the money qualifier lived only on HomeClassic, which is NOT the default route
// (HomeHub renders HomeDoNow unless ?view=classic). This renders the DEFAULT page and asserts the qualifier
// is visible on it for a retained transport, and absent when the transport is clean and the data is fresh.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))

// Unfiltered this file writes ~501 MB of stderr per run: each SSR "useLayoutEffect does nothing on the server"
// warning embeds a multi-megabyte data: module URL, and this page renders enough components to emit dozens of them.
// It is in the build line, so every npm run build would pay that. Same filter as retirement.metric.view.test.mjs:19.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  location: { pathname: '/', search: '' },
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  source = source.replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (path: string): any => (globalThis as any).__homeFixture(path)')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
      let target = resolve(dirname(path), spec)
      const isFile = (p) => existsSync(p) && statSync(p).isFile()
      if (!isFile(target)) target = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx'].map(s => target + s).find(isFile)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      return `from ${JSON.stringify(compile(target))}`
    })
  }).join('\n')
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

// All amounts/counts below are independently chosen synthetic fixture data.
const NOW = Date.parse('2030-01-07T15:00:00Z')
Date.now = () => NOW
const freshClock = '2030-01-07T14:59:00Z'
globalThis.fetch = () => { throw new Error('Network forbidden in synthetic Home rendering') }
let overview
const fixture = () => ({
  portfolio_value: 18473.25, today_change: -18.75, today_pct: -0.1, position_count: 7,
  pipeline_status: 'fresh', pipeline_completed: freshClock, last_repriced: freshClock,
  observation: { surface_status: 'FRESH', envelopes: { holdings: {
    observed_at: freshClock, freshness: { status: 'FRESH', observed_at_utc: freshClock },
  } } },
})
globalThis.__homeFixture = (path) => ({
  data: String(path) === '/api/v2/overview' ? overview : null,
  loading: false, stale: false, error: null, transport: globalThis.__transport ?? 'OK', refetch() {},
})
const { default: HomeDoNow } = await import(compile(join(app, 'src/pages/HomeDoNow.tsx')))
const { default: HomeHub } = await import(compile(join(app, 'src/pages/HomeHub.tsx')))
const { positionsFreshness } = await import(compile(join(app, 'src/lib/homeDoNow.ts')))
let failed = 0
let passed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } else passed++ }
for (const mode of ['fresh', 'retained', 'old', 'missing', 'malformed', 'future',
  'source-stale', 'source-unavailable', 'surface-only-unavailable', 'holdings-only-stale']) {
  overview = fixture()
  globalThis.__transport = mode === 'retained' ? 'RETAINED' : 'OK'
  const env = overview.observation.envelopes.holdings
  const stamp = mode === 'old' ? '2030-01-06T14:00:00Z'
    : mode === 'future' ? '2030-01-07T16:00:00Z' : mode === 'malformed' ? 'invalid-clock' : freshClock
  overview.last_repriced = overview.pipeline_completed = env.observed_at = env.freshness.observed_at_utc = stamp
  if (mode === 'missing') {
    delete overview.last_repriced; delete overview.pipeline_completed
    delete env.observed_at; delete env.freshness.observed_at_utc
  }
  if (mode === 'source-stale') overview.observation.surface_status = env.freshness.status = 'STALE'
  if (mode === 'source-unavailable') overview.observation.surface_status = env.freshness.status = 'UNAVAILABLE'
  if (mode === 'surface-only-unavailable') overview.observation.surface_status = 'UNAVAILABLE'
  if (mode === 'holdings-only-stale') env.freshness.status = 'STALE'
  for (const surface of ['primary', 'classic']) {
    const Comp = surface === 'primary' ? HomeDoNow : HomeHub
    const html = renderToStaticMarkup(React.createElement(MemoryRouter,
      { initialEntries: [surface === 'primary' ? '/' : '/?view=classic'] },
      React.createElement(Comp, { onDrill() {} })))
    check(html.includes('18,473'), `${surface}/${mode}: synthetic amount did not render`)
    const qualifier = html.match(/data-testid="home-money-qualifier"[^>]*>([^<]*)<\/span>/)?.[1] ?? null
    check(mode === 'fresh' ? qualifier === null : !!qualifier,
      `${surface}/${mode}: ${mode === 'fresh' ? 'fresh control unexpectedly qualified' : 'unusable observation left bare money'}`)
    if (mode === 'retained') check(/last known|not refreshed/i.test(qualifier ?? ''), `${surface}: retained value must say last known`)
  }
  const state = positionsFreshness(overview, NOW, globalThis.__transport)
  check(mode === 'fresh' ? !state.stale && state.qualifier === null : state.stale && !!state.qualifier,
    `${mode}: positions state and money qualifier disagree`)
  if (mode === 'retained') check(/did not complete cleanly/i.test(state.tip), 'retained source tip lost its reason')
}
// The same existing 24 h file threshold applies when the market is closed.
for (const old of [false, true]) {
  const closedNow = Date.parse('2030-01-12T15:00:00Z')
  const stamp = new Date(closedNow - (old ? 25 : 0.25) * 3600000).toISOString()
  const value = fixture()
  value.last_repriced = stamp
  value.observation.envelopes.holdings.observed_at = stamp
  value.observation.envelopes.holdings.freshness.observed_at_utc = stamp
  const state = positionsFreshness(value, closedNow, 'OK')
  check(state.stale === old && !!state.qualifier === old, `closed-market old=${old}: state and money qualifier disagree`)
}
// A fresh observation clock is not evidence that an absent/malformed value is a known zero.
for (const valueCase of [
  { name: 'missing', pv: undefined, count: undefined, moneyKnown: false, countKnown: false },
  { name: 'null', pv: null, count: null, moneyKnown: false, countKnown: false },
  { name: 'malformed', pv: 'unavailable', count: 'not-a-count', moneyKnown: false, countKnown: false },
  { name: 'boolean', pv: true, count: true, moneyKnown: false, countKnown: false },
  { name: 'nonfinite', pv: NaN, count: Infinity, moneyKnown: false, countKnown: false },
  { name: 'fractional-count', pv: 0, count: 1.5, moneyKnown: true, countKnown: false },
  { name: 'negative-count', pv: 0, count: -1, moneyKnown: true, countKnown: false },
  { name: 'known-zero', pv: 0, count: 0, moneyKnown: true, countKnown: true },
]) {
  overview = fixture()
  overview.portfolio_value = valueCase.pv
  overview.position_count = valueCase.count
  globalThis.__transport = 'OK'
  const html = renderToStaticMarkup(React.createElement(MemoryRouter,
    { initialEntries: ['/?view=classic'] }, React.createElement(HomeHub, { onDrill() {} })))
  const titleAt = html.indexOf('class="hub-title-row"')
  if (titleAt < 0) throw new Error('Actual Classic header did not render')
  const header = html.slice(html.lastIndexOf('<div', titleAt), html.indexOf('Needs action', titleAt))
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  check(valueCase.moneyKnown ? /Home \$0\s*·/.test(header) : /Home —\s*·/.test(header),
    `classic/${valueCase.name}: subtitle must distinguish unknown money from known zero`)
  check(valueCase.countKnown ? /· 0 positions over \$100/.test(header) : /· — positions over \$100/.test(header),
    `classic/${valueCase.name}: subtitle must distinguish unknown count from known zero`)
}

console.log(JSON.stringify({ suite: 'homeDoNowMoney.render', passed, failed }))
if (failed) process.exit(1)
