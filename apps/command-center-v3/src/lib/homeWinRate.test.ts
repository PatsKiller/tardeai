// Pure-logic tests for homeWinRate.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/homeWinRate.test.ts
//
// Proves the mixed-source coalescing (`journal?.win_rate ?? readiness?.win_rate`)
// is gone: paperWinRate and journalWinRate each return exactly one named source
// with its own basis/window/scope/as_of, and neither ever falls back to the other.
import { paperWinRate, journalWinRate } from './homeWinRate.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ── paperWinRate: single source, never the journal ───────────────────────────
{
  const p = paperWinRate({
    win_rate: 0.61, closed_usable: 120, timestamp: '2026-09-02T21:00:00Z',
  })
  check('paper value from readiness.win_rate', p.value === 0.61)
  check('paper trades from readiness.closed_usable', p.trades === 120)
  check('paper names its source', p.source === 'paper-trade-readiness.win_rate')
  check('paper names its basis', p.basis === 'paper_trade_statistics')
  check('paper scope is paper', p.scope === 'paper')
  check('paper window is all_time', p.window === 'all_time')
  check('paper carries its observation time', p.asOf === '2026-09-02T21:00:00Z')

  // Negative control: paper must NEVER borrow the journal. Feed a readiness
  // with NO win_rate and a journal with one — paper still yields null, not the
  // journal's number.
  const emptyReadiness = paperWinRate({ closed_usable: 5 })
  check('paper with no readiness win_rate is null, not a borrowed journal value',
    emptyReadiness.value === null)
  check('paper with no readiness win_rate still names its own source',
    emptyReadiness.source === 'paper-trade-readiness.win_rate')
}

// ── journalWinRate: single source, never the readiness metric ────────────────
{
  const j = journalWinRate({
    win_rate: 0.58, trade_count: 88, basis: 'broker_round_trips',
    account_scope: 'all_live_accounts', time_window: 'last_90_days',
    as_of: '2026-09-02T21:00:00Z',
  })
  check('journal value from overview.journal.win_rate', j.value === 0.58)
  check('journal trades from overview.journal.trade_count', j.trades === 88)
  check('journal names its source', j.source === 'overview.journal.win_rate')
  check('journal carries its basis', j.basis === 'broker_round_trips')
  check('journal carries its account scope', j.scope === 'all_live_accounts')
  check('journal carries its window', j.window === 'last_90_days')
  check('journal carries its observation time', j.asOf === '2026-09-02T21:00:00Z')

  // Negative control: journal must NEVER borrow the readiness metric.
  const emptyJournal = journalWinRate({})
  check('journal with no win_rate is null, not a borrowed readiness value',
    emptyJournal.value === null)
  check('journal with no win_rate still names its own source',
    emptyJournal.source === 'overview.journal.win_rate')
}

// ── the mixed-source negative control ────────────────────────────────────────
// The defect: `journal?.win_rate ?? readiness?.win_rate` under ONE label made the
// numerator and denominator come from different producers. With distinct helpers
// the two sources can no longer alias into one number.
{
  const readiness = { win_rate: 0.61, closed_usable: 120 }
  const journal = { win_rate: 0.58, trade_count: 88 }

  const p = paperWinRate(readiness)
  const j = journalWinRate(journal)

  check('paper and journal are two distinct sources', p.source !== j.source)
  check('paper value is not the journal value', p.value !== j.value)
  check('paper trades are not the journal trades', p.trades !== j.trades)

  // And a caller that mistakenly reads paper's source as journal's number
  // cannot silently succeed: the sources are textually distinct at the point
  // of display, so provenance is traceable per field.
  check('neither helper mentions the other endpoint',
    !p.source.includes('journal') && !j.source.includes('readiness'))
}

console.log(`\nhomeWinRate: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
