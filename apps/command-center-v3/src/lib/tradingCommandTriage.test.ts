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

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
