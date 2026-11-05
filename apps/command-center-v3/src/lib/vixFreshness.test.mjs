// node --experimental-strip-types src/lib/vixFreshness.test.mjs
import { vixFreshness, VIX_FRESH_HOURS } from './vixFreshness.ts'
let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const NOW = Date.parse('2026-11-04T18:00:00Z')
const ago = (h) => new Date(NOW - h * 3600_000).toISOString()

const fresh = vixFreshness(17.4, 'cboe', ago(2), NOW)
check('a recent dated value is FRESH', fresh.state === 'FRESH' && fresh.current === true, fresh.state)
check('and says its age and source', /17\.4/.test(fresh.label) && /h old/.test(fresh.label) && /cboe/.test(fresh.label), fresh.label)

const stale = vixFreshness(22.1, 'cboe', ago(VIX_FRESH_HOURS + 12), NOW)
check('a value past the limit is STALE', stale.state === 'STALE' && stale.current === false, stale.state)
check('and the label says it is not current', /not current/.test(stale.label), stale.label)
check('the value is still shown, not hidden', stale.value === '22.1', String(stale.value))

const undated = vixFreshness(19.2, 'cboe', null, NOW)
check('a value with no observation time is UNDATED', undated.state === 'UNDATED' && undated.current === false, undated.state)
check('and admits the age is unknown', /age is unknown/.test(undated.label), undated.label)
check('it is never reported as fresh', undated.state !== 'FRESH')

for (const missing of [null, undefined, '', 'n/a', NaN]) {
  const r = vixFreshness(missing, 'cboe', ago(1), NOW)
  check(`no value (${String(missing)}) is UNAVAILABLE and shows no number`, r.state === 'UNAVAILABLE' && r.value === null, r.state)
}
const zero = vixFreshness(0, 'cboe', ago(1), NOW)
check('0 is a real VIX, not a missing one', zero.state === 'FRESH' && zero.value === '0.0', zero.state)

const badTime = vixFreshness(18, 'cboe', 'not-a-time', NOW)
check('an unparseable observation time is UNDATED, not fresh', badTime.state === 'UNDATED', badTime.state)
const future = vixFreshness(18, 'cboe', new Date(NOW + 3600_000).toISOString(), NOW)
const future2 = vixFreshness(18, 'cboe', new Date(NOW + 10 * 3600_000).toISOString(), NOW)
check('a future-dated observation is not FRESH and not coloured current (PR 2654 F1)',
  future2.state === 'UNDATED' && future2.current === false && /future/i.test(future2.label), `${future2.state} ${future2.label}`)
const skew = vixFreshness(18, 'cboe', new Date(NOW + 60_000).toISOString(), NOW)
check('a one-minute clock skew is tolerated as fresh', skew.state === 'FRESH' && skew.current === true, skew.state)

// ── CX1 (codex-cloud at a66cdde53): an unzoned timestamp is an unknown instant, not a local one ──────────────
// This wall clock is exactly 36 h before NOW when read as UTC. Read as local time it is 31 h old in UTC-5 and 45 h
// old in UTC+9, so the old `Date.parse` path could show FRESH on one device and STALE on another near the limit.
const BOUNDARY_UNZONED = '2026-11-03T06:00:00'
const prevTZ = process.env.TZ
const byZone = []
for (const tz of ['UTC', 'America/New_York', 'Asia/Tokyo']) {
  process.env.TZ = tz
  const r = vixFreshness(17.4, 'cboe', BOUNDARY_UNZONED, NOW)
  byZone.push({ tz, state: r.state, age: r.age, label: r.label })
}
if (prevTZ === undefined) delete process.env.TZ
else process.env.TZ = prevTZ
check('an unzoned timestamp is UNDATED, never a locally-interpreted instant',
  byZone.every(r => r.state === 'UNDATED' && r.age === null), JSON.stringify(byZone))
check('its classification is identical in every timezone (UTC, UTC-5, UTC+9)',
  new Set(byZone.map(r => JSON.stringify({ state: r.state, age: r.age, label: r.label }))).size === 1,
  JSON.stringify(byZone))
check('and the label says the timezone is unstated', /no stated timezone/.test(byZone[0].label), byZone[0].label)

for (const unzoned of ['2026-11-04', '2026-11-04T16:00:00', '2026-11-04 16:00:00', '2026-11-04T16:00:00.123456']) {
  const r = vixFreshness(17.4, 'cboe', unzoned, NOW)
  check(`unzoned ${JSON.stringify(unzoned)} is UNDATED and not current`,
    r.state === 'UNDATED' && r.current === false, `${r.state} ${r.label}`)
}
// An explicit zone is honoured, not rejected: Z, +HH:MM, -HHMM, and fractional seconds before the designator.
for (const zoned of ['2026-11-04T16:00:00Z', '2026-11-04T11:00:00-05:00', '2026-11-04T21:00:00+0500', '2026-11-04T16:00:00.100Z']) {
  const r = vixFreshness(17.4, 'cboe', zoned, NOW)
  check(`explicitly zoned ${JSON.stringify(zoned)} keeps a real age`,
    r.state === 'FRESH' && r.age === '2 h old', `${r.state} ${r.age}`)
}
console.log(`vixFreshness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
