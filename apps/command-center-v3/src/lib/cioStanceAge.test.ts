// FQ-098: a stale CIO stance must be named stale with its evidence date, and never rendered as current advice.
import { cioStanceLine } from './cioStanceAge.ts'
// `tsconfig` includes src/, so tsc type-checks this file too; the repo's convention (accountLabels.test.ts:8) is to
// declare the host global instead of leaving TS2580 "Cannot find name 'process'" to break the build line.
declare const process: { exit(code?: number): never }

const now = new Date('2026-11-04T12:00:00Z')
const fail: string[] = []
const ok = (c: boolean, m: string) => { if (!c) fail.push(m) }

const staleOne = cioStanceLine('TRIM', '2026-08-29', 62, now)
ok(staleOne.stale, 'the 2026-08-29 stance is not marked stale')
ok(staleOne.text.includes('2026-08-29'), 'the evidence date is not shown')
ok(/stale/i.test(staleOne.text) && /not current advice/i.test(staleOne.text), 'the stale stance is not named stale')

const fresh = cioStanceLine('HOLD', '2026-11-01', 55, now)
ok(!fresh.stale, 'a three-day-old stance was marked stale')
ok(fresh.text.includes('2026-11-01'), 'the fresh stance lost its evidence date')

const undated = cioStanceLine('TRIM', null, 62, now)
ok(undated.stale, 'an undated stance is not treated as unverified')

// cc-deepseek-2 R1 at a3df7ce8e: a date that is PRESENT but unparseable used to render the fresh form with
// "(null days old)" — a stance whose age is unknown presented as current advice. `2026-8-29` is not a fuzz case; an
// unpadded month is what a hand-written memory row produces.
for (const bad of ['2026-8-29', '08/29/2026', 'not-a-date']) {
  const line = cioStanceLine('TRIM', bad, 62, now)
  ok(line.stale, `an unreadable evidence date (${bad}) is not treated as unverified`)
  ok(/unverified/i.test(line.text), `an unreadable evidence date (${bad}) does not say unverified`)
  ok(!/null days old/.test(line.text), `an unreadable evidence date (${bad}) renders "(null days old)"`)
}

// R2: a future date is an impossible age, not a fresh one — it used to print "(-117 days old)".
const fromTheFuture = cioStanceLine('ADD', '2027-03-01', 70, now)
ok(fromTheFuture.stale, 'a future-dated stance is not treated as unverified')
ok(/future/i.test(fromTheFuture.text) && /unverified/i.test(fromTheFuture.text), 'a future-dated stance is not named')
ok(!/-\d+ days old/.test(fromTheFuture.text), 'a future-dated stance renders a negative age')

if (fail.length) { console.error('FQ-098 FAILED:\n  - ' + fail.join('\n  - ')); process.exit(1) }
console.log('FQ-098 ok: stale stances name their evidence date and say they are not current advice')
