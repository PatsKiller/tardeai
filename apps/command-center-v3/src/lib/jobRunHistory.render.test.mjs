// node --experimental-strip-types src/lib/jobRunHistory.render.test.mjs
// /ops/jobs Run history (operator 2026-11-06). RENDERS the real list card and detail and asserts what the operator sees:
// writer times in ET, honest not-measured reasons, retries/heals timeline, no table at phone width. Synthetic fixtures only.
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


const { HistoryCard, HistoryDetail, HistoryListView } = await import(compile(join(app, 'src/components/JobRunHistory.tsx')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el) => renderToStaticMarkup(el)
const noop = () => {}
const COMPUTED = '2026-01-07T15:07:00Z'

const run = (over) => ({ run_id: 'd:synthetic-lane:live:20260107T1500', source: 'n8n run ledger', mode: 'live', result: 'succeeded',
  requested_at: '2026-01-07T15:00:05Z', started_at: '2026-01-07T15:00:05Z', finished_at: '2026-01-07T15:00:35Z', exit_code: 0,
  duration_s: 30, attempt: 1, retry_of: null, requested_by: 'n8n:workflow:synthetic', inline_attempts: null, reason: null, ...over })
const listRow = (over) => ({ lane_id: 'synthetic-lane', job: 'Synthetic lane', scheduler: 'n8n', state: 'ACTIVE', status: 'ok',
  status_reason: null, cadence: { expressions: ['*/30 * * * *'], timezone: 'America/New_York', every_hours: 0.5, market_days_only: false },
  last_run: run(), last_success_at: '2026-01-07T15:00:35Z', missed_count: 0, missed_gap: null, fix_count: 0, last_fix: null,
  history_sources: ['n8n run ledger'], history_gap: null, output_written_at: null, ...over })
const wire = (rows) => ({ schema: 'JobRunHistory@v1', computed_at: COMPUTED, rows, total: rows.length, offset: 0, limit: 50,
  has_more: false, filter: 'attention', summary: { jobs: 3, active: 3, failed: 1, late: 0, with_missed: 1, missed_not_measured: 1, fixed_14d: 1, no_run_history: 1 },
  sources: [{ name: 'n8n run ledger', newest_record_at: '2026-01-07T15:00:05Z', covers_from: '2025-12-28T15:00:00Z', note: null }],
  gaps: ['the incident ledger could not be read'], note: 'Times are the writers’ own times.' })

// List: a failed job, a job with no per-run history, a healthy job.
const failedRow = listRow({ lane_id: 'synthetic-failed', job: 'Synthetic failed', status: 'failed', status_reason: 'Exit code 2',
  last_run: run({ result: 'failed', exit_code: 2 }), fix_count: 2,
  last_fix: { at: '2026-01-07T14:00:00Z', kind: 'retry', by: 'retry policy', outcome: 'failed', detail: 'Attempt 2', ref: null } })
const blindRow = listRow({ lane_id: 'synthetic-timer', job: 'Synthetic timer', scheduler: 'systemd', status: 'not_measured',
  status_reason: 'systemd runs are not written to a store this page reads', last_run: null, last_success_at: null, missed_count: null,
  missed_gap: 'No wall-clock schedule is declared for this job', history_sources: [], history_gap: 'systemd runs are not written to a store this page reads' })
const list = h(React.createElement(HistoryListView, { data: wire([failedRow, blindRow, listRow({})]), loading: false, error: null,
  filter: 'attention', onFilter: noop, query: '', onQuery: noop, onOpen: noop, onPage: noop }))
check((list.match(/data-testid="history-card"/g) || []).length === 3, 'three cards')
check(list.includes('Last run failed') && list.includes('Exit code 2'), 'failed status and reason shown')
check(list.includes('Not measured: No wall-clock schedule is declared for this job'), 'missed count not measured shows why')
check(!/Not measured: <\/div>/.test(list), 'never a bare Not measured')
check(list.includes('Run history: systemd runs are not written'), 'history gap shown on the card')
check(list.includes('2 events · latest retried'), 'fix count + latest fix on the card')
check(list.includes('Jan 7, 10:00 AM ET'), 'writer time rendered in ET')
check(list.includes('Unavailable: the incident ledger could not be read'), 'source gap disclosed')
check(list.includes('computed Jan 7, 10:07 AM ET'), 'computed time labelled as such')
check(!/<table/.test(list), 'no table (phone width)')
check(list.includes('grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr))'), 'list collapses to one column at 390')
check(/min-height:44px/.test(list), 'tap targets are 44 px')

const empty = h(React.createElement(HistoryListView, { data: null, loading: false, error: 'HTTP 503', filter: 'all', onFilter: noop,
  query: '', onQuery: noop, onOpen: noop, onPage: noop }))
check(empty.includes('Run history could not be read: HTTP 503') && empty.includes('No run history is available.'), 'error state')

// Detail: retry chain, missed slot, fixes.
const detailRow = { ...listRow({ status: 'missed', status_reason: 'No run recorded in the n8n run ledger for the 2026-01-07T14:30:00Z slot', missed_count: 1, fix_count: 2 }),
  output: null,
  runs: [run({ run_id: 'd:synthetic-lane:live:20260107T1500:a2', attempt: 2, retry_of: 'd:synthetic-lane:live:20260107T1500' }),
         run({ result: 'failed', exit_code: 1, reason: 'upstream timeout' }), run({ mode: 'dry_run' })],
  slots: [{ slot_at: '2026-01-07T15:00:00Z', status: 'ran', run_id: 'x', started_at: '2026-01-07T15:00:05Z' },
          { slot_at: '2026-01-07T14:30:00Z', status: 'missed', run_id: null, started_at: null },
          { slot_at: '2026-01-07T09:00:00Z', status: 'not_measured', run_id: null, started_at: null }],
  fixes: [{ at: '2026-01-07T15:01:40Z', kind: 'retry', by: 'retry policy', outcome: 'succeeded', detail: 'Attempt 2 of this slot after failed', ref: 'd:synthetic-lane:live:20260107T1500:a2' },
          { at: '2026-01-07T12:00:00Z', kind: 'self_healed', by: 'n8n failure diagnosis', outcome: 'resolved', detail: 'Failure episode resolved', ref: null }] }
const detail = h(React.createElement(HistoryDetail, { row: detailRow, computedAt: COMPUTED }))
check((detail.match(/data-testid="history-run"/g) || []).length === 3, 'three runs')
check(detail.includes('Retry, attempt 2'), 'retry badge')
check(detail.includes('Exit code 1') && detail.includes('upstream timeout'), 'failure detail')
check(detail.includes('Dry run'), 'dry run labelled')
check((detail.match(/data-testid="history-slot"/g) || []).length === 3 && detail.includes('No run') && detail.includes('Not measured'), 'slots')
check(detail.includes('Retried') && detail.includes('Self-healed') && detail.includes('by n8n failure diagnosis'), 'fix timeline')
check(detail.includes('Last success') && detail.includes('6 min ago'), 'last success relative to computed_at')

const blindDetail = h(React.createElement(HistoryDetail, { row: { ...blindRow, output: { path_kind: 'file_mtime', written_at: '2026-01-07T14:47:00Z', note: 'File write time of the job’s declared output; not proof of a successful run' },
  cadence: { ...blindRow.cadence, expressions: [], schedule_gap: 'No wall-clock schedule is declared for this job' }, runs: [], slots: [], fixes: [] }, computedAt: COMPUTED }))
check(blindDetail.includes('Why the run history is limited: systemd runs'), 'gap explained in detail')
check(blindDetail.includes('not proof of a successful run'), 'output time never claimed as success')
check(blindDetail.includes('No retry, heal or incident is recorded'), 'empty fixes honest')

if (failed) { console.error(`jobRunHistory.render: ${failed} failed`); process.exit(1) }
console.log('jobRunHistory.render: all checks passed')
