// Isolated actual-header browser fixture (2026-11-02).
//
// Renders the REAL MetricStrip component in a real Chromium at 390px (phone)
// and 1440px (desktop), with EVERY useApi call mocked and the network blocked.
// It never talks to 127.0.0.1:7777 or any other host: page.setContent() + an
// inline IIFE bundle, and a page.route('**/*') that aborts and records every
// request. Any recorded request fails the run.
//
// What this PROVES:
//   * the real component renders the derived header banner for ready, unknown
//     (partial and all-empty), error and loading states;
//   * a settled-empty source is named and the Retry control is present;
//   * the responsive CSS really switches: .ms-compact is flex and the full row
//     is collapsed at 390px, and .ms-compact is hidden at 1440px;
//   * expanding the mobile header reveals the full tile row;
//   * no request is issued (fetch is replaced with a thrower and counted).
//
// What this does NOT prove:
//   * pixel layout / overflow / visual contrast (no screenshot diff here);
//   * a live backend response, a real browser storage origin (about:blank makes
//     localStorage throw, which the component already treats as collapsed);
//   * anything about the per-tile data values, which are synthetic {} payloads.
//
// Run: node scripts/test_metric_strip_header_fixture.mjs
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = resolve(HERE, '..', 'apps', 'command-center-v3')
const require = createRequire(join(APP, 'package.json'))
const esbuild = require('esbuild')
const { chromium } = require('@playwright/test')

const METRIC_STRIP = join(APP, 'src', 'components', 'MetricStrip.tsx')

// Every consumer of useApi in the rendered tree gets the same synthetic receipt
// store. No fetch, no timer, no retry ladder.
const MOCK_USE_API = `
export function useApi(path) {
  const all = globalThis.__HEADER_FEEDS || {}
  const f = all[path] || {}
  return {
    data: f.data !== undefined ? f.data : null,
    loading: !!f.loading,
    refreshing: false,
    error: f.error !== undefined ? f.error : null,
    stale: !!f.stale,
    receivedAt: null,
    transport: f.error ? 'ERROR' : 'OK',
    authState: null,
    refetch: () => { (globalThis.__REFETCH_CALLS = globalThis.__REFETCH_CALLS || []).push(path) },
  }
}
export function resetConnectionHealth() {}
export function signalApiRecover() {}
export function retryApiConnection() {}
export function useConnectionHealth() { return { degraded: false, failing: 0 } }
`

const ENTRY = `
import React from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import MetricStrip from ${JSON.stringify(METRIC_STRIP)}

globalThis.__FETCH_CALLS = []
globalThis.fetch = (...args) => {
  globalThis.__FETCH_CALLS.push(String(args[0]))
  throw new Error('network disabled by header fixture')
}

let root = null
globalThis.__renderHeader = (feeds) => {
  globalThis.__HEADER_FEEDS = feeds || {}
  globalThis.__REFETCH_CALLS = []
  const host = document.getElementById('root')
  if (root) { root.unmount(); root = null }
  if (host) host.innerHTML = ''
  root = createRoot(host)
  root.render(React.createElement(MemoryRouter, null, React.createElement(MetricStrip, { onDrill: () => {} })))
}
`

const mockPlugin = {
  name: 'header-fixture-mocks',
  setup(build) {
    build.onResolve({ filter: /(^|\/)hooks\/useApi(\.ts)?$/ }, () => ({ path: 'useApi', namespace: 'header-fixture' }))
    build.onLoad({ filter: /.*/, namespace: 'header-fixture' }, () => ({ contents: MOCK_USE_API, loader: 'js' }))
  },
}

const bundle = await esbuild.build({
  stdin: { contents: ENTRY, resolveDir: APP, sourcefile: 'header-fixture-entry.tsx', loader: 'tsx' },
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
  target: ['es2020'],
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [mockPlugin],
  logLevel: 'silent',
})
let js = bundle.outputFiles[0].text
if (/\b127\.0\.0\.1\b|\b:7777\b/.test(js)) {
  console.error('FAIL the fixture bundle references 127.0.0.1/:7777')
  process.exit(1)
}

// The real application stylesheet, with its one @import inlined. Concatenating
// (rather than re-parsing with a CSS tool) keeps the media queries verbatim.
const tokensCss = readFileSync(join(APP, 'src', 'styles', 'tokens.css'), 'utf8')
const css = readFileSync(join(APP, 'src', 'index.css'), 'utf8')
  .replace("@import './styles/tokens.css';", tokensCss)

const safe = (s) => s.replace(/<\/script>/gi, '<\\/script>').replace(/<\/style>/gi, '<\\/style>')
const html = `<!doctype html><html><head><meta charset="utf-8"><style>${safe(css)}</style></head><body><div id="root"></div><script>${safe(js)}</script></body></html>`

const V2 = '/api/v2'
const PATHS = {
  overview: `${V2}/overview`,
  readiness: `${V2}/paper-trade-readiness`,
  regime: `${V2}/risk-regime/latest`,
  tradeAi: `${V2}/trade-ai/summary`,
  gate: `${V2}/live-trading-gate`,
  health: `${V2}/health`,
  design: `${V2}/design-features`,
}

function fixture(overrides = {}) {
  const base = {
    [PATHS.overview]: { data: {} },
    [PATHS.readiness]: { data: {} },
    [PATHS.regime]: { data: {} },
    [PATHS.tradeAi]: { data: {} },
    [PATHS.gate]: { data: {} },
    [PATHS.health]: { data: {} },
    [PATHS.design]: { data: {} },
  }
  return { ...base, ...overrides }
}

const FIXTURES = {
  ready: fixture(),
  'partial-unknown': fixture({
    [PATHS.tradeAi]: { data: null, loading: false, error: null, stale: false },
  }),
  'partial-loading': fixture({
    [PATHS.regime]: { data: null, loading: true, error: null, stale: false },
  }),
  error: fixture({
    [PATHS.tradeAi]: { data: null, loading: false, error: 'HTTP 502', stale: false },
  }),
  'all-empty': fixture({
    [PATHS.overview]: { data: null, loading: false, error: null, stale: false },
    [PATHS.regime]: { data: null, loading: false, error: null, stale: false },
    [PATHS.tradeAi]: { data: null, loading: false, error: null, stale: false },
    [PATHS.gate]: { data: null, loading: false, error: null, stale: false },
    [PATHS.health]: { data: null, loading: false, error: null, stale: false },
  }),
  loading: fixture({
    [PATHS.overview]: { data: null, loading: true, error: null, stale: false },
    [PATHS.regime]: { data: null, loading: true, error: null, stale: false },
    [PATHS.tradeAi]: { data: null, loading: true, error: null, stale: false },
    [PATHS.gate]: { data: null, loading: true, error: null, stale: false },
    [PATHS.health]: { data: null, loading: true, error: null, stale: false },
  }),
}

let pass = 0, fail = 0
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}${detail ? ` — ${detail}` : ''}`) }
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const requests = []
await page.route('**/*', route => {
  requests.push(route.request().url())
  route.abort()
})
await page.setContent(html, { waitUntil: 'load' })

async function renderAt(width, height, state) {
  await page.setViewportSize({ width, height })
  await page.evaluate(feeds => globalThis.__renderHeader(feeds), FIXTURES[state])
  await page.waitForSelector('.metric-strip', { state: 'attached' })
  await page.waitForTimeout(60)
}

const display = (sel) => page.$eval(sel, el => getComputedStyle(el).display).catch(() => null)
const text = (sel) => page.$eval(sel, el => (el.textContent || '').trim()).catch(() => null)
const count = (sel) => page.$$eval(sel, els => els.length).catch(() => 0)
const bannerState = () => page.$eval('[data-header-state]', el => el.getAttribute('data-header-state')).catch(() => null)

// ── desktop 1440 ────────────────────────────────────────────────────────────
console.log('\ndesktop 1440px')
await renderAt(1440, 900, 'ready')
check('desktop hides the compact header', (await display('.ms-compact')) === 'none')
check('desktop shows the full tile row', (await display('.metric-strip-row')) !== 'none')
check('ready renders no banner', (await count('[data-header-state]')) === 0)
check('ready renders the PORTFOLIO tile', (await text('.metric-strip-row')).includes('PORTFOLIO'))
check('ready renders the TODAY tile', (await text('.metric-strip-row')).includes('TODAY'))

await renderAt(1440, 900, 'partial-unknown')
check('partial-unknown renders an unknown banner', (await bannerState()) === 'unknown')
check('partial-unknown banner names the empty source', (await text('[data-header-state]')).includes('trade AI summary'))
check('partial-unknown banner says no payload', /no payload/i.test(await text('[data-header-state]')))
check('partial-unknown banner offers Retry', (await count('[data-header-state] button')) === 1)
check('partial-unknown keeps the loaded tiles on screen', (await text('.metric-strip-row')).includes('PORTFOLIO'))

await renderAt(1440, 900, 'partial-loading')
check('partial-loading renders a loading banner', (await bannerState()) === 'loading')
check('partial-loading banner says remaining', /remaining/i.test(await text('[data-header-state]')))
check('partial-loading has aria-busy', (await page.$eval('[data-header-state]', el => el.getAttribute('aria-busy'))) === 'true')
check('partial-loading offers no Retry', (await count('[data-header-state] button')) === 0)

await renderAt(1440, 900, 'error')
check('error renders an error banner', (await bannerState()) === 'error')
check('error banner has role=alert', (await page.$eval('[data-header-state]', el => el.getAttribute('role'))) === 'alert')
check('error banner carries the transport text', (await text('[data-header-state]')).includes('HTTP 502'))
check('error banner offers Retry', (await count('[data-header-state] button')) === 1)

await renderAt(1440, 900, 'all-empty')
check('all-empty renders an unknown banner', (await bannerState()) === 'unknown')
check('all-empty banner says no payload', /no payload/i.test(await text('[data-header-state]')))
check('all-empty paints no tile row of em dashes', (await count('.metric-strip-tile')) === 0)

// ── mobile 390 ──────────────────────────────────────────────────────────────
console.log('\nmobile 390px')
await renderAt(390, 844, 'ready')
check('mobile shows the compact header', (await display('.ms-compact')) === 'flex')
check('mobile collapses the full row by default', (await display('.metric-strip-row')) === 'none')
check('mobile compact shows PORT', (await text('.ms-compact')).includes('PORT'))
check('mobile compact shows TODAY', (await text('.ms-compact')).includes('TODAY'))
await page.click('.ms-compact__toggle')
await page.waitForTimeout(50)
check('mobile expand reveals the full tile row', (await display('.metric-strip-row')) !== 'none')

await renderAt(390, 844, 'partial-unknown')
check('mobile partial-unknown banner is visible', (await bannerState()) === 'unknown')
check('mobile partial-unknown offers Retry', (await count('[data-header-state] button')) === 1)
check('mobile still shows loaded compact cells', (await text('.ms-compact')).includes('PORT'))

await renderAt(390, 844, 'all-empty')
check('mobile all-empty names the state in the compact line', (await text('[data-header-compact-state]')) === 'Header unavailable')
check('mobile all-empty banner is unknown', (await bannerState()) === 'unknown')

// ── isolation ───────────────────────────────────────────────────────────────
const fetchCalls = await page.evaluate(() => globalThis.__FETCH_CALLS || [])
check('the component issued no fetch call', fetchCalls.length === 0, JSON.stringify(fetchCalls))
check('no HTTP request left the page', requests.length === 0, JSON.stringify(requests))

await browser.close()

console.log(`\nheader fixture: ${pass} passed, ${fail} failed`)
process.exitCode = fail ? 1 : 0
