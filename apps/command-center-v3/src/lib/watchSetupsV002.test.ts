import { alertRows, certifiedOf, disarmBody, discoveryGap, etText, findRows, gradeAlerts, gradeDiscover, gradeSectors, gradeSetups, gradeStamp, lastRthTickMs, poolRows, sectorRows, setupsUrl } from './watchSetupsV002.ts'

declare const process: { exit(code?: number): never }
const fail = (m: string): never => { console.error('FAIL: ' + m); process.exit(1) }
const assert = {
  equal: (a: unknown, b: unknown) => { if (a !== b) fail(`${JSON.stringify(a)} !== ${JSON.stringify(b)}`) },
  ok: (v: unknown, m?: string) => { if (!v) fail(m || 'not ok') },
  match: (s: string, re: RegExp) => { if (!re.test(s)) fail(`${JSON.stringify(s)} !~ ${re}`) },
}
let passed = 0
const t = (name: string, fn: () => void) => { fn(); passed += 1; void name }
// Fri 2026-11-13 15:00Z = 10:00 ET (RTH). Sat 2026-11-14 15:00Z = Saturday.
const RTH = Date.parse('2026-11-13T15:00:00Z')
const SAT = Date.parse('2026-11-14T15:00:00Z')
const iso = (base: number, agoS: number) => new Date(base - agoS * 1000).toISOString()

t('no timestamp is UNKNOWN, never green', () => { for (const v of [undefined, null, '', 'x', 7]) assert.equal(gradeStamp(v, 'b', RTH, 900).state, 'UNKNOWN') })
t('future stamp is UNKNOWN', () => { assert.equal(gradeStamp(iso(RTH, -3600), 'b', RTH, 900).state, 'UNKNOWN') })
t('old stamp is STALE with age', () => { const g = gradeStamp(iso(RTH, 7200), 'b', RTH, 900); assert.equal(g.state, 'STALE'); assert.match(g.label, /2 h old/) })
const evOk = (agoS: number, base = RTH, extra: Record<string, unknown> = {}) => ({ evaluator: { readable: true, last_run_at: iso(base, agoS), last_ok_at: iso(base, agoS), last_rc: 0, ...extra } })
t('RTH alerts: last OK run 10 min ago is OK', () => { assert.equal(gradeAlerts(evOk(600), RTH).state, 'OK') })
t('RTH alerts: last OK run 50 min ago is STALE (limit 2400 s)', () => { assert.equal(gradeAlerts(evOk(3000), RTH).state, 'STALE') })
t('alerts graded on the evaluator, not on a fresh alert row or the legacy liveness_at', () => {
  const g = gradeAlerts({ as_of: iso(RTH, 10), liveness_at: iso(RTH, 10), ...evOk(6 * 3600) }, RTH)
  assert.equal(g.state, 'STALE')
})
t('R1: a crashing evaluator (recent run, rc 1) is STALE with the failure named, never OK', () => {
  const g = gradeAlerts({ evaluator: { readable: true, last_run_at: iso(RTH, 300), last_ok_at: iso(RTH, 3 * 86400), last_rc: 1, last_error: 'db down' } }, RTH)
  assert.equal(g.state, 'STALE'); assert.match(g.label, /last OK 3 d ago/); assert.match(g.reason || '', /failed \(rc 1: db down\)/)
})
t('R1: a recent failed run right after an OK run is still STALE', () => {
  assert.equal(gradeAlerts(evOk(300, RTH, { last_run_at: iso(RTH, 60), last_rc: 2 }), RTH).state, 'STALE')
})
t('R1: runs but no OK run on record is UNKNOWN with the reason', () => {
  const g = gradeAlerts({ evaluator: { readable: true, last_run_at: iso(RTH, 60), last_ok_at: null, last_rc: 1, last_error: 'x' } }, RTH)
  assert.equal(g.state, 'UNKNOWN'); assert.match(g.reason || '', /no successful run on record/)
})
t('alerts with no evaluator record, or an unreadable one, are UNKNOWN', () => {
  assert.equal(gradeAlerts({ as_of: iso(RTH, 10), liveness_at: iso(RTH, 10) }, RTH).state, 'UNKNOWN')
  assert.equal(gradeAlerts({ evaluator: { readable: true, last_ok_at: null } }, RTH).state, 'UNKNOWN')
  assert.equal(gradeAlerts({ evaluator: { readable: false, last_ok_at: iso(RTH, 5) } }, RTH).state, 'UNKNOWN')
})
t('weekend: a Friday-close OK run is still OK (expected tick is Fri 16:40 ET)', () => {
  const fri1640ET = Date.parse('2026-11-13T21:40:00Z')
  assert.equal(gradeAlerts({ evaluator: { readable: true, last_ok_at: new Date(fri1640ET).toISOString(), last_rc: 0 } }, SAT).state, 'OK')
  assert.equal(gradeAlerts(evOk(3 * 86400, SAT), SAT).state, 'STALE')
})
t('lastRthTickMs lands on a weekday tick', () => {
  const tick = lastRthTickMs(SAT)
  assert.ok(tick !== null && new Date(tick).toISOString() === '2026-11-13T21:40:00.000Z', String(tick && new Date(tick).toISOString()))
})
t('setups/sectors grade their own basis; unavailable is UNKNOWN', () => {
  assert.equal(gradeSetups({ as_of: iso(RTH, 600), as_of_basis: 'strategy_watchpool.entered_at' }, RTH).state, 'OK')
  assert.equal(gradeSetups({ status: 'unavailable', as_of: iso(RTH, 1) }, RTH).state, 'UNKNOWN')
  assert.equal(gradeSectors({ as_of: iso(RTH, 40 * 3600) }, RTH).state, 'STALE')
  assert.equal(gradeSectors({}, RTH).state, 'UNKNOWN')
})
t('R3: discover grades the pins clock, never the dead feed (kills F5)', () => {
  const dead = { feeds: { watch_candidate_events: { as_of: iso(RTH, 60), stale: false } }, as_of: iso(RTH, 60) }
  assert.equal(gradeDiscover(dead, RTH).state, 'UNKNOWN') // a fresh-looking feed stamp alone must not grade the tab
  const g = gradeDiscover({ pins_as_of: iso(RTH, 3600), pins_as_of_basis: 'screener_find_pins.auto_research_at', as_of: '2026-07-16T17:00:00Z' }, RTH)
  assert.equal(g.state, 'OK'); assert.equal(g.basis, 'screener_find_pins.auto_research_at')
  assert.equal(gradeDiscover({ pins_as_of: iso(RTH, 5 * 86400) }, RTH).state, 'STALE')
  assert.equal(gradeDiscover({ pins_as_of: null }, RTH).state, 'UNKNOWN')
})
t('R3: the dead discovery feed is a labelled gap with its real last event (ET), and honours stale', () => {
  const gap = discoveryGap({ feeds: { watch_candidate_events: { as_of: '2026-07-16T17:00:00Z', stale: true, gap: { kind: 'no_producer', last_as_of: '2026-07-16T17:00:00Z' } } } })
  assert.match(gap || '', /no producer; last event Jul 16, 1:00 PM ET/)
  assert.match(discoveryGap({ stale: true, as_of: '2026-07-16T17:00:00Z' }) || '', /stale/)
  assert.match(discoveryGap({ gap: { kind: 'no_coverage' } }) || '', /no coverage/)
  assert.equal(discoveryGap({ feeds: { watch_candidate_events: { as_of: iso(RTH, 60), stale: false } } }), null)
})
t('R5: sectors "empty" status is UNKNOWN too', () => { assert.equal(gradeSectors({ status: 'empty', as_of: iso(RTH, 1) }, RTH).state, 'UNKNOWN') })
t('etText is US Eastern, minute precision; junk is null', () => {
  assert.equal(etText('2026-11-12T18:20:00Z'), 'Nov 12, 1:20 PM ET')
  assert.equal(etText('2026-07-16T17:00:00Z'), 'Jul 16, 1:00 PM ET')
  assert.equal(etText(null), null); assert.equal(etText('x'), null)
})
t('R2/F6: certified count — missing, unreadable, unknown armed, real zero; age shown; never a digit by default', () => {
  const none = certifiedOf({ evaluator: { readable: true, certified: null } })
  assert.match(none.text, /No certified count/); assert.ok(!/\d/.test(none.text), 'no digit count when there is none')
  assert.match(certifiedOf({ evaluator: { readable: false } }).text, /unreadable/)
  const unk = certifiedOf({ active_count: 3, evaluator: { certified: { armed: null, runs_24h: 20, ok_runs_24h: 19, fired_24h: 0, as_of: iso(RTH, 600) } } }, RTH)
  assert.match(unk.text, /armed count unknown/); assert.equal(unk.unknown, true); assert.ok(!/armed 0/.test(unk.text))
  const zero = certifiedOf({ active_count: 3, evaluator: { certified: { armed: 0, runs_24h: 1, ok_runs_24h: 1, fired_24h: 0, as_of: iso(RTH, 600) } } }, RTH)
  assert.match(zero.text, /armed 0 · as of 10 min ago/); assert.equal(zero.mismatch, true) // armed 0 vs 3 rows is flagged
  const c = certifiedOf({ active_count: 5, evaluator: { certified: { armed: 4, runs_24h: 20, ok_runs_24h: 18, fired_24h: 1, as_of: iso(RTH, 7200) } } }, RTH)
  assert.equal(c.mismatch, true); assert.match(c.text, /armed 4 · as of 2 h ago · 20 runs \(18 ok\) \/ 24 h · 1 fired/)
  assert.equal(certifiedOf({ active_count: 4, evaluator: { certified: { armed: 4, runs_24h: 1, fired_24h: 0, as_of: iso(RTH, 60) } } }, RTH).mismatch, false)
  assert.match(certifiedOf({ evaluator: { certified: { armed: 4, runs_24h: 1, fired_24h: 0 } } }, RTH).text, /age unknown/)
})
t('row mappers tolerate junk and keep envelope data', () => {
  assert.equal(alertRows({ data: { alerts: [{ id: 3, symbol: 'AXTI', condition_type: 'rsi_below', threshold: 30, active: true }, { nope: 1 }] } }).length, 1)
  assert.equal(alertRows(null).length, 0)
  assert.equal(sectorRows({ sectors: [{ sector: 'Tech', count: 3, sample: ['A'] }, {}] }).length, 1)
  assert.equal(poolRows({ rows: [{ symbol: 'A', current_status: 'ACTIVE' }, {}] })[0].origin, 'screener')
  assert.equal(findRows({ items: [{ symbol: 'Z', reason: 'r' }] })[0].note, 'r')
})
t('urls and bodies', () => { assert.equal(setupsUrl(25), '/api/v2/watchpool?status=all&offset=25&limit=25'); assert.equal(disarmBody(9).action, 'disarm') })
console.log(`${passed} passed, 0 failed`)
