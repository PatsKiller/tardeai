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
console.log(`vixFreshness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
