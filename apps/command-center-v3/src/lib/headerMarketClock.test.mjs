// LQ-20261107-1610: header REGIME/VIX age helpers.
// Run:  node --experimental-strip-types src/lib/headerMarketClock.test.mjs
import { hoursOld, vixStaleAfterHours, regimeAgeNote, NOT_CURRENT_COLOR } from './headerMarketClock.ts'
import { VIX_FRESH_HOURS } from './vixFreshness.ts'

let pass = 0, fail = 0
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name} — got ${JSON.stringify(got)} want ${JSON.stringify(want)}`) }
}

eq('minutes', hoursOld(0.4), '24 min old')
eq('never zero minutes', hoursOld(0.001), '1 min old')
eq('hours keep one decimal', hoursOld(5.66), '5.7 h old')
eq('days past 48 h', hoursOld(50), '2.1 d old')
eq('unknown age is null, not fresh', hoursOld(null), null)
eq('negative age is null', hoursOld(-1), null)
eq('NaN age is null', hoursOld(NaN), null)

eq('server line wins', vixStaleAfterHours(26), 26)
eq('server line as string', vixStaleAfterHours('26'), 26)
eq('absent line falls back to client default', vixStaleAfterHours(undefined), VIX_FRESH_HOURS)
eq('zero line is not "always stale" or "always fresh"', vixStaleAfterHours(0), VIX_FRESH_HOURS)
eq('garbage line falls back', vixStaleAfterHours('x'), VIX_FRESH_HOURS)

// Fail-before: the REGIME tile printed nothing about age while fresh (asOfNote null with quiet provenance off).
eq('fresh regime always carries its age', regimeAgeNote({ stale: false, ageHours: 5.7, asOf: '2026-01-12T09:00:00-05:00' }), '5.7 h old')
eq('fresh regime age plus detail', regimeAgeNote({ stale: false, ageHours: 0.5, asOf: 'x' }, 'uptrend · broad'), '30 min old · uptrend · broad')
eq('stale regime names stale and age', regimeAgeNote({ stale: true, ageHours: 55.2, asOf: 'x' }), 'stale · 2.3 d old')
eq('no clock is admitted', regimeAgeNote({ stale: true, ageHours: null, asOf: null }), 'regime clock not reported')
eq('as_of without age is admitted', regimeAgeNote({ stale: false, ageHours: null, asOf: 'x' }), 'regime age unknown')
eq('not-current colour is the shared grey', NOT_CURRENT_COLOR, 'var(--text3)')

console.log(`\nheaderMarketClock: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
