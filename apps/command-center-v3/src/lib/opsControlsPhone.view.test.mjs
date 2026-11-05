/**
 * FQ-067 / FQ-068 (operator page audit 2026-11-04T0011Z, /system/ops-controls).
 *
 * FQ-067: the controls table clipped its Deploy and kill-switch columns on a 390 px phone. Fix: the
 * shared `ops-evidence-table` responsive contract (each row becomes a labelled card below 820 px).
 * FQ-068: the page led with source-writer diagnostics and many job rows before the controls, and an
 * unavailable page gave only the server's "forbidden" text. Fix: controls lead, the diagnostics block
 * starts closed on a phone, and the unavailable banner states the meaning plus the authorized route.
 */
import assert from 'node:assert/strict'
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
// The server renderer emits one `useLayoutEffect does nothing on the server` warning per component — expected in SSR,
// and each stack line embeds a multi-megabyte `data:` module URL. Unfiltered this file wrote 52 MB per build, which is
// ~99% of the `npm run build` log the CI jobs stream (cc-deepseek and cc-deepseek-5 on PR 2620, 2026-11-05). Same four
// lines as retirement.metric.view.test.mjs, health.labels.view.test.mjs and watchlist.labels.view.test.mjs.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}
const memo = new Map()
// Render-only window stub: these components read matchMedia/innerWidth during render, which a
// server-side render has no business depending on. Nothing here touches the network or storage.
if (typeof globalThis.window === 'undefined') {
  const listeners = new Set()
  globalThis.window = {
    innerWidth: 1200, innerHeight: 800,
    matchMedia: () => ({ matches: false, media: '', addEventListener: (_e, fn) => listeners.add(fn), removeEventListener: (_e, fn) => listeners.delete(fn) }),
    addEventListener() {}, removeEventListener() {},
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  }
}
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
    .replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
    .replace(/import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__opsFixture')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (existsSync(target) && statSync(target).isDirectory()) {
      target = ['index.ts', 'index.tsx', 'index.js'].map(s => resolve(target, s)).find(existsSync)
    }
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const mod = await import(compile(join(app, 'src/pages/OpsControls.tsx')))
const { Table, JobsTab, ControlsUnavailableBanner } = mod

globalThis.__opsFixture = { data: null, error: null, loading: false, stale: false, refetch() {} }
const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}
const wrap = el => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/system/ops-controls'] }, el))
const visible = html => html.replace(/<details[\s\S]*?<\/details>/g, '')

check('FQ-067: every controls cell carries its column label for the phone card layout', () => {
  const html = renderToStaticMarkup(React.createElement(Table, {
    label: 'Deploys and kill switch',
    heads: ['Control', 'State', 'Safe direction', 'Risky direction'],
    rows: [['Deploys', 'AUTO', 'STOP', 'Resume']],
  }))
  assert.match(html, /class="ops-evidence-table"/)
  assert.match(html, /data-label="Control"/)
  assert.match(html, /data-label="Safe direction"/)
  assert.match(html, /data-label="Risky direction"/)
})

check('FQ-068: controls lead; the diagnostics block is a details section', () => {
  const html = wrap(React.createElement(JobsTab, {
    d: { deploy: { state: 'OK', mode: 'AUTO', epoch: 1, latch: 'ABSENT' }, policy: { state: 'ACTIVE' } },
    run: () => {},
  }))
  const controls = html.indexOf('Deploys &amp; kill switch')
  const health = html.indexOf('data-testid="ops-jobs-health-details"')
  assert.ok(controls >= 0, 'the controls panel renders')
  assert.ok(health >= 0, 'the diagnostics section renders')
  assert.ok(controls < health, 'the controls panel comes before the diagnostics section')
  assert.match(html, /<details[^>]*data-testid="ops-jobs-health-details"[^>]*>/)
})

check('FQ-068: an unavailable page says who can use it and how to get access', () => {
  const html = renderToStaticMarkup(React.createElement(ControlsUnavailableBanner, {
    error: 'forbidden — this operator is not permitted this surface; this will not resolve by waiting',
  }))
  assert.match(visible(html), /Controls are limited to the operator; this session is not signed in with that role\./)
  assert.match(visible(html), /Open this page from the operator’s own Command Center session \(the tailnet address\), or ask the administrator to grant operator access\./)
  assert.doesNotMatch(visible(html), /forbidden — this operator is not permitted/)
  assert.match(html, /<details[^>]*>[\s\S]*forbidden — this operator is not permitted[\s\S]*?<\/details>/)
})

check('FQ-068: a generic read failure still says what is not shown', () => {
  const html = renderToStaticMarkup(React.createElement(ControlsUnavailableBanner, { error: 'HTTP 503' }))
  assert.match(visible(html), /The controls state could not be read, so the page will not show or accept a change\./)
  assert.match(html, /<details[^>]*>[\s\S]*HTTP 503[\s\S]*?<\/details>/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)
