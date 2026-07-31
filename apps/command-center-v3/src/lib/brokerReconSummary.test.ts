//   node apps/command-center-v3/src/lib/brokerReconSummary.test.ts
import { summarizeReconByBroker } from './brokerReconSummary.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('brokerReconSummary')

{
  const rows = summarizeReconByBroker(
    [
      { broker: 'tradeai_automated', run_status: 'completed', unmatched_broker_orders: 0, unmatched_local_trades: 0 },
      { broker: 'schwab', run_status: 'completed', unmatched_broker_orders: 2, unmatched_local_trades: 1 },
    ],
    [{ broker: 'schwab', symbol: 'DXCM' }],
  )
  check('two venues', rows.length === 2)
  check('break first', rows[0].broker === 'schwab' && rows[0].status === 'break')
  check('ok second', rows[1].status === 'ok')
  check('next action mentions match', /match|unmatched/i.test(rows[0].next_action))
}

{
  const rows = summarizeReconByBroker([], [])
  check('empty → unknown none', rows[0].broker === 'none')
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
