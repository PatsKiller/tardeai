import { alertRows, certifiedOf, closeInstantMs, disarmBody, discoveryGap, etText, findRows, gradeAlerts, gradeDiscover, gradePullback, gradeSectors, gradeSetups, gradeStamp, lastRthTickMs, PULLBACK_API, PULLBACK_MAX_AGE_S, poolRows, poolValidity, pullbackProvenance, pullbackRows, setupsUrl } from './watchSetupsV002.ts'

declare const process: { exit(code?: number): never }
const fail = (m: string): never => { console.error('FAIL: ' + m); process.exit(1) }
const assert = {
  equal: (a: unknown, b: unknown, m?: string) => { if (a !== b) fail(`${m ? m + ': ' : ''}${JSON.stringify(a)} !== ${JSON.stringify(b)}`) },
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
  assert.equal(gradeSectors({ rs_as_of: iso(RTH, 40 * 3600) }, RTH).state, 'STALE')
  assert.equal(gradeSectors({}, RTH).state, 'UNKNOWN')
})
t('OBS-W6-a: a fresh quote does not make a stale momentum read OK (kills the two-clocks trap)', () => {
  // The payload's top as_of is the market-quote envelope, minutes old on a live quote.
  const freshQuote = { as_of: iso(RTH, 60), rs_as_of: iso(RTH, 60 * 3600) }
  assert.equal(gradeSectors(freshQuote, RTH).state, 'STALE')
  assert.equal(gradeSectors(freshQuote, RTH).basis, 'rs_as_of · sector relative strength (20d/60d vs SPY)')
  assert.equal(gradeSectors({ as_of: iso(RTH, 60), rs_as_of: iso(RTH, 600) }, RTH).state, 'OK')
})
t('OBS-W6-a: a date-only rs_as_of is that session close, not UTC midnight', () => {
  // 2026-11-13 close is 16:00 EST = 21:00Z. Parsed as an instant it would be 00:00Z — five hours fresher.
  assert.equal(new Date(closeInstantMs('2026-11-13')).toISOString(), '2026-11-13T21:00:00.000Z')
  // DST is resolved by the zone, not guessed: 16:00 EDT is 20:00Z.
  assert.equal(new Date(closeInstantMs('2026-07-16')).toISOString(), '2026-07-16T20:00:00.000Z')
  assert.ok(Number.isNaN(closeInstantMs('2026-11-13T21:00:00Z')))
  // 34 h after the Friday close is within the 36 h limit; 40 h is not.
  assert.equal(gradeSectors({ rs_as_of: '2026-11-13' }, Date.parse('2026-11-15T07:00:00Z')).state, 'OK')
  assert.equal(gradeSectors({ rs_as_of: '2026-11-13' }, Date.parse('2026-11-15T13:00:00Z')).state, 'STALE')
})
t('OBS-W6-b: validity comes from expires_at, and an unreaped expiry says so', () => {
  const NOW2 = Date.parse('2026-11-14T22:30:00Z')
  assert.equal(poolValidity('2026-11-10T15:00:00Z', NOW2).key, 'expired_unreaped')
  assert.match(poolValidity('2026-11-10T15:00:00Z', NOW2).text, /^expired 4 d ago — still ACTIVE \(no reaper writes this table\)$/)
  assert.equal(poolValidity('2026-11-20T15:00:00Z', NOW2).key, 'active')
  assert.match(poolValidity('2026-11-20T15:00:00Z', NOW2).text, /^within its window — expires in 6 d$/)
  assert.equal(poolValidity(null, NOW2).key, 'no_expiry')
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
  // OBS-W6-a: the sectors inventory mapper moved to lib/watchSectorsV002.ts (see its own test).
  assert.equal(poolRows({ rows: [{ symbol: 'A', current_status: 'ACTIVE' }, {}] })[0].origin, 'screener')
  // OBS-W6-b: expires_at is in the read and was being dropped by the mapper.
  assert.equal(poolRows({ rows: [{ symbol: 'A', expires_at: '2026-11-10T15:00:00Z' }] })[0].expiresAt, '2026-11-10T15:00:00Z')
  assert.equal(poolRows({ rows: [{ symbol: 'A' }] })[0].expiresAt, null)
  assert.equal(findRows({ items: [{ symbol: 'Z', reason: 'r' }] })[0].note, 'r')
})
t('urls and bodies', () => { assert.equal(setupsUrl(25), '/api/v2/watchpool?status=all&offset=25&limit=25'); assert.equal(disarmBody(9).action, 'disarm') })

t('pullback is graded on the last completed SCAN, never on request time', () => {
  const g = (body: unknown) => gradePullback(body, RTH)
  assert.equal(g({}).state, 'UNKNOWN')
  assert.equal(g({ candidates: [] }).state, 'UNKNOWN')       // an empty list with no scan is not "no candidates"
  assert.equal(g({ generated_at: iso(RTH, 3600) }).state, 'OK')
  assert.equal(g({ generated_at: iso(RTH, 3600) }).basis, 'pullback_scan_run')
  assert.equal(g({ generated_at: iso(RTH, 2 * 86400) }).state, 'STALE')
  assert.equal(g({ generated_at: iso(RTH, -600) }).state, 'UNKNOWN') // future stamp
  assert.equal(g({ data: { generated_at: iso(RTH, 60) } }).state, 'OK') // envelope unwrapped
  assert.ok(PULLBACK_MAX_AGE_S >= 24 * 3600, 'a day without a scan must read stale')
})
t('pullbackRows maps the screener payload without inventing values', () => {
  const rows = pullbackRows({ data: { candidates: [
    { symbol: 'tgt', tier: 'trigger', price: '101.5', pullback_pct: 4.2, macd_prox_pct: 0.8, bars_to_cross_est: 2, entry: 101, stop: 97, target1: 112, rr: 2.75,
      score: 84, proposal_live: true, proposal_status: 'PENDING', held: { near_stop: true, reason: 'held' }, held_conflict: true, first_seen_at: '2026-11-13T09:00:00Z', redisplay_reason: 'cooldown' },
    { symbol: 'TWO', proposal_live: false, held: 'held', held_conflict: 'yes' },
    { symbol: 'THREE', proposal_live: null },
    { tier: 'trigger' },
  ] } })
  assert.equal(rows.length, 3, 'a row with no symbol is dropped')
  const [a, b, c] = rows
  assert.equal(a.symbol, 'tgt'); assert.equal(a.entry, 101); assert.equal(a.rr, 2.75); assert.equal(a.barsToCross, 2)
  assert.equal(a.price, 101.5, 'a numeric string is not lost')
  assert.equal(a.held, 'held'); assert.equal(a.heldConflict, true); assert.equal(a.proposalLive, true)
  assert.equal(a.redisplay, 'cooldown'); assert.equal(a.firstSeenAt, '2026-11-13T09:00:00Z')
  assert.equal(b.tier, 'watch', 'a missing tier defaults to watch, never to trigger')
  assert.equal(b.proposalLive, false); assert.equal(b.heldConflict, false, 'only a real true is a conflict')
  assert.equal(c.proposalLive, null, 'an unstated proposal stays null, not false')
  assert.equal(c.whyNot, null); assert.equal(c.entry, null)
  assert.equal(pullbackRows(null).length, 0); assert.equal(pullbackRows({ candidates: {} }).length, 0)
})
t('pullbackProvenance states what the scan covered, and keeps silence null', () => {
  const p = pullbackProvenance({ candidates: [], trigger_count: 2, trigger_live_count: 1, trigger_stale_count: 1, watch_count: 4, held_count: 1,
    dismissed_in_cooldown: 3, scan_provenance: { universe: 'S&P 500 uptrend pullbacks', screened: 498 }, generated_at: '2026-11-13T14:30:00Z',
    hit_stats: { window_days: 90, triggers: 12, target1_first: 5, evaluated: 9, median_days: 6 } })
  assert.equal(p.triggers, 2); assert.equal(p.triggersLive, 1); assert.equal(p.triggersStale, 1); assert.equal(p.watch, 4)
  assert.equal(p.held, 1); assert.equal(p.dismissed, 3); assert.equal(p.screened, 498); assert.equal(p.universe, 'S&P 500 uptrend pullbacks')
  assert.equal(p.lastRun, '2026-11-13T14:30:00Z')
  assert.ok(p.hit && p.hit.target1First === 5 && p.hit.medianDays === 6)
  const bare = pullbackProvenance({})
  assert.equal(bare.universe, ''); assert.equal(bare.screened, null); assert.equal(bare.hit, null)
  // a count the body did not state stays null: it must never read as 0 on the page
  assert.equal(bare.triggers, null); assert.equal(bare.triggersLive, null); assert.equal(bare.watch, null); assert.equal(bare.held, null)
  const part = pullbackProvenance({ trigger_count: 0, watch_count: 2 })
  assert.equal(part.triggers, 0, 'a stated 0 is a real 0'); assert.equal(part.held, null, 'an unstated held count is not 0')
  const hit = pullbackProvenance({ hit_stats: { triggers: 4 } })
  assert.ok(hit.hit && hit.hit.triggers === 4 && hit.hit.target1First === null && hit.hit.windowDays === null)
  assert.equal(pullbackProvenance(null).screened, null)
  assert.equal(PULLBACK_API, '/api/v2/pullback-macd/candidates')
})

console.log(`${passed} passed, 0 failed`)
