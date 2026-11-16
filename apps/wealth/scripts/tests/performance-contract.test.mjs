// Portfolio audit 2026-11-16 (E + section 4): the Performance page against the `performance_contract` block, with and
// without it (live 661a lacks it). Synthetic SYN_*/QZ* values only.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire, Module } from 'node:module'
const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), require = createRequire(import.meta.url)
const { buildSync } = require('esbuild')
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server')
const mod = (() => {
  const c = buildSync({ stdin: { contents: "export {PerformancePage} from './src/pages/portfolio/PerformancePage'; export {adaptPerformance,selectPerformance} from './src/pages/portfolio/performanceAdapter'", resolveDir: APP, loader: 'tsx' },
    bundle: true, write: false, platform: 'node', format: 'cjs', logLevel: 'silent', loader: { '.css': 'empty' }, external: ['react', 'react-router-dom'] }).outputFiles[0].text
  const f = path.join(APP, 'perf-contract-model.cjs'), m = new Module(f); m.filename = f; m.paths = Module._nodeModulePaths(APP); m._compile(c, f); return m.exports
})()
const NOW = Date.parse('2040-06-04T16:00:00Z'), OLD = '2040-06-01T16:00:00Z'
const cell = (o = {}) => ({ change: 100, change_pct: 1, start_value: 10000, end_value: 10100, start_date: '2040-05-01', source: 'synthetic snapshots', quality: 'reliable', flags: [], ...o })
const residual = cell({ change: 9000, change_pct: 90, nav_change: 9000, nav_change_pct: 90, display_change: 120, display_change_pct: 1.2, display_label: '≈ market (ex-transfers)', flags: ['ex_transfer_residual'], adjustment_method: 'household_residual_live_end', linked_start_value: 10000 })
const contractBody = (withContract) => ({
  periods: { '1W': cell() },
  accounts: { syn_a: { current_value: 1, periods: { '1W': cell(), '1M': residual } }, syn_b: { current_value: 1, periods: { '1W': cell({ change: null, change_pct: null }) } } },
  today_pnl: { status: 'UNKNOWN', observation_clock: { as_of: null, status: 'UNKNOWN' }, mark_batch_at: OLD, batch_built_at: OLD,
    stored_row_evidence: { source_values: [{ account_id: 'syn_a' }, { account_id: 'syn_b' }, { account_id: 'syn_c' }] },
    ...(withContract ? { represented_accounts: { count: 1, internal_keys: ['syn_a'] }, missing_accounts_stored_rows: { count: 2, internal_keys: ['syn_b', 'syn_c'] } } : {}) },
  market_session: { latest_open_session: '2040-06-04' }, clock_provenance: { quote: { as_of: OLD, status: 'OK' }, valuation: { as_of: OLD, status: 'OK' } },
  ...(withContract ? { performance_contract: { version: 'PerformanceContract@v1',
    periods: { '1W': { end_date: null, end_date_reason: 'not proven', observation_clock: { end: { as_of: null, date: null } }, external_flows: null, external_flows_reason: 'no ledger' } },
    accounts: { syn_a: {
      '1W': { eligibility: { status: 'eligible', source: 'synthetic registry' }, anchor: { snapshot_id: 'snap-1', date: '2040-05-01', source: 'last stored snapshot on or before the start date', start_value_matches_snapshot: true },
        residual_allocated: false, raw_change: 100, raw_change_pct: 1, end_date: '2040-06-01', observation_clock: { end: { as_of: OLD, date: '2040-06-01' } }, external_flows: null, external_flows_reason: 'no dated external-flow ledger' },
      '1M': { eligibility: { status: 'eligible', source: 'synthetic registry' }, anchor: { snapshot_id: null, date: '2040-05-01', source: 'last stored snapshot on or before the start date' },
        residual_allocated: true, raw_change: 9000, raw_change_pct: 90, end_date: '2040-06-01', external_flows: null, external_flows_reason: 'no dated external-flow ledger' } },
      syn_b: { '1W': { eligibility: { status: 'unknown', source: 'no result for this window; the producer does not say why' }, anchor: { snapshot_id: null, date: null, source: 'no stored snapshot' }, residual_allocated: false, raw_change: null, raw_change_pct: null, end_date: null, end_date_reason: 'no end value served', external_flows: null, external_flows_reason: 'no ledger' } } } } } : {}),
})
const html = (b, period) => { const r = mod.adaptPerformance(b, NOW, null); assert.ok(r.props, r.reason)
  const sel = mod.selectPerformance(r.props, null, period).props
  return renderToStaticMarkup(React.createElement(mod.PerformancePage, sel)) }

test('contract served: eligibility, interval, anchor, flows and the served census render', () => {
  const h = html(contractBody(true), '1W')
  assert.match(h, /Eligibility: eligible · synthetic registry/)
  assert.match(h, /Interval: 2040-05-01 → 2040-06-01/)
  assert.match(h, /Start anchor: snapshot snap-1 dated 2040-05-01/)
  assert.match(h, /Eligibility: unknown · no result for this window/)
  assert.match(h, /end not served \(no end value served\)/)
  assert.match(h, /External flows: not served — no dated external-flow ledger/)
  assert.match(h, /Producer stored-row census: 1 represented, 2 missing a day change/)
  assert.match(h, /No performance result for 1: Unlabelled account/)
})
test('residual-allocated value is flagged and shown beside the raw NAV change', () => {
  const h = html(contractBody(true), '1M')
  assert.match(h, /Includes household residual allocation, not account profit/)
  assert.match(h, /Allocated \+\$120\.00/)
  assert.match(h, /beside raw NAV change \+\$9,000\.00/)
  assert.match(h, /Raw NAV change \(before household residual allocation\): \+\$9,000\.00/)
})
test('old backend (no contract): everything says not served, residual stays withheld, nothing is guessed', () => {
  const b = contractBody(false)
  for (const a of Object.values(b.accounts)) a.eligibility = undefined
  const h = html(b, '1M')
  assert.match(h, /Eligibility: not served/); assert.match(h, /Start anchor: not served/); assert.match(h, /External flows: not served/)
  assert.match(h, /end not served/)
  assert.doesNotMatch(h, /Includes household residual allocation/)
  assert.doesNotMatch(h, /Producer stored-row census/)
  assert.match(h, /No performance result for 1/)
  assert.match(h, /not zero/)
})

test('probe p1: an unverified account 1D figure with eligibility unknown is refused, never shown as eligible', () => {
  const b = contractBody(true)
  b.accounts.syn_a.periods['1D'] = cell({ change: -555, change_pct: -5, start_date: '2040-06-03' })
  b.performance_contract.accounts.syn_a['1D'] = { eligibility: { status: 'unknown', source: 'no eligibility registry; a result is served but not certified' },
    anchor: { snapshot_id: null, date: null, source: 'none' }, residual_allocated: false, raw_change: -555, raw_change_pct: -5, end_date: null, end_date_reason: 'x', external_flows: null, external_flows_reason: 'none' }
  const h = html(b, '1D')
  assert.doesNotMatch(h, /Eligibility: eligible/)
  assert.doesNotMatch(h, /555/)
})
