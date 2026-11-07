// Ops › Jobs & n8n › n8n catalog helpers (LQ-20261107-150). Synthetic lane ids only.
//   node --experimental-strip-types src/lib/n8nCatalog.test.ts
import {
  MODES, MODE_LABEL, MODE_TIP, VERDICT_MEANING, NOT_AUDITED, catalogStats, categoryLanes, laneChips, laneHref, notInRelay, scheduleText,
  verdictClassOf, verdictLabel, verdictTip, type CatalogLane,
} from './n8nCatalog.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const lane = (id: string, extra: Partial<CatalogLane> = {}): CatalogLane => ({ lane_id: id, category_key: 'ops', mode: 'live', in_relay: true, ...extra })

t('mode labels are the operator\'s words; never a bare "dry"', () => {
  eq(MODE_LABEL, { live: 'Live on n8n', both: 'n8n + cron (both)', dry: 'Dry run on n8n', none: 'Not on n8n' })
  for (const m of MODES) if (/(^|\s)dry(\s|$)/i.test(MODE_LABEL[m]) && !/Dry run/.test(MODE_LABEL[m])) fail(`bare dry in ${m}`)
})
t('mode tooltips are verbatim from the addendum', () => {
  eq(MODE_TIP.live, 'n8n is the only scheduler; the cron line is retired. Being live does not prove the data is right — see the audit verdict.')
  eq(MODE_TIP.both, 'n8n and cron are both scheduled. They share a lock, so whichever fires first runs and the other skips. The cron line is retired only after a verified live n8n run.')
  eq(MODE_TIP.dry, 'n8n runs it in report-only mode and writes nothing. It shows what it would do before the cutover.')
  eq(MODE_TIP.none, 'Stays on cron/systemd: broker, send class, always-on services, or not migrated yet.')
})
t('every verdict the audit uses, and "not audited", has a one-sentence meaning', () => {
  for (const v of ['PASS', 'PASS_IDLE', 'FAIL_DATA', 'FAIL_RUN', 'FAIL_CONFIG', 'FAIL_NO_OUTPUT', 'FAIL_CONSUMER', 'UNVERIFIABLE', NOT_AUDITED]) {
    if (!VERDICT_MEANING[v] || VERDICT_MEANING[v].length < 20) fail(`no meaning for ${v}`)
  }
})
t('only PASS and PASS_IDLE are working; no verdict is "not audited"', () => {
  eq(['PASS', 'PASS_IDLE', 'FAIL_DATA', 'HALLUCINATION', 'UNVERIFIABLE', null, ''].map(v => verdictClassOf(v)),
    ['pass', 'pass', 'fail', 'fail', 'not_provable', 'not_audited', 'not_audited'])
  eq(verdictLabel(null), 'Not audited')
  eq(verdictLabel('UNVERIFIABLE'), 'Not provable yet')
  eq(verdictLabel('FAIL_SOMETHING_NEW'), 'FAIL SOMETHING NEW')
})
t('verdict tooltip carries the meaning, then the defect, fix and work item', () => {
  const tip = verdictTip({ verdict: 'FAIL_DATA', defect: 'stale synthetic values', fix_suggestion: 're-key', work_item: 'LQ-20261107-999' })
  eq(tip, `${VERDICT_MEANING.FAIL_DATA} Defect: stale synthetic values Suggested fix: re-key Work item: LQ-20261107-999`)
  eq(verdictTip({ verdict: null }), VERDICT_MEANING[NOT_AUDITED])
  eq(verdictTip({ verdict: 'NEW_KIND' }), 'Audit verdict NEW_KIND.')
})
t('stats: four modes then audit PASS / FAIL / not provable; a missing count is null, never 0', () => {
  const s = catalogStats({ stats: { modes: { live: 68, both: 43, dry: 20, none: 436 }, audit: { pass: 25, fail: 37, not_provable: 16, audited: 78 } } })
  eq(s.map(x => x.label), ['Live on n8n', 'n8n + cron (both)', 'Dry run on n8n', 'Not on n8n', 'Audit PASS', 'Audit FAIL', 'Not provable yet'])
  eq(s.map(x => x.value), [68, 43, 20, 436, 25, 37, 16])
  eq(catalogStats(null).every(x => x.value === null), true)
  eq(s.every(x => x.tip.length > 20), true, 'every stat has a tooltip')
  eq(s[4].tip.includes('out of 78 audited'), true)
})
t('every lane chip has tooltip text', () => {
  for (const mode of MODES) {
    for (const verdict of ['PASS', 'FAIL_RUN', 'UNVERIFIABLE', null, 'ODD']) {
      for (const c of laneChips(lane('x', { mode, verdict }))) if (!c.tip.trim()) fail(`empty ${c.kind} tip for ${mode}/${verdict}`)
    }
  }
})
t('categories keep the server order and skip unknown ids', () => {
  const w = { lanes: { a: lane('a'), b: lane('b', { mode: 'dry' }) } }
  eq(categoryLanes(w, { key: 'ops', label: 'Ops', modes: { live: 1, both: 0, dry: 1, none: 0 }, lanes: ['b', 'ghost', 'a'] }).map(l => l.lane_id), ['b', 'a'])
})
t('schedule, lane link and relay flag', () => {
  eq(scheduleText({ schedule: ['0 7 * * 1-5', '30 16 * * 1-5'] }), '0 7 * * 1-5 · 30 16 * * 1-5')
  eq(scheduleText({ schedule: [] }), 'event / no schedule')
  eq(laneHref('synthetic lane'), '/ops/jobs-n8n?tab=n8n&lane=synthetic%20lane')
  eq([notInRelay({ mode: 'live', in_relay: false }), notInRelay({ mode: 'both', in_relay: true }), notInRelay({ mode: 'dry', in_relay: false })], [true, false, false])
})

console.log(`n8nCatalog: ${n} passed`)
