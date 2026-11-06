const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  ok(value: unknown, message = 'expected truthy value') { if (!value) throw new Error(message) },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import { ageText, ciLabel, ciTone, coachFacts, kpiDisplay, lastRunText, prList, promoteFacts, sectionView, SECTION_KEYS, stopFacts, verifyLabel, verifyVerdict, type Kpi, type ReleasesSchedulesWire, type TimelineRow } from './releasesSchedules.ts'

const NOW = Date.parse('2026-10-22T19:00:00Z')
const wire: ReleasesSchedulesWire = {
  schema: 'ReleasesSchedules@v1', generated_at: '2026-10-22T19:00:00Z', status: 'DEGRADED',
  serving: { value: { sha: 'b'.repeat(40), short_sha: 'bbbbbbbbb', release_name: 'r', since: null, since_basis: null, pins_agree: true, pins: {}, deploy_receipt: null },
    as_of: '2026-10-22T18:58:00Z', freshness: 'OK', source: 'CURRENT', reason: null },
  history: { value: null, as_of: null, freshness: 'UNAVAILABLE', source: 'release_pins', reason: 'git_failed' },
  n8n_today: { value: { day: '2026-10-22', total: 0, by_mode: {}, by_state: {}, errors_total: 0, skips_total: 0, errors: [], lock_skips: [], busiest: [], dead_letters: { available: false, unreleased: null, recent: null } },
    as_of: '2026-10-22T18:59:00Z', freshness: 'OK', source: 'ledger', reason: null },
}

// OK section: value kept, freshness label carries age and source.
const sv = sectionView(wire, 'serving', { nowMs: NOW })
assert.equal(sv.state, 'OK'); assert.equal(sv.ageS, 120); assert.match(sv.label, /OK · 2m ago · CURRENT/)
// UNAVAILABLE section: null value, reason in the label, never zero.
const q = sectionView(wire, 'history', { nowMs: NOW })
assert.equal(q.state, 'UNAVAILABLE'); assert.equal(q.value, null); assert.match(q.label, /UNAVAILABLE · git_failed/)
// The retired release train's windows / queue sections are gone (2026-10-27).
assert.ok(!(SECTION_KEYS as readonly string[]).includes('windows') && !(SECTION_KEYS as readonly string[]).includes('queue'))
// A real zero from an OK source stays zero (it was measured).
const td = sectionView<{ total: number }>(wire, 'n8n_today', { nowMs: NOW })
assert.equal(td.value?.total, 0)
// Missing section, unknown schema, failed request: UNAVAILABLE.
assert.equal(sectionView(wire, 'timeline', { nowMs: NOW }).state, 'UNAVAILABLE')
assert.equal(sectionView({ ...wire, schema: 'ReleasesSchedules@v9' }, 'serving', { nowMs: NOW }).state, 'UNAVAILABLE')
assert.match(sectionView(null, 'serving', { nowMs: NOW, error: true }).label, /request failed/)
// Old response or failed refresh: STALE, value kept and labelled.
const old = sectionView(wire, 'serving', { nowMs: NOW + 10 * 60_000 })
assert.equal(old.state, 'STALE'); assert.ok(old.value); assert.match(old.reason ?? '', /older than 5 minutes/)
assert.equal(sectionView(wire, 'serving', { nowMs: NOW, error: true }).state, 'STALE')

// KPIs: null is UNAVAILABLE, never 0 / green; a stale response is labelled.
const k = (v: Kpi['value'], f: Kpi['freshness'] = 'OK'): Kpi => ({ key: 'x', label: 'X', value: v, detail: 'd', tone: 'success', freshness: f, as_of: null })
assert.equal(kpiDisplay(k(null), true).value, 'UNAVAILABLE'); assert.equal(kpiDisplay(k(null), true).tone, 'warning')
assert.equal(kpiDisplay(k(5, 'UNAVAILABLE'), true).value, 'UNAVAILABLE')
assert.equal(kpiDisplay(k(2883), true).value, '2,883'); assert.equal(kpiDisplay(k(2883), true).tone, 'success')
assert.equal(kpiDisplay(k(0), true).value, '0')
assert.match(kpiDisplay(k(1), false).detail, /^STALE/); assert.equal(kpiDisplay(undefined, true).value, 'UNAVAILABLE')

assert.equal(ageText(null), 'age unknown'); assert.equal(ageText(30), '30s ago'); assert.equal(ageText(7200), '2h ago')
assert.equal(prList(null, 'git failed'), 'UNAVAILABLE · git failed'); assert.equal(prList([], null), 'no PRs')
assert.equal(prList([1, 2, 3], null, 2), '#1, #2 +1 more')
assert.equal(verifyLabel({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: true, readback_errors: [] }, verify_reason: null, serving: true }).text, 'LIVE · VERIFIED')
assert.equal(verifyLabel({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: false }, verify_reason: null }).tone, 'danger')
assert.equal(verifyLabel({ receipt: 'r', mode: 'rollback', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: null, prs_reason: null, verify: null, verify_reason: null }).text, 'ROLLBACK')

// codex R1 (#2541): the verdict is STRUCTURED. "NOT VERIFIED" ends with "VERIFIED", so any suffix test on the label
// reads a failed verification as a pass — which is exactly what the operator view did.
assert.equal(verifyVerdict({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: false }, verify_reason: null }), 'not_verified')
assert.equal(verifyVerdict({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: true, readback_errors: ['x'] }, verify_reason: null }), 'not_verified')
assert.equal(verifyVerdict({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: true, rolled_back: true }, verify_reason: null }), 'not_verified')
assert.equal(verifyVerdict({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: true, readback_errors: [] }, verify_reason: null, serving: true }), 'verified')
assert.equal(verifyVerdict({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: null, prs_reason: null, verify: null, verify_reason: null }), 'not_recorded')
assert.equal(verifyVerdict({ receipt: 'r', mode: 'rollback', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: null, prs_reason: null, verify: null, verify_reason: null }), 'rollback')
const row = (o: Partial<TimelineRow>): TimelineRow => ({ at: '2026-10-22T20:33:00Z', lane: 'l', lane_id: 'l', runner: 'cron', schedule: '', stage: 'LIVE', n8n_stage: null, fires_in_horizon: 1, cadence_label: null, paused_since: null, paused_note: null, last_run: null, ...o })
assert.match(lastRunText(row({ stage: 'PAUSED', paused_since: '2026-10-14', paused_note: 'schwab' })), /paused since 2026-10-14 · schwab/)
assert.match(lastRunText(row({ runner: 'n8n' })), /no ledger run today/)
console.log('releasesSchedules: OK/STALE/UNAVAILABLE sections, KPI never-zero, PR/verify/stage labels passed')

// Main-HEAD CI: state + age from the main-ci-watch receipt; tone never green unless SUCCESS/OK.
assert.equal(ciLabel({ state: 'PENDING', reason: null, age_s: 720 }), 'PENDING · 12m ago')
assert.equal(ciLabel({ state: 'SUCCESS', reason: null, age_s: 9000, stale: true }), 'SUCCESS · 3h ago (stale)')
assert.equal(ciLabel({ state: 'UNAVAILABLE', reason: 'no receipt' }), 'UNAVAILABLE')
assert.equal(ciTone('FAILURE'), 'danger'); assert.equal(ciTone('PENDING'), 'info'); assert.equal(ciTone('UNAVAILABLE'), 'warning')
assert.equal(ciTone('SUCCESS'), 'success')

// n8n failure is a data gap, not a zero: a capture-fresh response whose source failed stays UNAVAILABLE.
const n8nDown: ReleasesSchedulesWire = {
  ...wire,
  n8n_today: { value: null, as_of: '2026-10-22T18:59:00Z', freshness: 'UNAVAILABLE', source: 'sqlite:n8n_coordination_ledger', reason: 'OperationalError: unable to open database file' },
}
const down = sectionView<{ total: number }>(n8nDown, 'n8n_today', { nowMs: NOW })
assert.equal(down.state, 'UNAVAILABLE')
assert.equal(down.value, null)                                  // never 0
assert.match(down.label, /OperationalError/)                   // the real cause, not a capture age
assert.ok(!/^OK/.test(down.label))                             // the label never claims a fresh OK

// A section's as_of is the SOURCE's own time (last run, last release), not the read time: an OK section whose
// as_of is hours old is NOT downgraded. Staleness comes from the source's freshness or the capture time.
const quiet: ReleasesSchedulesWire = { ...wire, n8n_today: { ...wire.n8n_today!, as_of: '2026-10-22T13:00:00Z' } }
assert.equal(sectionView(quiet, 'n8n_today', { nowMs: NOW }).state, 'OK')

// An undated capture is not current: the response cannot be called OK when generated_at is missing.
assert.equal(sectionView({ ...wire, generated_at: undefined }, 'serving', { nowMs: NOW }).state, 'STALE')

// ── the coach strip states what it knows, and says "unknown" instead of a zero (codex-cloud F2 at 567486a98) ──
const servingNext = { sha: 'a'.repeat(40), short_sha: 'aaaaaaaaa', subject: null, committed_at: null, fetched_at: null,
  is_serving: true, commits_ahead: 0, prs_since_serving: null, prs_reason: null, ci: { state: 'SUCCESS' as const, reason: null } }
const aheadNext = { ...servingNext, is_serving: false, commits_ahead: 3 }
const unstakedNext = { ...servingNext, is_serving: false, commits_ahead: null }

// The two defaults the finding named: a null board must not read "0 READY", a null next must not read "matches main".
const blank = coachFacts({ inFlight: null, next: null, stopEffective: false })
assert.equal(blank.ready, null)                                  // never 0
assert.equal(blank.ahead, null)                                  // never 0
assert.equal(blank.matches, false)                               // no green badge from an absence
assert.match(blank.recommend, /not saying "nothing needs you"/i)
assert.match(blank.unknown ?? '', /open-PR board/)
assert.ok(!/^Nothing needs you/.test(blank.recommend))

// A stated zero is still a zero, and a serving main is still a match — the honest case must keep its sentence.
const known = coachFacts({ inFlight: { ready_count: 0, count: 4 }, next: servingNext, stopEffective: false })
assert.equal(known.ready, 0); assert.equal(known.ahead, 0); assert.equal(known.matches, true)
assert.match(known.recommend, /Nothing needs you right now/)
assert.equal(known.unknown, null)

// An unstaked distance is unknown even when the release object is present.
const unstaked = coachFacts({ inFlight: { ready_count: 0, count: 1 }, next: unstakedNext, stopEffective: false })
assert.equal(unstaked.ahead, null); assert.equal(unstaked.matches, false)
assert.match(unstaked.recommend, /how far main is ahead of the site/i)

// Ready wins over everything, and STOP is stated when it is the reason Job B cannot run.
assert.match(coachFacts({ inFlight: { ready_count: 2, count: 2 }, next: servingNext, stopEffective: false }).recommend, /2 changes ready/)
assert.match(coachFacts({ inFlight: { ready_count: 0, count: 0 }, next: aheadNext, stopEffective: true }).recommend, /Deploy STOP is on/)
assert.match(coachFacts({ inFlight: { ready_count: 0, count: 0 }, next: aheadNext, stopEffective: false }).recommend, /3 commits ahead/)

// ── cx-openai-4 R2/R3 at 8cd7fee69: an unread STOP latch is unknown, and a stale read is not present readiness ──
const unknownStop = coachFacts({ inFlight: { ready_count: 0, count: 0 }, next: aheadNext, stopEffective: null })
assert.equal(unknownStop.stop, null)
assert.match(unknownStop.recommend, /STOP state was not read/i)          // never "off, promote allowed"
assert.match(unknownStop.unknown ?? '', /STOP latch/)

// A stale/retained board may not state a READY count as present readiness.
const staleBoard = coachFacts({ inFlight: { ready_count: 3, count: 3, freshness: 'UNAVAILABLE' }, next: servingNext, stopEffective: false })
assert.equal(staleBoard.ready, null)
assert.match(staleBoard.unknown ?? '', /current open-PR board/i)
assert.ok(!/3 changes ready/.test(staleBoard.recommend))

// A STALE next-release section keeps its value for display but cannot prove alignment or a promote.
const staleNext = coachFacts({ inFlight: { ready_count: 0, count: 0 }, next: servingNext, stopEffective: false, nextFreshness: 'STALE' })
assert.equal(staleNext.ahead, 0)                 // historical value retained
assert.equal(staleNext.aheadCurrent, false)
assert.equal(staleNext.matches, false)           // a stale zero is not "matches"
assert.ok(!/Nothing needs you right now/.test(staleNext.recommend))
assert.match(staleNext.recommend, /comparison is stale/i)

// A stale CI receipt is not current green, even when the state string says SUCCESS.
const staleCi = coachFacts({ inFlight: { ready_count: 0, count: 0 },
  next: { ...aheadNext, ci: { state: 'SUCCESS' as const, reason: null, stale: true, age_s: 86400 } }, stopEffective: false })
assert.equal(staleCi.ciOk, false)
assert.ok(!/promote when you are ready/.test(staleCi.recommend))

// ── Job B promote panel: no green headline from an unread comparison or an unread STOP (cx-openai-4 R1/R2) ──
const promoteUnknown = promoteFacts({ next: null, stopEffective: false })
assert.match(promoteUnknown.headline, /not read/i)
assert.ok(!/look aligned/.test(promoteUnknown.headline))
assert.equal(promoteUnknown.badge, 'unknown')
assert.equal(promoteUnknown.matches, false)

const promoteStale = promoteFacts({ next: servingNext, stopEffective: false, nextFreshness: 'STALE' })
assert.match(promoteStale.headline, /stale/i)
assert.ok(!/look aligned/.test(promoteStale.headline))
assert.equal(promoteStale.promoteReady, false)

const promoteUnknownStop = promoteFacts({ next: aheadNext, stopEffective: null })
assert.ok(!/ready to promote when you choose/.test(promoteUnknownStop.headline))
assert.match(promoteUnknownStop.headline, /STOP state was not read/i)
assert.equal(promoteUnknownStop.promoteReady, false)
assert.equal(promoteUnknownStop.badge, 'STOP not read')

const promoteStaleCi = promoteFacts({ next: { ...aheadNext, ci: { state: 'SUCCESS' as const, reason: null, stale: true } }, stopEffective: false })
assert.equal(promoteStaleCi.ciGreen, false)
assert.equal(promoteStaleCi.promoteReady, false)
assert.ok(!/ready to promote when you choose/.test(promoteStaleCi.headline))

// The positive cases survive: a current zero is aligned, and a current ahead+green+STOP-off is a promote candidate.
const promoteAligned = promoteFacts({ next: servingNext, stopEffective: false })
assert.match(promoteAligned.headline, /look aligned/)
assert.equal(promoteAligned.matches, true)
assert.equal(promoteAligned.badge, 'serving main')
const promoteReady = promoteFacts({ next: aheadNext, stopEffective: false })
assert.match(promoteReady.headline, /ready to promote when you choose/)
assert.equal(promoteReady.promoteReady, true)
assert.equal(promoteReady.badge, 'promote candidate')
const promoteStopped = promoteFacts({ next: aheadNext, stopEffective: true })
assert.match(promoteStopped.headline, /STOP is latched/)
assert.equal(promoteStopped.promoteReady, false)

// ── STOP is tri-state: only a current response that states a boolean can say "off" ──
assert.equal(stopFacts(null, { error: true }).effective, null)
assert.equal(stopFacts(undefined).effective, null)
assert.equal(stopFacts(wire).effective, null)                                   // no stop block: unknown, not off
assert.equal(stopFacts({ ...wire, stop: { state: 'STOP' } }).effective, null)   // state without the boolean
assert.equal(stopFacts({ ...wire, stop: { state: 'CLEAR', effective_stop: false } }).effective, false)
assert.equal(stopFacts({ ...wire, stop: { state: 'STOP', effective_stop: true } }).effective, true)
assert.equal(stopFacts({ ...wire, stop: { state: 'CLEAR', effective_stop: false } }, { stale: true }).effective, null)
assert.equal(stopFacts({ ...wire, stop: { state: 'CLEAR', effective_stop: false } }, { error: true }).effective, null)

