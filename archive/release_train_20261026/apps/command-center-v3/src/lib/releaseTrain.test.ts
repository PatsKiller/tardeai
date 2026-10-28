import {
  censusFrom, countLabel, DESIGN_OUTCOMES, fieldFresh, freshness, historyFrom, historyOutcome, newIdempotencyKey,
  NO_STOP_REQUEST, queueFrom, RELEASE_TRAIN_PATHS, riskTone, shortSha, stopModelFrom, stopReasonError, summaryFrom,
  trainDetailFrom, trainDetailPath, TRAIN_ID_RE, STOP_STALE_AFTER_S,
} from './releaseTrain.ts'
import {
  DETAIL, EVENTS, NOW_ISO, QUEUE, QUEUE_NOT_MIGRATED, STOP_ABSENT, STOP_RESULT_OK, STOP_RESULT_REFUSED, STOP_SET, SUMMARY,
  SUMMARY_NOT_MIGRATED,
} from './releaseTrainFixtures.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const now = Date.parse(NOW_ISO)
const tr = (p: any, extra: any = {}) => freshness(p?.generated_at ?? p?.as_of, !!p, { nowMs: now, ...extra })
const T_OK = tr(SUMMARY)
const T_DOWN = freshness(null, false, { nowMs: now, error: 'HTTP 502' })

// paths — RELEASE_TRAIN_API.md §3, §5, §6, §7 and this branch's STOP endpoint
check('summary/queue/events paths', RELEASE_TRAIN_PATHS.summary === '/api/v2/coordination/release-train'
  && RELEASE_TRAIN_PATHS.queue.endsWith('/release-train/queue') && RELEASE_TRAIN_PATHS.events.startsWith('/api/v2/coordination/release-train/events'))
check('stop path is the served STOP endpoint', RELEASE_TRAIN_PATHS.stop === '/api/v2/coordination/release-train/stop')
check('train id pattern (API §6)', TRAIN_ID_RE.test('rt-20261021-1800-a1b2c3') && !TRAIN_ID_RE.test('t1'))
check('train detail path', trainDetailPath('rt-20261021-1800-a1b2c3') === '/api/v2/coordination/release-train/trains/rt-20261021-1800-a1b2c3')

// transport freshness
check('no payload, loading → LOADING', freshness(null, false, { nowMs: now, loading: true }).state === 'LOADING')
check('no payload, error → UNAVAILABLE with reason', T_DOWN.state === 'UNAVAILABLE' && T_DOWN.reason === 'HTTP 502')
check('fresh response → OK', T_OK.state === 'OK')
check('undated response → STALE', freshness(null, true, { nowMs: now }).state === 'STALE')
check('old response → STALE with age', freshness('2026-10-21T19:30:00+00:00', true, { nowMs: now }).ageLabel === '2h ago')
check('kept response after failed refresh → STALE', tr(SUMMARY, { error: 'timeout' }).state === 'STALE')

// Field envelopes (API §2)
check('field OK', fieldFresh(SUMMARY.next_window, T_OK, now).state === 'OK')
check('field UNAVAILABLE keeps reason', fieldFresh(SUMMARY_NOT_MIGRATED.queue_counts, T_OK, now).reason === 'not_migrated')
check('field missing → UNAVAILABLE', fieldFresh(undefined, T_OK, now).state === 'UNAVAILABLE')
check('unknown freshness word → UNAVAILABLE, never OK', fieldFresh({ value: 1, freshness: 'GREEN' }, T_OK, now).state === 'UNAVAILABLE')
check('field STALE is STALE', fieldFresh({ value: 1, freshness: 'STALE', as_of: '2026-10-19T00:00:00Z', reason: null }, T_OK, now).state === 'STALE')
check('OK field over a STALE transport is STALE', fieldFresh(SUMMARY.next_window, tr(SUMMARY, { error: 'x' }), now).state === 'STALE')

// counts never fabricate zero
check('missing count is UNAVAILABLE, not 0', countLabel(undefined, T_OK) === 'UNAVAILABLE' && countLabel(0, T_DOWN) === 'UNAVAILABLE')
check('measured 0 shows 0', countLabel(0, T_OK) === '0')

// summary / Home card
const q = queueFrom(QUEUE, tr(QUEUE), now)
const s = summaryFrom(SUMMARY, T_OK, now, q)
check('ready/held from queue_counts', s.ready.text === '2' && s.held.text === '5')
check('next window: time, role, countdown, not armed', s.nextWindow.text === '18:00 ET canary · in 30m · not armed' && s.nextWindow.tone === 'warning')
check('last outcome keeps its class', s.lastOutcome.text.startsWith('verified · a1b2c3d4e') && s.lastOutcome.tone === 'success')
check('current train derived from queue in-train row', s.currentTrain.text === 'rt-20261021-1800-a1b2c3')
check('policy NOT_CONFIGURED, not armed, warning', s.policy.text === 'NOT_CONFIGURED · not armed' && s.policy.tone === 'warning')
check('stop CLEAR → not stopped', s.stop.text === 'not stopped' && !s.stop.effective)
const nm = summaryFrom(SUMMARY_NOT_MIGRATED, T_OK, now, queueFrom(QUEUE_NOT_MIGRATED, tr(QUEUE_NOT_MIGRATED), now))
check('not migrated: counts UNAVAILABLE with reason, never 0', nm.ready.text === 'UNAVAILABLE (not_migrated)' && nm.held.text === 'UNAVAILABLE (not_migrated)')
check('not migrated: current train UNAVAILABLE', nm.currentTrain.text === 'UNAVAILABLE')
check('not migrated: last outcome UNAVAILABLE', nm.lastOutcome.text === 'UNAVAILABLE')
check('degraded list names the unavailable fields', nm.degraded.some(d => d.startsWith('queue counts UNAVAILABLE')))
const noOutcome = summaryFrom({ ...SUMMARY, last_outcome: { value: null, as_of: SUMMARY.generated_at, freshness: 'OK', reason: 'no_outcome_recorded' } }, T_OK, now, q)
check('no_outcome_recorded is a real empty', noOutcome.lastOutcome.text === 'none recorded')
const down = summaryFrom(null, T_DOWN, now)
check('summary down: every field UNAVAILABLE', [down.nextWindow, down.ready, down.held, down.lastOutcome, down.currentTrain, down.policy].every(i => i.text === 'UNAVAILABLE'))
check('summary down: STOP fails closed (API rule 3)', down.stop.effective && down.stop.text.includes('treat as STOPPED'))
const unreadable = summaryFrom({ ...SUMMARY, stop: { ...SUMMARY.stop!, value: { state: 'UNREADABLE', effective_stop: true } } }, T_OK, now, q)
check('UNREADABLE stop is effective', unreadable.stop.effective && unreadable.stop.text.startsWith('STOPPED (UNREADABLE)'))
const stale = summaryFrom(SUMMARY, tr(SUMMARY, { error: 'timeout' }), now, q)
check('stale summary labels values STALE', stale.ready.text === '2 (STALE)' && stale.nextWindow.text.endsWith('(STALE)'))

// census (API §4)
const c = censusFrom(SUMMARY.census, T_OK, now)
check('census COMPLETE + open = sum → OK', c.state === 'OK' && c.openPrs === 30 && c.bucketSum === 30)
check('zero buckets hidden, largest first', c.buckets[0].name === 'conflicting' && c.buckets.every(b => b.n > 0))
const inc = (v: any) => censusFrom({ ...SUMMARY.census!, value: { ...SUMMARY.census!.value!, ...v } }, T_OK, now)
check('server INCOMPLETE → INCOMPLETE with reasons', inc({ status: 'INCOMPLETE', incomplete_reasons: ['possible_truncation'] }).state === 'INCOMPLETE'
  && /possible_truncation/.test(inc({ status: 'INCOMPLETE', incomplete_reasons: ['possible_truncation'] }).reason || ''))
check('open ≠ sum → INCOMPLETE even if server says COMPLETE', inc({ open_prs: 31 }).state === 'INCOMPLETE')
check('invariant_holds missing → INCOMPLETE', inc({ invariant_holds: undefined }).state === 'INCOMPLETE')
check('null bucket count → INCOMPLETE', inc({ buckets: [{ name: 'held', count: null }], open_prs: 0 }).state === 'INCOMPLETE')
check('census UNAVAILABLE (no receipt)', censusFrom({ value: null, freshness: 'UNAVAILABLE', reason: 'no_receipt' }, T_OK, now).reason === 'no_receipt')
check('census STALE (>36 h, server verdict)', censusFrom({ ...SUMMARY.census!, freshness: 'STALE' }, T_OK, now).state === 'STALE')

// queue (API §5)
check('queue rows', q.usable && q.rows.length === 3 && q.rows[0].pr === 1901)
check('age from age_seconds', q.rows[0].age === '2h')
check('age from submitted_at when age_seconds is null', q.rows[1].age === '4h')
check('undated row says UNDATED', q.rows[2].age === 'UNDATED')
check('held risk is danger; risk reason kept', q.rows[0].riskTone === 'danger' && q.rows[0].riskWhy.includes('always held'))
check('eligible is success; unknown risk never success', riskTone('eligible') === 'success' && q.rows[2].risk === 'unknown' && riskTone('unknown') === 'warning')
check('missing title says UNAVAILABLE', q.rows[2].title === '(title UNAVAILABLE)')
check('dependencies rendered', q.rows[0].dependencies === '#1899' && q.rows[1].dependencies === '—')
check('queue not migrated → not usable, store state kept', !queueFrom(QUEUE_NOT_MIGRATED, tr(QUEUE_NOT_MIGRATED), now).usable
  && queueFrom(QUEUE_NOT_MIGRATED, tr(QUEUE_NOT_MIGRATED), now).storeState === 'NOT_MIGRATED')
check('queue transport down → not usable', !queueFrom(null, T_DOWN, now).usable)

// history (API §6 history_class / §8 outcomes, via §7 events)
const h = historyFrom(EVENTS, tr(EVENTS), now)
check('each design outcome is its own category', DESIGN_OUTCOMES.every(o => h.counts[o] === 1))
check('in-progress train counted apart', h.counts.IN_PROGRESS === 1)
check('PR-subject events are not trains', h.rows.length === 6)
check('newest first', h.rows[0].trainId === 'rt-20261021-1800-a1b2c3')
check('merged queue state is not merged-not-live', historyOutcome('merged') === 'IN_PROGRESS' && historyOutcome('MERGED_NOT_LIVE') === 'MERGED_NOT_LIVE')
check('rollback failed is never rolled back', historyOutcome('ROLLBACK_FAILED') !== historyOutcome('ROLLED_BACK'))
check('history_class words map', historyOutcome('verified') === 'VERIFIED' && historyOutcome('not_shipped') === 'NOT_SHIPPED' && historyOutcome('STOPPED') === 'NOT_SHIPPED')
check('unknown outcome is UNKNOWN', historyOutcome('SOMETHING_NEW') === 'UNKNOWN')
check('members from payload, else UNAVAILABLE', h.rows.find(r => r.trainId === 'rt-20261020-0000-aaaa1')!.members === '3'
  && h.rows.find(r => r.trainId === 'rt-20261021-0600-dddd4')!.members === 'UNAVAILABLE')
check('bad sha is UNAVAILABLE', shortSha('nope') === 'UNAVAILABLE' && shortSha(undefined) === 'UNAVAILABLE')
check('events unavailable → not usable', !historyFrom({ ...EVENTS, events: null, freshness: 'UNAVAILABLE', reason: 'not_migrated' }, tr(EVENTS), now).usable)

// train detail (API §6)
const t = trainDetailFrom(DETAIL.train)!
check('train detail SHAs', t.candidate === 'a1b2c3d4e' && t.main === 'a1b2c3d4e' && t.served === 'a1b2c3d4e' && t.servedMatchesCandidate === true)
check('members in freeze order', t.members[0].pr === 1901 && t.members[1].pr === 1903)
check('timeline ascending', t.timeline[0].step === 'frozen' && t.timeline[1].step === 'promoted')
check('outcome from history_class while in progress', t.outcome === 'OBSERVING')
check('elapsed and checks', t.elapsed === '1h 0m' && t.checks.includes('ci-gate'))
check('served ≠ candidate is flagged', trainDetailFrom({ ...DETAIL.train!, served_sha: 'f'.repeat(40) })!.servedMatchesCandidate === false)
check('served unknown is null, not a match', trainDetailFrom({ ...DETAIL.train!, served_sha: null })!.servedMatchesCandidate === null)
check('missing train → null', trainDetailFrom(null) === null)

// STOP flow
const sf = (st: any, extra: any = {}) => freshness(st?.as_of, !!st, { nowMs: now, staleAfterS: STOP_STALE_AFTER_S, ...extra })
const fAbsent = sf(STOP_ABSENT), fSet = sf(STOP_SET)
const idle = stopModelFrom(STOP_ABSENT, NO_STOP_REQUEST, fAbsent)
check('no request, latch absent → not stopped, no step done', idle.latch === 'ABSENT' && idle.steps.every(x => !x.done) && idle.headline === 'Releases not stopped')
check('resume command is the host CLI', idle.resumeCommand.includes('release_window.py clear-stop'))
const requested = stopModelFrom(STOP_ABSENT, { ...NO_STOP_REQUEST, requestedAt: '2026-10-21T21:30:20Z', inFlight: true }, fAbsent)
check('requested only', requested.steps[0].done && !requested.steps[1].done && !requested.steps[3].done)
const acked = stopModelFrom(STOP_ABSENT, { ...NO_STOP_REQUEST, requestedAt: '2026-10-21T21:30:20Z', result: STOP_RESULT_OK, httpStatus: 200 }, fAbsent)
check('acknowledged needs the server read-back, with its timestamp', acked.steps[1].done && acked.steps[1].at === '2026-10-21T21:30:21Z')
check('acknowledged is not yet stopped without an independent read', !acked.steps[3].done)
const stopped = stopModelFrom(STOP_SET, { ...NO_STOP_REQUEST, requestedAt: '2026-10-21T21:30:20Z', result: STOP_RESULT_OK, httpStatus: 200 }, fSet)
check('stopped after independent read with no window running', stopped.steps[3].done && stopped.steps[3].at === STOP_SET.as_of && stopped.headline === 'RELEASES STOPPED')
check('latch body shown (actor, reason, time)', stopped.latchedBy === 'tailnet:john@jwwhiting.com' && stopped.latchReason === 'bad batch' && stopped.latchedAt === '2026-10-21T21:30:21Z')
const early = stopModelFrom({ ...STOP_SET, as_of: '2026-10-21T21:30:00Z' }, { ...NO_STOP_REQUEST, requestedAt: NOW_ISO, result: STOP_RESULT_OK, httpStatus: 200 }, sf({ ...STOP_SET, as_of: '2026-10-21T21:30:00Z' }))
check('a status read older than the acknowledgement never confirms stopped', !early.steps[3].done)
const settling = stopModelFrom({ ...STOP_SET, window_run_lock: 'HELD' }, NO_STOP_REQUEST, fSet)
check('window mid-run → settling, not stopped', settling.steps[2].done && !settling.steps[3].done && settling.headline.includes('settling'))
const staleSet = stopModelFrom(STOP_SET, NO_STOP_REQUEST, freshness(STOP_SET.as_of, true, { nowMs: now + 3600_000, staleAfterS: STOP_STALE_AFTER_S }))
check('stale latch read never confirms stopped', !staleSet.steps[3].done && staleSet.headline.includes('STALE'))
const noStatus = stopModelFrom(null, NO_STOP_REQUEST, freshness(null, false, { nowMs: now, error: 'HTTP 502' }))
check('status unavailable → treat as STOPPED, never "not stopped"', noStatus.latch === 'UNKNOWN' && noStatus.headline.includes('treat as STOPPED'))
const refused = stopModelFrom(STOP_ABSENT, { ...NO_STOP_REQUEST, requestedAt: NOW_ISO, result: STOP_RESULT_REFUSED, httpStatus: 403 }, fAbsent)
check('refusal shown with its code; not acknowledged', refused.refused === 'CSRF: csrf: Origin not on allowlist' && !refused.steps[1].done)
const lost = stopModelFrom(STOP_ABSENT, { ...NO_STOP_REQUEST, requestedAt: NOW_ISO, error: 'network' }, fAbsent)
check('transport failure is unconfirmed, not success', !!lost.unconfirmed && !lost.steps[1].done)
check('unreadable latch is an effective STOP under a fail-closed runner', stopModelFrom({ ...STOP_ABSENT, runner_reader: 'fail_closed', latch: { status: 'UNREADABLE' } }, NO_STOP_REQUEST, fAbsent).headline.includes('effective STOP'))
check('unreadable latch under main\'s fail-open runner says NOT SET, never "stopped"', /NOT SET: press STOP/.test(stopModelFrom({ ...STOP_ABSENT, latch: { status: 'UNREADABLE' } }, NO_STOP_REQUEST, fAbsent).headline))
check('reason required', stopReasonError('') !== null && stopReasonError('short') !== null && stopReasonError('bad batch in flight') === null)
check('idempotency key matches the server pattern', /^[A-Za-z0-9._:-]{16,128}$/.test(newIdempotencyKey(() => '1b4e28ba-2fa1-11d2-883f-0016d3cca427')))

console.log(`releaseTrain: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
