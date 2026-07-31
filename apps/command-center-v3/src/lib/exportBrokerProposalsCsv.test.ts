//   node apps/command-center-v3/src/lib/exportBrokerProposalsCsv.test.ts
import { brokerProposalsToCsv } from './exportBrokerProposalsCsv.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('exportBrokerProposalsCsv')

const csv = brokerProposalsToCsv([
  {
    id: 99,
    symbol: 'DXCM',
    account: 'schwab_taxable',
    strategy_id: 'pullback_macd',
    status: 'PENDING',
    shares: 25,
    entry: 70,
    stop: 65,
    target: 85,
    rr_live: 2.1,
    routing_lane: 'live_2fa',
  },
])

check('header', csv.startsWith('id,symbol,'))
check('id', csv.includes('99'))
check('symbol', csv.includes('DXCM'))
check('rr_live', csv.includes('2.1'))
check('lane', csv.includes('live_2fa'))
check('newline', csv.endsWith('\n'))

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
