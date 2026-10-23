// Pure tests for tradingCommandTriage.ts
//   node apps/command-center-v3/src/lib/tradingCommandTriage.test.ts
import { buildTradingTriage } from './tradingCommandTriage.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('tradingCommandTriage')

{
  const chips = buildTradingTriage({
    intelSummary: { risk_counts: { near_stop: 2, large_gain_unprotected: 3 }, total_positions: 10 },
    intelPositions: [
      { symbol: 'V', operator_priority: 'critical', protection_state: 'unprotected', operator_decision: 'Needs protection review', risk_flags: ['large_gain_unprotected', 'no_protection'] },
      { symbol: 'SCHD', operator_priority: 'low', protection_state: 'unprotected', risk_flags: ['no_protection'] },
    ],
    queueSummary: { total: 12, route_ready: 2, blocked: 10, agent_pending: 5 },
    recon: { runs: [{ unmatched_broker_orders: 1, unmatched_local_trades: 2 }] },
    pilot: { standing_approvals_active: 3 },
    paperPending: 4,
  })
  const ids = chips.map(c => c.id)
  check('has unprotected priority', ids.includes('unprotected_priority'))
  check('has near stop', ids.includes('near_stop'))
  check('has route ready', ids.includes('route_ready'))
  check('has blocked', ids.includes('queue_blocked'))
  check('has recon', ids.includes('recon_break'))
  check('has standing 2fa', ids.includes('standing_2fa'))
  check('V sample on unprot', Boolean(chips.find(c => c.id === 'unprotected_priority')?.samples?.includes('V')))
  check('route ready count 2', chips.find(c => c.id === 'route_ready')?.count === 2)
  check('recon count 3', chips.find(c => c.id === 'recon_break')?.count === 3)
  check('recon opens the Open Trades reconciliation drawer', chips.find(c => c.id === 'recon_break')?.tab === 'Open Trades' && chips.find(c => c.id === 'recon_break')?.params?.drawer === 'recon')
  // paper pending suppressed when queue has action items
  check('no paper when queue active', !ids.includes('paper_pending'))
}

{
  const chips = buildTradingTriage({
    intelSummary: { risk_counts: {}, total_positions: 5 },
    intelPositions: [],
    queueSummary: { total: 0, route_ready: 0, blocked: 0 },
  })
  check('all clear when quiet', chips.some(c => c.id === 'all_clear'))
}

{
  const chips = buildTradingTriage({})
  check('empty sources → no fake clear', chips.length === 0)
}

// Open Trades audit 2026-10-22: funds, tiny positions and write-offs are never "unprotected"; near-stop
// samples are the positions actually near a stop (flag `stop_near`), never the first rows.
{
  const chips = buildTradingTriage({
    intelSummary: { risk_counts: { near_stop: 1 } },
    intelPositions: [
      { symbol: 'SCHD', operator_priority: 'critical', protection_state: 'unprotected', risk_flags: ['no_protection'] },
      { symbol: 'AMANX', operator_priority: 'high', protection_state: 'unprotected', risk_flags: ['no_protection'], stop_eligible: false, is_unstoppable_fund: true },
      { symbol: 'VSMALL', operator_priority: 'high', protection_state: 'unprotected', risk_flags: ['no_protection'], small_position: true },
      { symbol: 'SRNE', operator_priority: 'high', protection_state: 'unprotected', risk_flags: ['no_protection'], worthless: true },
      { symbol: 'XLB', operator_priority: 'low', protection_state: 'protected', risk_flags: ['stop_near'], protection: { stop_near: true } },
    ],
  })
  const unprot = chips.find(c => c.id === 'unprotected_priority')
  check('unprotected excludes fund / small / write-off', unprot?.count === 1 && unprot?.samples?.join() === 'SCHD')
  check('near-stop samples are the near rows', chips.find(c => c.id === 'near_stop')?.samples?.join() === 'XLB')
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
