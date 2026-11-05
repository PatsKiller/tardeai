// node --experimental-strip-types src/lib/moneyFreshness.test.mjs
// FQ-087 (HQ-03): a money/position value must not render as fresh after a failed or retained transport,
// however recent its data clock. The qualifier is the thing that carries that truth beside the number.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { moneyQualifier, transportQualifier, ageQualifier } from './observationEnvelope.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

for (const t of ['ERROR', 'RETAINED', 'FALLBACK', 'PARTIAL', 'UNKNOWN']) {
  check(transportQualifier(t) !== null, `${t} transport has no qualifier — the value reads as fresh`)
  check(moneyQualifier(t, 0.1) !== null, `${t} with a recent data clock renders as fresh`)
}
check(transportQualifier('OK') === null, 'a clean transport with fresh data is being flagged')
check(moneyQualifier('OK', 0.5) === null, 'fresh data on a clean transport is being flagged')
check(/stale/.test(moneyQualifier('OK', 30) || ''), 'aged data on a clean transport does not say stale')
check(/stale/.test(ageQualifier(72, 24) || ''), 'ageQualifier does not report a 3-day-old value')
check(/unknown|unavailable/i.test(ageQualifier(null, 24) || ''), 'an undatable value must say its time is unavailable')
for (const age of [NaN, Infinity, -1]) check(!!ageQualifier(age, 24), 'an unusable clock must not read fresh')
for (const state of ['STALE', 'UNKNOWN']) check(!!moneyQualifier('OK', 0.1, 24, state), 'source refusal cannot be hidden by a recent clock')

const home = readFileSync(join(HERE, '../pages/HomeHub.tsx'), 'utf8')
check(/holdingsMoneyQualifier\(overview,/.test(home), 'HomeHub does not qualify its money value with the holdings contract + transport + age')
check(/observationAgeHours\(/.test(home), 'HomeHub does not use the data clock for the qualifier')
check(/moneyNote/.test(home), 'HomeHub computes no money note to render')

if (failed) { console.error(`moneyFreshness: ${failed} failure(s)`); process.exit(1) }
console.log('moneyFreshness: ok')
