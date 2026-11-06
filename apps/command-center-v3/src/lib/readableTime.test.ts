// Site sweep 2026-10-25: raw ISO stamps become ET display text. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/readableTime.test.ts
import { hasRawIsoStamp, readableTime, readableTimesInText } from './readableTime.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, got === want, got)

// The exact stamps the sweep captured.
eq('UTC fraction stamp → ET', readableTime('2026-10-25T13:53:48.866966+00:00'), 'Oct 25 09:53 ET')
eq('offset stamp → ET', readableTime('2026-10-23T09:45:02-04:00'), 'Oct 23 09:45 ET')
eq('UTC midnight is date-only', readableTime('2026-04-19T00:00:00+00:00'), 'Apr 19 (date only)')
eq('timeOnly', readableTime('2026-10-25T11:30:01+00:00', { timeOnly: true }), '07:30 ET')
eq('missing → null', readableTime(null), null)

eq('chip sentence', readableTimesInText('Ledger synced 2026-10-23T22:15:02+00:00 · ledger row write'), 'Ledger synced Oct 23 18:15 ET · ledger row write')
eq('calendar provenance', readableTimesInText('benzinga_rss · 2026-10-01T09:45:11.982480-04:00 · publication'), 'benzinga_rss · Oct 1 09:45 ET · publication')
eq('two stamps in one line', readableTimesInText('observed 2026-10-20T00:00:00-04:00 · collection 2026-10-25T13:52:44.844256+00:00'), 'observed Oct 20 00:00 ET · collection Oct 25 09:52 ET')
eq('bare date untouched', readableTimesInText('session 2026-10-22 closed'), 'session 2026-10-22 closed')
eq('unzoned stamp shown as published without T', readableTimesInText('at 2026-10-22T15:59:21'), 'at 2026-10-22 15:59')
eq('Z stamp', readableTimesInText('at 2026-10-22T19:59:21Z'), 'at Oct 22 15:59 ET')
eq('null → empty', readableTimesInText(null), '')
check('no raw stamp left', !hasRawIsoStamp(readableTimesInText('Holdings synced 2026-10-25T11:30:02.571711+00:00')))
check('detector sees a raw stamp', hasRawIsoStamp('2026-10-25T11:30:02'))

console.log(`readableTime: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
