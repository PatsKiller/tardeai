// LQ-20261107-611 · the Run-a-lane sheet at 390px (server render; no network, no storage, nothing is pressed).
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
    innerWidth: 390, innerHeight: 800,
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

const mod = await import(compile(join(app, 'src/components/RunLaneSheet.tsx')))
const RunLaneSheet = mod.default

const lane = (id, over = {}) => ({
  lane_id: id, family: id.split('-')[0], schedule: '*/15 * * * *',
  dry: { available: true, reason: null }, live: { available: true, reason: null, live_listed: true },
  run_all_live: { included: true, excluded_because: [] }, run_all_dry: { included: true }, last_receipt: null, ...over,
})
const view = {
  schema: 'OpsControlsLanes@v1', live_list_missing: false, market_open_today: true,
  lanes: [
    lane('alpha-ingest', { last_receipt: { state: 'RUN_DONE', exit_code: 0, duration_s: 2.5, output_signal_advanced: true, finished_at: '2026-11-08 09:00 ET' } }),
    lane('beta-send', { live: { available: false, reason: 'relay_live_not_enabled: lane is not on the relay live list', live_listed: false },
      run_all_live: { included: false, excluded_because: ['sends_to_operator_surface'] } }),
    lane('gamma-nodry', { dry: { available: false, reason: 'no_dry_run_arg: this lane has no dry-run mode' }, run_all_dry: { included: false } }),
  ],
  run_all: { dry_count: 2, live_count: 1, cooldown_s: 600, live_excluded: [{ lane_id: 'beta-send', reasons: ['sends_to_operator_surface'] }, { lane_id: 'gamma-nodry', reasons: ['x'] }] },
  note: 'Undo is not supported: a queued run is a request.',
}
const progress = { batch_id: 'opsreq_x', total: 3, finished: false,
  counts: { queued: 1, running: 1, done: 1, failed: 0, cancelled: 0 },
  runs: [{ run_id: 'opm-opsreq_x-000', lane_id: 'alpha-ingest', mode: 'dry_run', state: 'RUN_DONE', exit_code: 0, duration_s: 2.5, output_signal_advanced: true },
         { run_id: 'opm-opsreq_x-001', lane_id: 'beta-send', mode: 'dry_run', state: 'RUN_SKIPPED_LOCK', flock_held: true, reason: 'flock_held' },
         { run_id: 'opm-opsreq_x-002', lane_id: 'gamma-nodry', mode: 'dry_run', state: 'REQUESTED' }] }

const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}
const render = (props = {}) => renderToStaticMarkup(React.createElement(RunLaneSheet, { onClose() {}, start() {}, ...props }))
globalThis.__opsFixture = { data: { data: view }, error: null, loading: false, stale: false, refetch() {} }

check('390px: the sheet is a full-screen dialog that cannot scroll sideways', () => {
  assert.equal(globalThis.window.innerWidth, 390)
  const html = render()
  assert.match(html, /role="dialog"[^>]*aria-modal="true"/)
  assert.match(html, /position:fixed;inset:0/)
  assert.match(html, /overflow-x:hidden/)
  assert.match(html, /max-width:100vw/)
  const widths = [...html.matchAll(/[^-]width:(\d+)px/g)].map(m => Number(m[1]))
  assert.ok(widths.every(w => w <= 390), `no fixed width above 390px: ${widths}`)
})

check('lists every lane with Dry run and Live run, and the search box', () => {
  const html = render()
  assert.equal((html.match(/data-testid="run-lane-row"/g) || []).length, 3)
  assert.match(html, /data-testid="run-lane-search"/)
  assert.equal((html.match(/>Dry run</g) || []).length, 3)
  assert.equal((html.match(/>Live run</g) || []).length, 3)
  assert.match(html, /3 of 3 lanes/)
})

check('a live run that is not allowed is disabled and shows its reason', () => {
  const html = render()
  assert.match(html, /<button[^>]*disabled=""[^>]*title="relay_live_not_enabled[^"]*"[^>]*>Live run</)
  assert.match(html, /Live run unavailable: relay_live_not_enabled/)
  assert.match(html, /Dry run unavailable: no_dry_run_arg/)
})

check('the last receipt reads as exit, duration and output-signal advanced', () => {
  assert.match(render(), /Last: exit 0 · 2\.5 s · output signal advanced: yes/)
})

check('Run all shows both counts, the cooldown, and each excluded lane with its reason', () => {
  const html = render()
  assert.match(html, /Run all dry \(2\)/)
  assert.match(html, /Run all live \(1, passkey\)/)
  assert.match(html, /inside 10 minutes/)
  assert.match(html, /<b[^>]*>beta-send<\/b>: sends_to_operator_surface/)
  assert.match(html, /Undo is not supported/)
})

check('the progress view shows counts, flock_held, and a Cancel-queued button', () => {
  globalThis.__opsFixture = { ...globalThis.__opsFixture, data: { ...view, ...progress } }
  const html = render({ initialBatch: 'opsreq_x' })
  assert.match(html, /1 queued · 1 running · 1 done of 3/)
  assert.match(html, /flock_held/)
  assert.match(html, /data-testid="run-lane-cancel-queued"[^>]*>Cancel queued \(1\)</)
  globalThis.__opsFixture = { ...globalThis.__opsFixture, data: { ...view, ...progress, counts: { ...progress.counts, queued: 0 } } }
  assert.doesNotMatch(render({ initialBatch: 'opsreq_x' }), /run-lane-cancel-queued/)
})

check('an unreadable server still renders the sheet with the reason, and no lane buttons', () => {
  globalThis.__opsFixture = { data: null, error: 'forbidden', loading: false, stale: false, refetch() {} }
  const html = render()
  assert.match(html, /UNAVAILABLE — forbidden/)
  assert.doesNotMatch(html, /run-lane-row/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)
