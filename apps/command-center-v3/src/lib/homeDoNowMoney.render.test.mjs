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

// All amounts/counts below are newly chosen synthetic fixture data for this test. They are deliberately
// round placeholders (1,000,000.00 / -1,000.00 / 10) and are not copied from any account, holdings or BOARD record.
const NOW = Date.parse('2030-01-07T15:00:00Z')
Date.now = () => NOW
const freshClock = '2030-01-07T14:59:00Z'
globalThis.fetch = () => { throw new Error('Network forbidden in synthetic Home rendering') }
let overview
const fixture = () => ({
  portfolio_value: 1000000, today_change: -1000, today_pct: -0.1, position_count: 10,
  pipeline_status: 'fresh', pipeline_completed: freshClock, last_repriced: freshClock,
  observation: { surface_status: 'FRESH', envelopes: { holdings: {
    observed_at: freshClock, freshness: { status: 'FRESH', observed_at_utc: freshClock, threshold_hours: 24 },
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
    check(html.includes('1,000,000'), `${surface}/${mode}: synthetic amount did not render`)
    const qualifier = html.match(/data-testid="home-money-qualifier"[^>]*>([^<]*)<\/span>/)?.[1] ?? null
    check(mode === 'fresh' ? qualifier === null : !!qualifier,
      `${surface}/${mode}: ${mode === 'fresh' ? 'fresh control unexpectedly qualified' : 'unusable observation left bare money'}`)
    if (surface === 'primary') {
      const todayQualifier = html.match(/data-testid="home-today-money-qualifier"[^>]*>([^<]*)<\/span>/)?.[1] ?? null
      check(mode === 'fresh' ? todayQualifier === null : !!todayQualifier,
        `primary/${mode}: Today money must carry the same qualifier as Portfolio`)
    }
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

// FIRST cloud CX1/CX2: real CanonicalObservation@v1 fields from compute_freshness(),
// including its strict > cutoff boundary, legitimate zero, and repricer raw-ET clock.
// All clocks and amounts are independent synthetic data; no runtime stores are read.
const producerCases = [
  {
    "name": "changed-cutoff",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-11T09:00:00+00:00",
    "freshness": {
      "status": "FRESH",
      "age_seconds": 108000.0,
      "age_hours": 30.0,
      "threshold_hours": 48,
      "reason": "fresh:within_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-11T09:00:00+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": false
  },
  {
    "name": "cutoff-boundary",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-10T15:00:00+00:00",
    "freshness": {
      "status": "FRESH",
      "age_seconds": 172800.0,
      "age_hours": 48.0,
      "threshold_hours": 48,
      "reason": "fresh:within_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-10T15:00:00+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": false
  },
  {
    "name": "over-cutoff",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-10T14:59:59+00:00",
    "freshness": {
      "status": "STALE",
      "age_seconds": 172801.0,
      "age_hours": 48.0,
      "threshold_hours": 48,
      "reason": "stale:over_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-10T14:59:59+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": true
  },
  {
    "name": "zero-cutoff-boundary",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-12T15:00:00+00:00",
    "freshness": {
      "status": "FRESH",
      "age_seconds": 0.0,
      "age_hours": 0.0,
      "threshold_hours": 0,
      "reason": "fresh:within_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-12T15:00:00+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": false
  },
  {
    "name": "zero-cutoff-old",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-12T14:59:59+00:00",
    "freshness": {
      "status": "STALE",
      "age_seconds": 1.0,
      "age_hours": 0.0,
      "threshold_hours": 0,
      "reason": "stale:over_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-12T14:59:59+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": true
  },
  {
    "name": "no-agreed-cutoff",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-12T15:00:00+00:00",
    "freshness": {
      "status": "UNKNOWN",
      "age_seconds": 0.0,
      "age_hours": 0.0,
      "threshold_hours": null,
      "reason": "not_fresh:no_agreed_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-12T15:00:00+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": true
  },
  {
    "name": "repricer-raw-ET",
    "now": "2030-01-12T15:00:00+00:00",
    "raw": "2030-01-12 09:59:00 ET",
    "freshness": {
      "status": "FRESH",
      "age_seconds": 60.0,
      "age_hours": 0.017,
      "threshold_hours": 48,
      "reason": "fresh:within_threshold",
      "precision": "instant",
      "observed_at_utc": "2030-01-12T14:59:00+00:00",
      "evaluated_at_utc": "2030-01-12T15:00:00+00:00"
    },
    "qualified": false
  }
]
const renderMoneyQualifier = (surface) => {
  const Comp = surface === 'primary' ? HomeDoNow : HomeHub
  const html = renderToStaticMarkup(React.createElement(MemoryRouter,
    { initialEntries: [surface === 'primary' ? '/' : '/?view=classic'] },
    React.createElement(Comp, { onDrill() {} })))
  return html.match(/data-testid="home-money-qualifier"[^>]*>([^<]*)<\/span>/)?.[1] ?? null
}
for (const valueCase of producerCases) {
  overview = fixture()
  globalThis.__transport = 'OK'
  const now = Date.parse(valueCase.now)
  Date.now = () => now
  const env = overview.observation.envelopes.holdings
  overview.last_repriced = overview.pipeline_completed = env.observed_at = valueCase.raw
  env.freshness = { ...valueCase.freshness }
  overview.observation.surface_status = valueCase.freshness.status
  for (const surface of ['primary', 'classic']) {
    const qualifier = renderMoneyQualifier(surface)
    check(!!qualifier === valueCase.qualified,
      `${surface}/${valueCase.name}: producer cutoff/normalized clock must control qualification (got ${qualifier})`)
  }
  const state = positionsFreshness(overview, now, 'OK')
  check(state.stale === valueCase.qualified && !!state.qualifier === valueCase.qualified,
    `${valueCase.name}: positions state must agree with producer threshold`)
  check(state.ageS === valueCase.freshness.age_seconds, `${valueCase.name}: actual normalized observation age`)
  if (valueCase.name === 'changed-cutoff') check(state.tip.includes('48 h') && !state.tip.includes('24 h'),
    'changed cutoff: tooltip names supplied policy, not a frontend default')
}
// Corrupt/incomplete metadata must not invent an agreed cutoff or silently accept a boolean.
for (const cutoffCase of [
  { name: 'missing', cutoff: undefined }, { name: 'null', cutoff: null },
  { name: 'boolean', cutoff: true }, { name: 'numeric-string', cutoff: '48' },
  { name: 'malformed', cutoff: 'later' }, { name: 'negative', cutoff: -1 },
  { name: 'nonfinite', cutoff: Infinity }, { name: 'nan', cutoff: NaN },
]) {
  const now = Date.parse('2030-01-12T15:00:00Z')
  Date.now = () => now
  overview = fixture()
  const env = overview.observation.envelopes.holdings
  const stamp = new Date(now).toISOString()
  overview.last_repriced = overview.pipeline_completed = env.observed_at = env.freshness.observed_at_utc = stamp
  env.freshness.threshold_hours = cutoffCase.cutoff
  for (const surface of ['primary', 'classic']) check(!!renderMoneyQualifier(surface),
    `${surface}/${cutoffCase.name}: unusable cutoff must qualify money`)
  const state = positionsFreshness(overview, now, 'OK')
  check(state.stale && !!state.qualifier, `${cutoffCase.name}: unusable cutoff cannot claim positions fresh`)
}
// Keep the existing market-hours 30 min SLA even when the backend file cutoff is longer.
Date.now = () => NOW
overview = fixture()
{
  const env = overview.observation.envelopes.holdings
  env.freshness.threshold_hours = 48
  const stamp = new Date(NOW - 31 * 60000).toISOString()
  overview.last_repriced = overview.pipeline_completed = env.observed_at = env.freshness.observed_at_utc = stamp
  check(!!renderMoneyQualifier('primary'), 'market-hours 30 min positions SLA remains effective')
  check(!renderMoneyQualifier('classic'), 'Classic preserves its existing file-freshness scope')
}

console.log(JSON.stringify({ suite: 'homeDoNowMoney.render', passed, failed }))
if (failed) process.exit(1)
