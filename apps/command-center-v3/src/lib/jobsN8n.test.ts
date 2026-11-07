// Ops › Jobs & n8n helpers (design pages/jobs v002). Synthetic lane ids only; no real holdings or account data.
//   node --experimental-strip-types src/lib/jobsN8n.test.ts
import {
  JOBS_N8N_TABS, TAB_HISTORY_FILTER, historyTiles, laneCard, moveToN8nSentence, n8nTiles, resolveJobsN8nTab, sortLanes, tabLabel,
} from './jobsN8n.ts'
import type { N8nRowX } from './opsControlsN8n.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const NOW = Date.parse('2026-11-06T20:00:00Z')
const lane = (id: string, extra: Partial<N8nRowX> = {}): N8nRowX => ({ lane_id: id, on_live_list: true, stage: 'canary', ...extra })

t('five tabs in the approved order; Needs you is the default', () => {
  eq(JOBS_N8N_TABS.map(([k]) => k), ['needs', 'all', 'checks', 'n8n', 'incidents', 'fixes'])
  eq(resolveJobsN8nTab(null), 'needs')
  eq(resolveJobsN8nTab('N8N'), 'n8n')
  eq(resolveJobsN8nTab('today'), 'needs')
  eq(resolveJobsN8nTab('fixes'), 'fixes')
})
t('job tabs read the existing jobs-history filters', () => {
  eq(TAB_HISTORY_FILTER, { needs: 'attention', all: 'all', fixes: 'fixed' })
})
t('a tab count shows only once it was read', () => {
  eq(tabLabel('Needs you', 22), 'Needs you · 22')
  eq(tabLabel('Needs you', 0), 'Needs you · 0')
  eq(tabLabel('Needs you', null), 'Needs you')
  eq(tabLabel('Needs you', undefined), 'Needs you')
})
t('history tiles never invent a zero', () => {
  const s = { jobs: 10, active: 9, with_missed: 2, missed_not_measured: 1, fixed_14d: 5, no_run_history: 3, failed: 1, ok: 4 }
  const tiles = historyTiles(s, 'needs')
  eq(tiles.map(x => x.label), ['Failed', 'Missed a run', 'Late', 'Ran OK', 'Ran, unproven', 'Fixed · 14 d'])
  eq(tiles.map(x => x.value), [1, 2, null, 4, null, 5])
  eq(historyTiles(null, 'needs').every(x => x.value === null), true)
  eq(historyTiles(s, 'fixes')[0], { label: 'Fixed · 14 d', value: 5, tone: 'success', key: 'fixed' })
})
t('n8n tiles: server summary first; cut over from summary or stage; unknown stays null', () => {
  const summary = { live_healthy: 3, live_failing: 1, rehearsing: 2, ready_to_promote: 1, never_ran: 0 }
  const rows = [lane('a', { stage: 'cutover' }), lane('b'), lane('c', { stage: 'cutover' })]
  eq(n8nTiles(summary, rows).map(x => x.value), [3, 1, 2, 2, 1, 0])
  eq(n8nTiles({ ...summary, cut_over: 16 }, rows)[3].value, 16)
  eq(n8nTiles(null, []).map(x => x.value), [null, null, null, null, null, null])
})
t('move-to-n8n sentence counts effective mode; absent outcomes say nothing', () => {
  eq(moveToN8nSentence([lane('a'), lane('b')]), null)
  const rows = [
    lane('a', { outcome: { effective_mode: 'live', health: 'OK' } }),
    lane('b', { stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'OK' } }),
    lane('c', { stage: 'cutover', outcome: { effective_mode: 'live', health: 'OK' } }),
  ]
  eq(moveToN8nSentence(rows), '2 of 3 lanes run for real through n8n; 1 rehearse (dry run) while cron still does the work; 1 is fully cut over (cron line removed).')
})
t('lane card says in words why a lane is not live', () => {
  const c = laneCard(lane('synthetic-lane', { on_live_list: false, live_exclusion: 'NO_WRAPPER', live_exclusion_text: 'needs the effect-claim wrapper', outcome: { effective_mode: 'dry_run', health: 'OK' } }), NOW)
  eq(c.why, 'Not on the live list: needs the effect-claim wrapper')
  eq(c.liveList.label, 'Not live')
  eq(c.stage.label, 'Canary — not live: not on the effective live list')
})
t('lane card: failing lane quotes the server health reason; unmeasured run says so', () => {
  const c = laneCard(lane('synthetic-fail', { outcome: { effective_mode: 'live', health: 'FAILING', health_reason: 'last run failed (exit 1)',
    last_run: { outcome: 'FAILED', mode: 'live', at: '2026-11-06T19:40:00Z' } } }), NOW)
  eq(c.why, 'last run failed (exit 1)')
  eq(c.health, { label: 'Failing', tone: 'danger' })
  eq(c.lastRun, { text: '20 min ago · failed', tone: 'danger' })
  const u = laneCard(lane('synthetic-unknown'), NOW)
  eq(u.lastRun.text, 'Not measured')
  eq(u.why, null)
})
t('lane card: blocked promotion is the why when nothing worse applies', () => {
  const c = laneCard(lane('synthetic-blocked', { stage: 'shadow', outcome: { effective_mode: 'dry_run', health: 'OK' },
    readiness: { verdict: 'BLOCKED', blocked_by: ['broker-reach check'] } }), NOW)
  eq(c.why, 'Blocked: broker-reach check')
  eq(c.promotion.label, 'Blocked')
})
t('lanes sort failing first', () => {
  const rows = [lane('b-ok', { outcome: { effective_mode: 'live', health: 'OK' } }), lane('a-fail', { outcome: { effective_mode: 'live', health: 'FAILING' } })]
  eq(sortLanes(rows).map(r => r.lane_id), ['a-fail', 'b-ok'])
})
console.log(`jobsN8n: ${n} passed`)
