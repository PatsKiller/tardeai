// P3 2026-10-23: date-only as_of values render as dates. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/asOfDisplay.test.ts
import { dateOnlyPart, fmtAsOf, isDateOnly, monthDay } from './asOfDisplay.ts'
import { fmtDeskTimestamp } from './fmtTimestamp.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, got === want, got)

// The captured Schwab source_as_of (rotation/summary 2026-10-23) and its bare form.
eq('UTC-midnight widened date is date-only', dateOnlyPart('2026-10-22T00:00:00+00:00'), '2026-10-22')
eq('Z form is date-only', dateOnlyPart('2026-10-22T00:00:00Z'), '2026-10-22')
eq('zero fraction is date-only', dateOnlyPart('2026-10-22T00:00:00.000000+00:00'), '2026-10-22')
eq('bare date is date-only', dateOnlyPart('2026-10-22'), '2026-10-22')
check('a real stamp is not date-only', !isDateOnly('2026-10-22T20:45:13.673977+00:00'))
check('non-zero fraction at midnight is a real stamp', !isDateOnly('2026-10-22T00:00:00.5+00:00'))
check('midnight in another zone is a real stamp', !isDateOnly('2026-10-22T00:00:00-04:00'))
check('null / number are not date-only', !isDateOnly(null) && !isDateOnly(20261022))

eq('monthDay', monthDay('2026-10-22'), 'Oct 22')
eq('monthDay January', monthDay('2026-01-05'), 'Jan 5')

eq('date-only renders as a date, not 20:00 ET the day before', fmtAsOf('2026-10-22T00:00:00+00:00'), 'Oct 22 (date only)')
eq('bare date renders the same', fmtAsOf('2026-10-22'), 'Oct 22 (date only)')
eq('zoned UTC stamp renders in ET (EDT)', fmtAsOf('2026-10-23T12:09:53.669391+00:00'), 'Oct 23 08:09 ET')
eq('time-only form', fmtAsOf('2026-10-23T02:21:58.964617+00:00', { timeOnly: true }), '22:21 ET')
eq('EST after the November change', fmtAsOf('2026-11-03T15:00:00Z'), 'Nov 3 10:00 ET')
eq('offset stamp renders in ET', fmtAsOf('2026-10-22T18:15:05.932127-04:00'), 'Oct 22 18:15 ET')
eq('unzoned stamp is shown as published, no zone assumed', fmtAsOf('2026-10-23T08:08:08'), '2026-10-23 08:08')
eq('missing → null', fmtAsOf(null), null)
eq('blank → null', fmtAsOf('  '), null)
eq('garbage passes through clipped', fmtAsOf('not a time'), 'not a time')

// The shared desk formatter picks the rule up.
eq('fmtDeskTimestamp date-only', fmtDeskTimestamp('2026-10-22T00:00:00+00:00'), 'Oct 22 (date only)')
eq('fmtDeskTimestamp bare date', fmtDeskTimestamp('2026-10-22'), 'Oct 22 (date only)')
check('fmtDeskTimestamp real stamp still formats as a time', /\d{2}:\d{2}/.test(fmtDeskTimestamp('2026-10-22T20:45:13+00:00') ?? ''))

console.log(`asOfDisplay: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
