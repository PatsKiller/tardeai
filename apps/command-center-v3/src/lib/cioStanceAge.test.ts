// FQ-098: a stale CIO stance must be named stale with its evidence date, and never rendered as current advice.
import { cioStanceLine } from './cioStanceAge.ts'
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

if (fail.length) { console.error('FQ-098 FAILED:\n  - ' + fail.join('\n  - ')); process.exit(1) }
console.log('FQ-098 ok: stale stances name their evidence date and say they are not current advice')
