// Ops → Controls · Data approvals: summary strip, verdict labels, writer/freshness wording, filters and order.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/opsControlsData.test.ts
import {
  EXPLAINER, findingText, freshnessView, matchesDataFilter, scanText, sortRows, summarize, verdictView, writerText,
  type DataFinding, type DataRow,
} from './opsControlsData.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControls.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const files = (k: number) => ({ count: k, files: Array.from({ length: Math.min(k, 3) }, (_, i) => `scripts/f${i}.py`) })
const live = (w: number, findings: DataFinding[] = []) =>
  ({ writer_files: files(w), surface_reads: {}, store_readers: files(4), findings, warn_count: findings.length })
const ROWS: DataRow[] = [
  { domain: 'cio_prospect', verdict: 'READY_TO_APPROVE', writer: 'scripts/lib/cio_instrument_record.py', live: live(1),
    operator_note: { approval_given: true, decision: 'operator approval E (2026-10-22, approve-all)', pending: 'its own PR' } },
  { domain: 'paper_proposals', verdict: 'READY_TO_APPROVE', writer: null, writer_status: 'UNCONSOLIDATED', writer_target: 'scripts/lib/proposal_lifecycle.py',
    writer_target_status: 'to_build', live: live(51, [{ check: 'DICTIONARY_SECOND_WRITER', store: 'table:paper_trade_proposals', ceiling: 1, now: 51 }]) },
  { domain: 'operator_settings', verdict: 'NOT_READY', writer: null, writer_status: 'UNCONSOLIDATED', live: live(1),
    missing: ["declared projection 'operator_settings' is not in the data-broker catalog"] },
  { domain: 'old', verdict: 'APPROVED', writer: 'scripts/x.py', live: live(1) },
  { domain: 'pending', verdict: null },
]

t('summary strip counts from the rows', () => {
  const s = summarize(ROWS)
  eq([s.approved, s.ready, s.notReady, s.findings, s.unchecked], [1, 2, 1, 1, 1])
  eq(s.pendingPr, ['cio_prospect'])
  eq(summarize(null), { approved: 0, ready: 0, notReady: 0, findings: 0, unchecked: 0, pendingPr: [] })
})

t('verdict labels: operator-approved row with a pending PR is said so, never "approved"', () => {
  eq(verdictView(ROWS[0]).label, 'Approved by operator · PR pending')
  ok(verdictView(ROWS[0]).tip.includes('approval E'), 'tip cites the decision')
  eq(verdictView(ROWS[1]).label, 'Ready to approve')
  eq(verdictView(ROWS[2]).tone, 'warning')
  eq(verdictView(ROWS[3]).label, 'Approved')
  eq(verdictView(ROWS[4]).label, 'Checking…')
})

t('writer wording: single vs not consolidated, with today\'s count and target', () => {
  eq(writerText(ROWS[0]), 'scripts/lib/cio_instrument_record.py (single writer)')
  eq(writerText(ROWS[1]), 'Not consolidated — 51 writer files today; target scripts/lib/proposal_lifecycle.py (to_build)')
  eq(writerText({ writer: 'a.py', live: live(3) }), 'a.py (single writer) — 3 files write it today')
  eq(writerText({ writer: null, writer_status: 'UNCONSOLIDATED' }), 'Not consolidated — writers not yet counted')
})

t('freshness: measured / stale / missing / declared-column mismatch / unavailable', () => {
  eq(freshnessView({ state: 'MEASURED', age_h: 16.27, stale: false, stale_after_hours: 24, signal: 'file mtime' }).text, 'Updated 16.3 h ago')
  eq(freshnessView({ state: 'MEASURED', age_h: 0.5, stale: true, stale_after_hours: 0.25 }).text, 'Updated 30 min ago — stale')
  eq(freshnessView({ state: 'MEASURED', age_h: 0.5, stale: true }).tone, 'warning')
  eq(freshnessView({ state: 'MISSING', detail: 'table cio_prospect does not exist' }).text, 'Store does not exist')
  eq(freshnessView({ state: 'NO_SIGNAL', declared_signal_mismatch: true, detail: 'x' }).text, 'Declared time column not found')
  eq(freshnessView({ state: 'NO_SIGNAL', rows_estimate: 1200 }).tip.includes('~1,200 rows'), true)
  eq(freshnessView({ state: 'UNAVAILABLE' }).text, 'Freshness unavailable')
  eq(freshnessView(null).text, 'Not measured yet')
})

t('filters and order: not ready first, unchecked last', () => {
  eq(sortRows(ROWS).map(r => r.domain), ['operator_settings', 'cio_prospect', 'paper_proposals', 'old', 'pending'])
  eq(ROWS.filter(r => matchesDataFilter(r, 'findings')).map(r => r.domain), ['paper_proposals'])
  eq(ROWS.filter(r => matchesDataFilter(r, 'ready')).length, 2)
  eq(ROWS.filter(r => matchesDataFilter(r, 'all')).length, 5)
})

t('finding and scan wording', () => {
  eq(findingText({ check: 'NON_AUTHORITATIVE_READ', copy: 'file:x.json', now: 1 }), '1 page/API file read copy file:x.json')
  eq(scanText({ state: 'FAILED', error: 'boom' }).tone, 'danger')
  eq(scanText({ state: 'DONE', age_s: 12, duration_s: 15.2 }).text, 'Live scan 12s ago (took 15.2s)')
  eq(scanText(null).tone, 'warning')
})

t('explainer says what approval does and does not do', () => {
  ok(EXPLAINER.startsWith('Proposed = the data flows today'), 'proposed defined')
  ok(EXPLAINER.includes('fails the build') && EXPLAINER.includes('creates no table'), 'effect and non-effect')
})

console.log(`opsControlsData: ${n} passed`)
