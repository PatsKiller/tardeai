// Ops → Controls · n8n lanes dashboard model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/opsControlsN8n.test.ts
import {
  failuresBadge, GLOSSARY, healthView, isFailing, lastRunView, matchesN8nFilter, matchesN8nQuery, n8nFilterCounts,
  nextRunView, readinessView, runsText, sortRows, stageView, summaryOf, timeAgo, timeUntil, type N8nRowX,
} from './opsControlsN8n.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControlsJobs.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const NOW = Date.parse('2026-10-22T18:00:00Z')
const H = 3600_000
const at = (ms: number) => new Date(NOW - ms).toISOString()
const row = (p: Partial<N8nRowX>): N8nRowX => ({
  lane_id: 'lane-x', stage: 'canary', mode: 'live', on_live_list: true, workflow: 'tradeai-dispatcher', registry_state: 'ACTIVE',
  scheduler_kind: 'cron',
  outcome: {
    effective_mode: 'live', health: 'OK', health_reason: null, failures_24h: 0, failures_7d: 0,
    runs_7d: { dry_run: 2, live: 5 }, last_run: { run_id: 'd:lane-x:live:20261022T1000', mode: 'live', outcome: 'SUCCESS', at: at(3 * H) },
    next_run_at: '2026-10-23T14:00:00Z', schedule: ['0 10 * * 1-5'], tz: 'America/New_York',
  },
  readiness: { verdict: 'READY_FOR_CUTOVER', target: 'cutover', missing: [], blocked_by: [], evidence: ['live RUN_DONE'], owed: ['regression tests'] },
  ...p,
})

t('stage in plain words, corrected by what a fire really does', () => {
  eq(stageView(row({ stage: 'shadow', mode: 'dry_run' })).label, 'Rehearsing — not doing real work yet')
  eq(stageView(row({})).label, 'Live, watched (canary)')
  eq(stageView(row({ on_live_list: false, outcome: { effective_mode: 'dry_run' } })).key, 'canary_dry')
  ok(stageView(row({ on_live_list: false, outcome: { effective_mode: 'dry_run' } })).label.includes('not on the live list'), 'canary not listed says so')
  eq(stageView(row({ stage: 'cutover' })).label, 'Fully moved to n8n')
  eq(stageView(row({ registry_state: 'NEVER_SCHEDULED', outcome: { effective_mode: 'off' } })).label, 'Off — registry NEVER_SCHEDULED')
  eq(stageView(row({ stage: undefined, scheduler_kind: 'n8n' })).label, 'n8n-native — live')
})

t('glossary covers every word on the tab and states the live-list rule', () => {
  for (const k of ['shadow', 'canary', 'cutover', 'dry_run', 'live', 'live_list', 'promotion']) ok(GLOSSARY[k], `glossary ${k}`)
  ok(GLOSSARY.live_list.includes('TRADEAI_N8N_RELAY_LIVE_LANES'), 'names the env key')
  ok(GLOSSARY.promotion.includes('SKIPPED run does not count'), 'skip is not a live proof')
  ok(GLOSSARY.canary.includes('same lock'), 'canary = shared lock')
})

t('last run: ✓ / ✗ / skipped / never / not measured, with time-ago and the reason in the tooltip', () => {
  const s = lastRunView(row({}), NOW)
  eq([s.icon, s.text, s.tone], ['✓', '3 h ago · live', 'success'])
  const f = lastRunView(row({ outcome: { health: 'FAILING', last_run: { mode: 'live', outcome: 'FAILED', reason: 'output_unverifiable', at: at(40 * 60_000), run_id: 'r1' } } }), NOW)
  eq([f.icon, f.text, f.tone], ['✗', '40 min ago · failed', 'danger'])
  ok(f.tip.includes('output_unverifiable') && f.tip.includes('r1'), 'reason + run id in tooltip')
  const k = lastRunView(row({ outcome: { health: 'OK', last_run: { mode: 'live', outcome: 'SKIPPED', at: at(H) } } }), NOW)
  ok(k.icon === '↷' && k.tip.includes('not a live proof'), 'skip explained')
  eq(lastRunView(row({ outcome: { health: 'NEVER_RAN', last_run: null } }), NOW).text, 'never ran')
  eq(lastRunView(row({ outcome: undefined }), NOW).text, 'not measured')
  eq(lastRunView(row({ outcome: { health: 'UNKNOWN', health_reason: 'FileNotFoundError' } }), NOW).tip, 'FileNotFoundError')
})

t('time-ago / time-until', () => {
  eq(timeAgo(at(30_000), NOW), 'just now')
  eq(timeAgo(at(5 * 60_000), NOW), '5 min ago')
  eq(timeAgo(at(26 * H), NOW), '26 h ago')
  eq(timeAgo(at(72 * H), NOW), '3 d ago')
  eq(timeUntil('2026-10-23T14:00:00Z', NOW), 'in 20 h')
  eq(timeAgo('garbage', NOW), null)
})

t('health, failures badge, runs, next run', () => {
  eq(healthView(row({})).label, 'OK')
  eq(healthView(row({ outcome: { health: 'STALE', health_reason: 'missed 10:00' } })).reason, 'missed 10:00')
  eq(healthView(row({ outcome: undefined })).label, 'Not measured')
  eq(failuresBadge(row({})), null)
  eq(failuresBadge(row({ outcome: { failures_24h: 2, failures_7d: 3 } })), { text: '2 failed in 24 h · 3 in 7 d', tone: 'danger' })
  eq(failuresBadge(row({ outcome: { failures_24h: 0, failures_7d: 1 } }))?.tone, 'warning')
  eq(runsText(row({})), '5 live · 2 dry')
  ok(nextRunView(row({}), NOW)?.text.startsWith('in 20 h · Fri 10:00 ET'), `next run ${nextRunView(row({}), NOW)?.text}`)
  eq(nextRunView(row({ outcome: { effective_mode: 'live', next_run_at: null, schedule: [] } }), NOW)?.text, 'event-driven')
  eq(nextRunView(row({ outcome: { effective_mode: 'off' } }), NOW), null)
})

t('promotion readiness labels carry the missing evidence', () => {
  eq(readinessView(row({})).label, 'Ready for cutover')
  ok(readinessView(row({})).tip.includes('regression tests'), 'owed listed')
  const nr = readinessView(row({ readiness: { verdict: 'NOT_READY', target: 'cutover', missing: ['not on the relay live list', 'no live RUN_DONE'] } }))
  eq(nr.label, 'Not ready · 2 missing')
  ok(nr.tip.includes('not on the relay live list'), 'missing in tip')
  const b = readinessView(row({ readiness: { verdict: 'BLOCKED', blocked_by: ['health contract DRAFT'] } }))
  ok(b.label === 'Blocked' && b.tip.includes('DRAFT'), 'blocked reason')
  eq(readinessView(row({ readiness: { verdict: 'CUT_OVER' } })).label, 'Done')
  eq(readinessView(row({ readiness: undefined })).label, '—')
})

t('filters, counts, search, summary strip and sort', () => {
  const rows = [
    row({ lane_id: 'a-live' }),
    row({ lane_id: 'b-fail', outcome: { effective_mode: 'live', health: 'FAILING' }, readiness: { verdict: 'NOT_READY' } }),
    row({ lane_id: 'c-shadow', stage: 'shadow', mode: 'dry_run', outcome: { effective_mode: 'dry_run', health: 'OK' }, readiness: { verdict: 'READY_FOR_CANARY' } }),
    row({ lane_id: 'd-never', stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'NEVER_RAN' }, readiness: { verdict: 'NOT_READY' } }),
    row({ lane_id: 'e-off', registry_state: 'RETIRED', outcome: { effective_mode: 'off', health: 'OFF' }, readiness: { verdict: 'N_A' } }),
  ]
  eq(n8nFilterCounts(rows), { all: 5, failing: 1, ready: 2, shadow: 2, live: 2 })
  ok(matchesN8nFilter(rows[1], 'failing') && isFailing(rows[1]) && !matchesN8nFilter(rows[0], 'failing'), 'failing filter')
  ok(matchesN8nQuery(rows[2], 'SHAD') && !matchesN8nQuery(rows[2], 'zzz'), 'search')
  eq(summaryOf(rows, null), { live_healthy: 1, live_failing: 1, rehearsing: 2, ready_to_promote: 2, never_ran: 1 })
  eq(summaryOf(rows, { live_healthy: 62, live_failing: 1, rehearsing: 47, ready_to_promote: 32, never_ran: 4 })?.live_healthy, 62)
  eq(summaryOf([row({ outcome: undefined })], null), null)  // older server: no strip, never zeros
  eq(sortRows(rows).map(r => r.lane_id), ['b-fail', 'd-never', 'a-live', 'c-shadow', 'e-off'])
})

console.log(`opsControlsN8n: ${n} passed`)
