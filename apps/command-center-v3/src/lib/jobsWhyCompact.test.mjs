// node --experimental-strip-types src/lib/jobsWhyCompact.test.mjs
// FQ-047 (/ops/jobs D): the phone list repeated a long cause, a last-success line and a Review button on
// every card. The row now carries a one-line summary and opens the full detail behind a toggle — with
// nothing removed: the full cause, the last-success line and the Review job button all still exist.
//
// This is a RENDERED test, not a source grep. It renders the real JobsHealth component, invokes the
// rendered jobs-why-toggle control, and asserts what a person sees before and after the tap. A toggle
// whose onClick does nothing leaves the detail closed and fails the "after the tap" assertions.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
}

// The component's own useState becomes a persistent store so a rendered toggle's setter can be invoked
// between renders without a browser. Every other React hook is the real one.
const REACT_URL = pathToFileURL(require.resolve('react')).href
const JSX_URL = pathToFileURL(require.resolve('react/jsx-runtime')).href
const REACT_SHIM = 'data:text/javascript;base64,' + Buffer.from(`
import * as React from ${JSON.stringify(REACT_URL)}
export * from ${JSON.stringify(REACT_URL)}
export default React.default
const store = globalThis.__whyCompactStore ?? (globalThis.__whyCompactStore = [])
export const useState = (init) => {
  const index = globalThis.__whyCompactCursor ?? 0
  globalThis.__whyCompactCursor = index + 1
  if (!(index in store)) store[index] = typeof init === 'function' ? init() : init
  return [store[index], (value) => { store[index] = typeof value === 'function' ? value(store[index]) : value }]
}
`).toString('base64')
// JSX elements are captured as they are created, so the test can invoke the rendered control's handler.
const JSX_SHIM = 'data:text/javascript;base64,' + Buffer.from(`
import * as RT from ${JSON.stringify(JSX_URL)}
export const Fragment = RT.Fragment
export const jsx = (type, props, key) => { const element = RT.jsx(type, props, key); (globalThis.__whyCompactElements ??= []).push(element); return element }
export const jsxs = (type, props, key) => { const element = RT.jsxs(type, props, key); (globalThis.__whyCompactElements ??= []).push(element); return element }
`).toString('base64')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  source = source.replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (path: string): any => (globalThis as any).__jobsFixture(path)')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (spec === 'react') return `from ${JSON.stringify(REACT_SHIM)}`
      if (spec === 'react/jsx-runtime') return `from ${JSON.stringify(JSX_SHIM)}`
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

const LONG_CAUSE = 'the nightly indicator cache refresh overlapped a market-data reconnect and the run was retried after the window closed'
const DATA = {
  rows: [], summary: { total: 1, due_today: 1, succeeded: 1, failed: 0, missed: 0, paused: 0, retired: 0 },
  total: 1, has_more: false, as_of: '2026-11-04T15:00:00Z', coverage_gaps: [],
  monitor: { status: 'RUNNING', cause: null, notification: null },
}
const ROW = {
  lane_id: 'lane-1', job: 'Indicator cache refresh', scheduler: 'systemd', state: 'ACTIVE', result: 'succeeded',
  last_run_at: '2026-11-04T14:00:00Z', last_success_at: '2026-11-04T14:00:00Z',
  next_due_at: '2026-11-04T15:00:00Z', due_today: true, missed_fires: 0, market_hours_only: false,
  cause: LONG_CAUSE,
}
globalThis.__jobsFixture = (path) => {
  DATA.rows = [ROW]
  if (String(path).includes('/api/v2/jobs-health')) {
    return { data: DATA, loading: false, error: null, refetch: () => {} }
  }
  return { data: null, loading: false, error: null, refetch: () => {} }
}

const { default: JobsHealth } = await import(compile(join(app, 'src/components/JobsHealth.tsx')))

// React warns loudly (repeatedly) because react-router's useLayoutEffect is a no-op under the server
// renderer; that is expected here. Keep our own FAIL lines and drop only that known warning.
function render() {
  globalThis.__whyCompactCursor = 0
  globalThis.__whyCompactElements = []
  const realError = console.error
  console.error = (...args) => {
    if (typeof args[0] === 'string' && args[0].startsWith('Warning: useLayoutEffect does nothing on the server')) return
    realError(...args)
  }
  try {
    const html = renderToStaticMarkup(
      React.createElement(MemoryRouter, null, React.createElement(JobsHealth, {})),
    )
    return { html, elements: [...globalThis.__whyCompactElements] }
  } finally {
    console.error = realError
  }
}

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// 1. Collapsed: a short summary is shown; the long cause, last success and Review are not on the card.
const collapsed = render()
const summary = LONG_CAUSE.slice(0, 80) + '…'
check(collapsed.html.includes(summary), 'the collapsed row does not show the 80-character why summary')
check(!collapsed.html.includes(LONG_CAUSE), 'the full cause is already on the collapsed card')
check(!collapsed.html.includes('data-testid="jobs-why-detail"'), 'the full why block is always rendered instead of on demand')
check(!collapsed.html.includes('Review job'), 'the Review job control is on the collapsed card instead of behind the toggle')
check(!collapsed.html.includes('Last success:'), 'the last-success line is on the collapsed card instead of behind the toggle')
check(/<button[^>]*data-testid="jobs-why-toggle"/.test(collapsed.html), 'the row has no button to open the full why')
check(collapsed.html.includes('Why ▾'), 'the collapsed toggle does not offer to open the why')

// 2. Tap the rendered control — the same handler a phone user taps.
const toggles = collapsed.elements.filter(el => el && el.props && el.props['data-testid'] === 'jobs-why-toggle')
check(toggles.length === 1, 'exactly one rendered jobs-why-toggle control was expected')
let tapped = false
if (toggles[0]) { toggles[0].props.onClick?.(); tapped = true }
check(tapped, 'the rendered why toggle has no click handler')

// 3. Opened: the detail carries the full cause, the last-success line and Review. Nothing was removed.
const opened = render()
check(opened.html.includes('data-testid="jobs-why-detail"'), 'tapping the why toggle did not open the full detail')
check(opened.html.includes(LONG_CAUSE), 'the opened detail does not carry the full cause')
check(opened.html.includes('Last success:'), 'the opened detail lost the last-success line')
check(opened.html.includes('Review job'), 'the opened detail lost the Review job control')
check(opened.html.includes('Hide why ▴'), 'the opened toggle does not offer to close the why')
check(opened.html.includes(summary), 'the compact summary disappeared when the detail opened')

if (failed) { console.error(`jobsWhyCompact: ${failed} failure(s)`); process.exit(1) }
console.log('jobsWhyCompact: ok')
