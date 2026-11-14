// LQ-20261107-2993 · completion-matrix W-04 (lead 00:47 ET): the two new Watch v002 Overview sections.
//   - Action/Triggers lists only decision points: TRIGGER-tier pullback candidates and alerts that have FIRED.
//   - Since Last Visit filters the same two sources to events after the anchor; with no recorded visit it is an
//     explicit 24 h fallback that says so, and a pref that could not be read is UNKNOWN — never an empty window.
// No invented content: a row whose timestamp is missing is not claimed as "since".
//   node --experimental-strip-types src/lib/watchOverviewV002.test.ts
import {
  actionRows, actionMeta, lastVisit, sinceRows, stampResult, unreadReads,
  LAST_SEEN_KEY, LAST_SEEN_API, FALLBACK_WINDOW_HOURS, type LastVisit,
} from './watchOverviewV002.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

// Fri 2026-11-13 15:00Z = 10:00 ET.
const NOW = Date.parse('2026-11-13T15:00:00Z')
const iso = (agoS: number) => new Date(NOW - agoS * 1000).toISOString()
const MIN = 60, H = 3600, D = 24 * H

const alerts = (list: unknown[]) => ({ data: { alerts: list } })
const cands = (list: unknown[]) => ({ data: { candidates: list } })
const trig = (o: Record<string, unknown> = {}) => ({ symbol: 'AAA', tier: 'trigger', entry: 101, stop: 97, target1: 112, score: 82, proposal_live: true, ...o })
const fired = (o: Record<string, unknown> = {}) => ({ id: 7, symbol: 'BBB', condition_type: 'rsi_above', threshold: 70, active: true, last_fired_at: iso(H), ...o })

console.log('lastVisit')
{
  const rec = (seen: string) => lastVisit({ data: { key: LAST_SEEN_KEY, read: { status: 'RECORDED', seen_at: seen }, value: { device: 'web' } } }, NOW)
  const v = rec(iso(3 * H))
  check('a recorded visit anchors the window at its stamped seen_at', v.recorded && v.status === 'RECORDED' && v.startMs === NOW - 3 * H * 1000)
  check('the recorded label says since when, in ET', /^since Nov 13, 7:00 AM ET$/.test(v.label))
  check('the recorded visit keeps the seen_at it used', v.seenAt === iso(3 * H))

  const missing = lastVisit({ data: { key: LAST_SEEN_KEY, read: { status: 'NOT_RECORDED' }, value: null } }, NOW)
  check('no record is NOT_RECORDED on the 24 h fallback', !missing.recorded && missing.status === 'NOT_RECORDED' &&
    missing.startMs === NOW - FALLBACK_WINDOW_HOURS * H * 1000)
  check('the fallback says it is a fallback, not a visit', /your last visit is not recorded/.test(missing.label) && missing.seenAt === null)

  // the page hands the model the whole readOnce record, not just its data
  const unread = lastVisit({ state: 'UNKNOWN', data: null, error: 'HTTP 503', at: null, source: LAST_SEEN_API }, NOW)
  check('a failed read is UNKNOWN, not "nothing happened"', !unread.recorded && unread.status === 'UNKNOWN' &&
    /could not be read/.test(unread.label))
  const loading = lastVisit({ state: 'LOADING', data: undefined, error: null, at: null, source: LAST_SEEN_API }, NOW)
  check('a read still in flight says it is still reading, not "not recorded"', !loading.recorded &&
    loading.status === 'NOT_RECORDED' && /still reading your last visit/.test(loading.label))
  const okRead = lastVisit({ state: 'OK', data: { key: LAST_SEEN_KEY, read: { status: 'RECORDED', seen_at: iso(600) } }, error: null, at: iso(1), source: LAST_SEEN_API }, NOW)
  check('an OK readOnce record is read through its data', okRead.recorded && okRead.startMs === NOW - 600_000)

  const future = rec(iso(-2 * H))
  check('a future stamp is a clock fault: fallback, not a negative window', !future.recorded && future.status === 'NOT_RECORDED')
  // small skew is tolerated (the server stamps, the client clock may lead by seconds)
  check('a stamp a few seconds ahead is still a visit', rec(iso(-60)).recorded)

  const junk = rec('not-a-date')
  check('an unparseable seen_at degrades to the fallback', !junk.recorded && junk.startMs === NOW - FALLBACK_WINDOW_HOURS * H * 1000)

  // before the backend registers watch.last_seen in LAST_SEEN_KEYS there is no read block; the stored value is still an anchor
  const raw = lastVisit({ data: { value: { seen_at: iso(2 * H) } } }, NOW)
  check('a stored value.seen_at is honoured without a read block', raw.recorded && raw.startMs === NOW - 2 * H * 1000)
  const none = lastVisit(undefined, NOW) as LastVisit
  check('an absent pref never throws and never reads as a visit', none.recorded === false && none.startMs === NOW - D * 1000)
}

console.log('actionRows')
{
  const rows = actionRows(
    alerts([fired(), fired({ id: 8, symbol: 'CCC', active: false }), fired({ id: 9, symbol: 'DDD', last_fired_at: null })]),
    cands([trig(), { symbol: 'EEE', tier: 'watch', score: 50 }, { tier: 'trigger' }]),
  )
  check('only TRIGGER-tier candidates become actions', rows.filter(r => r.kind === 'trigger').map(r => r.symbol).join() === 'AAA')
  check('only FIRED, armed alerts become actions', rows.filter(r => r.kind === 'alert').map(r => r.symbol).join() === 'BBB')
  check('a symbol-less row is dropped, not rendered blank', rows.every(r => r.symbol.length > 0))
  const a = rows.find(r => r.symbol === 'AAA')!
  check('the trigger row carries entry/stop/target and its live-proposal state',
    /entry 101 · stop 97 · target 112/.test(a.detail) && /proposal in queue/.test(a.detail))
  check('the trigger row names the score', /trigger · score 82/.test(a.text))
  check('the trigger row links to the symbol page', a.href === '/watch/intelligence/AAA')
  const bb = rows.find(r => r.symbol === 'BBB')!
  check('the alert row names the condition, threshold and when it fired',
    /Alert: BBB rsi above 70/.test(bb.text) && /fired Nov 13, 9:00 AM ET/.test(bb.detail))

  const conflict = actionRows(null, cands([trig({ held_conflict: true })]))[0]
  check('a held name near its stop is toned bad and says so', conflict.tone === 'bad' && /HELD, near its stop/.test(conflict.detail))
  const dead = actionRows(null, cands([trig({ proposal_live: false })]))[0]
  check('a dead proposal is disclosed, not counted as queued', /its proposal is dead/.test(dead.detail) && !/in queue/.test(dead.detail))
  const none = actionRows(null, cands([trig({ proposal_live: null })]))[0]
  check('no proposal is stated as no proposal', /no proposal/.test(none.detail))
  check('unreadable bodies produce no invented action', actionRows(null, null).length === 0 && actionRows({}, {}).length === 0)
}

console.log('sinceRows')
{
  const start = NOW - 2 * H * 1000
  const al = alerts([fired({ last_fired_at: iso(3 * H) }), fired({ id: 8, symbol: 'NEW', last_fired_at: iso(30 * MIN) }), fired({ id: 9, symbol: 'NOTS', last_fired_at: null })])
  const ca = cands([
    { symbol: 'OLD', tier: 'trigger', first_seen_at: iso(5 * H) },
    { symbol: 'MID', tier: 'watch', first_seen_at: iso(1 * H) },
    { symbol: 'NEWEST', tier: 'trigger', first_seen_at: iso(10 * MIN) },
    { symbol: 'UNDATED', tier: 'watch' },
  ])
  const rows = sinceRows(al, ca, start)
  check('only events after the anchor are listed', rows.map(r => r.symbol).sort().join() === 'MID,NEW,NEWEST')
  check('an event exactly at the anchor counts (>= start)', sinceRows(null, cands([{ symbol: 'EQ', first_seen_at: new Date(start).toISOString() }]), start).length === 1)
  check('an undated event is not claimed as "since"', !rows.some(r => r.symbol === 'UNDATED'))
  check('newest first', rows.map(r => r.symbol).join() === 'NEWEST,NEW,MID')
  check('a trigger row says it entered the screen and with which tier', /NEWEST entered the Pullback\/MACD screen \(trigger\)/.test(rows[0].text))
  check('an alert row says what fired', /NEW alert fired: rsi above 70/.test(rows.find(r => r.symbol === 'NEW')!.text))
  check('each row carries an ET time', rows.every(r => /^\w{3} \d{1,2}, \d{1,2}:\d{2} (AM|PM) ET$/.test(r.atText ?? '')))
  check('the cap is a cap, newest kept', sinceRows(al, ca, start, 1).length === 1 && sinceRows(al, ca, start, 1)[0].symbol === 'NEWEST')
  check('ids are unique across the two sources', new Set(rows.map(r => r.id)).size === rows.length)
  check('nothing since an anchor after every event', sinceRows(al, ca, NOW).length === 0)
}

console.log('unreadReads')
{
  check('every source that did not answer OK is named', unreadReads([
    { name: 'alert list', state: 'OK' }, { name: 'pullback candidates', state: 'UNKNOWN' }, { name: 'prefs', state: 'TIMED OUT' },
  ]).join() === 'pullback candidates,prefs')
  check('all OK = nothing unread', unreadReads([{ name: 'a', state: 'OK' }]).length === 0)
  check('an empty source list is not an unread list', unreadReads([]).length === 0)
}

// W-04 review C1: HTTP 200 is not a visit stamp. The unregistered-key branch answers {ok, key} with no value; only the
// registered branch writes the server-owned seen_at. Classifying the body keeps the line drawn either way.
console.log('stampResult')
{
  check('200 {ok,key} with no value = not stamped', stampResult({ ok: true, key: 'watch.last_seen' }) === 'the server did not stamp a visit')
  check('200 {ok,key,value:{device}} with no seen_at = not stamped', stampResult({ ok: true, key: 'watch.last_seen', value: { device: 'phone' } }) === 'the server did not stamp a visit')
  check('a stamped body (value.seen_at) = recorded', stampResult({ ok: true, key: 'watch.last_seen', value: { device: 'phone', seen_at: iso(0) } }) === null)
  check('an empty seen_at is not a stamp', stampResult({ ok: true, key: 'watch.last_seen', value: { seen_at: '' } }) === 'the server did not stamp a visit')
  check('ok:false carries the server reason', stampResult({ ok: false, error: 'last visit not recorded (StoreError)' }) === 'last visit not recorded (StoreError)')
  check('ok:false without a reason still refuses', stampResult({ ok: false }) === 'the server refused the visit')
  check('an unparseable body is not a stamp', stampResult(null) === 'the server did not confirm the visit')
  check('an array body is not a stamp', stampResult([]) === 'the server did not confirm the visit')
}

// W-04 review C2: the Action/Triggers headline never states a total while a source is unread.
console.log('actionMeta')
{
  check('a complete read states the count', actionMeta(7, 0, false) === '7 to look at')
  check('zero rows over complete reads says 0', actionMeta(0, 0, false) === '0 to look at')
  check('an unread source suppresses the count', actionMeta(0, 1, false) === 'incomplete — a source could not be read')
  check('an unread source suppresses a non-zero count too', actionMeta(7, 2, false) === 'incomplete — a source could not be read')
  check('loading is still loading', actionMeta(0, 0, true) === 'reading…')
}

console.log('constants')
check('the last-seen key matches the server pref key', LAST_SEEN_KEY === 'watch.last_seen')
check('the GET asks for exactly that key', LAST_SEEN_API === `/api/v2/ui/prefs/get?key=${encodeURIComponent(LAST_SEEN_KEY)}`)
check('the fallback window is the documented 24 h', FALLBACK_WINDOW_HOURS === 24)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
