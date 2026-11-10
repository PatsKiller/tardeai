// node --experimental-strip-types src/lib/jobRunHistory.lq1842.test.mjs
// LQ-20261107-1842: the page RENDERS the backend's one display decision (JobDisplayStatus@v1) and never recomputes
// green/amber from status + quality. Renders the real list card and detail against synthetic rows only.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { pathname: '/', search: '', href: 'http://synthetic.invalid/' } }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
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

const { HistoryCard, HistoryDetail } = await import(compile(join(app, 'src/components/JobRunHistory.tsx')))
const { displayOf } = await import(compile(join(app, 'src/lib/jobRunHistory.ts')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el) => renderToStaticMarkup(el)
const noop = () => {}
const COMPUTED = '2026-11-10T21:20:00Z'

const run = (over) => ({ run_id: 'd:synthetic-lane:live:20261110T2100', source: 'n8n run ledger', mode: 'live',
  result: 'succeeded', requested_at: '2026-11-10T21:00:05Z', started_at: '2026-11-10T21:00:05Z',
  finished_at: '2026-11-10T21:00:35Z', exit_code: 0, duration_s: 30, attempt: 1, retry_of: null,
  requested_by: 'n8n:workflow:synthetic', inline_attempts: null, reason: null, ...over })
const row = (over) => ({ lane_id: 'synthetic-lane', job: 'Synthetic lane', scheduler: 'n8n', state: 'ACTIVE',
  status: 'ok', status_reason: null,
  cadence: { expressions: ['*/30 * * * *'], timezone: 'America/New_York', every_hours: 0.5, market_days_only: false },
  last_run: run(), last_success_at: '2026-11-10T21:00:35Z', missed_count: 0, missed_gap: null, fix_count: 0,
  last_fix: null, history_sources: ['n8n run ledger'], history_gap: null, output_written_at: null, ...over })
const display = (over) => ({ schema: 'JobDisplayStatus@v1', green: false, tone: 'warning',
  label: 'Ran on time, result unproven', reason: 'Ran live 20 min ago and exited ok, but nothing can check its output',
  quality: 'UNPROVEN', ...over })
const card = (r) => h(React.createElement(HistoryCard, { row: r, computedAt: COMPUTED, onOpen: noop }))
const detail = (r) => h(React.createElement(HistoryDetail, { row: { ...r, runs: [], slots: [], fixes: [], output: null }, computedAt: COMPUTED }))

// A status-ok row whose result was not GOOD: the backend said amber, so the card must not read "Running on schedule".
const amber = card(row({ display: display() }))
check(/data-green="false"/.test(amber), 'amber: data-green is false')
check(amber.includes('Ran on time, result unproven'), 'amber: the backend label is rendered as-is')
check(!amber.includes('Running on schedule'), 'amber: an ok status never reads "Running on schedule"')
check(amber.includes('nothing can check its output'), 'amber: the quality reason is shown under the chip')

// The UI must not upgrade a payload: status ok AND quality GOOD but the backend said not green (e.g. an older
// payload or a display rule the page does not know). The field wins; recomputing here would be a second calculation.
const withheld = card(row({ status: 'ok', quality: { grade: 'GOOD' }, display: display({ quality: 'GOOD', label: 'Ran on time, unconfirmed' }) }))
check(/data-green="false"/.test(withheld), 'the page renders green=false from the field even when status+quality look green')
check(withheld.includes('Ran on time, unconfirmed'), 'the page renders the field label, not one it computed')

// And the green case: whatever the status, the backend's green decision renders.
const green = card(row({ display: display({ green: true, tone: 'success', label: 'Running on schedule', reason: null, quality: 'GOOD' }) }))
check(/data-green="true"/.test(green), 'green: data-green is true')
check(green.includes('Running on schedule'), 'green: label rendered')

// A payload from before the field existed has no decision: never green.
const legacy = card(row({ status: 'ok' }))
check(/data-green="false"/.test(legacy), 'a row with no display field is never green')
check(legacy.includes('Running on schedule'), 'a legacy row still shows its own status words')

// IDLE: the backend amber label names why, and the quality chip says Idle (not Good).
const idle = card(row({ quality: { grade: 'IDLE', sub: 'all_already_settled', headline: 'every item had already settled' },
  display: display({ label: 'Ran on time, result nothing to do', reason: 'Ran live 20 min ago; nothing to do: every item had already settled (receipt says all_already_settled)', quality: 'IDLE' }) }))
check(idle.includes('Ran on time, result nothing to do'), 'IDLE: the display label names the no-work result')
check(!/data-green="true"/.test(idle), 'IDLE: never green')
check(idle.includes('all_already_settled') || idle.includes('already settled'), 'IDLE: the reason is on the card')

// Detail sheet renders the same field.
const detailHtml = detail(row({ display: display(), quality: { grade: 'UNPROVEN', headline: 'nothing can check its output' } }))
check(/data-green="false"/.test(detailHtml), 'detail: data-green false')
check(detailHtml.includes('Ran on time, result unproven'), 'detail: backend label')
check(detailHtml.includes('run status said: Running on schedule'), 'detail: names the row status it replaces')

// The pure helper is a pass-through: it returns the field object itself.
const field = display()
check(displayOf({ status: 'ok', display: field }) === field, 'displayOf returns the backend field untouched')
const fallback = displayOf({ status: 'ok' })
check(fallback.green === false && fallback.label === 'Running on schedule', 'displayOf fallback is non-green with the status words')
// REWORK 1 (M2): green is the backend's decision — a payload with no decision has no green to give, and a
// status-only 'ok' must not paint the chip green either. The words say what the status said; the colour says nothing.
check(fallback.tone === 'neutral', 'M2: the no-decision fallback is neutral, never success on status ok')
const legacyFailed = displayOf({ status: 'failed', status_reason: 'Exit code 2' })
check(legacyFailed.green === false && legacyFailed.reason === 'Exit code 2', 'a legacy non-ok row keeps its status reason')
check(legacyFailed.tone === 'neutral', 'M2: a no-decision row is neutral whatever its status; the label carries the status')

if (failed) { console.error(`jobRunHistory.lq1842: ${failed} failed`); process.exit(1) }
console.log('jobRunHistory.lq1842: all checks passed')
