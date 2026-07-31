//   node apps/command-center-v3/src/lib/exportOpenTradesCsv.test.ts
import { openTradesToCsv } from './exportOpenTradesCsv.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('exportOpenTradesCsv')

const csv = openTradesToCsv([
  {
    symbol: 'V',
    account: 'schwab_rollover_ira',
    broker: 'schwab',
    shares: 10,
    current_price: 300,
    unrealized_pnl: 100,
    risk_flags: ['no_protection', 'large_gain_unprotected'],
    technical: { rsi: 42.5 },
    sector_relative: { sector: 'Financials' },
    protection_state: 'unprotected',
    operator_priority: 'critical',
    operator_decision: 'Needs protection review',
  },
])

check('has header', csv.startsWith('symbol,account,'))
check('includes V', csv.includes('V'))
check('escapes flags pipe', csv.includes('no_protection|large_gain_unprotected'))
check('rsi from technical', csv.includes('42.5'))
check('sector', csv.includes('Financials'))
check('trailing newline', csv.endsWith('\n'))

const quoted = openTradesToCsv([{ symbol: 'X', operator_decision: 'Needs, review "now"' }])
check('quotes commas', quoted.includes('"Needs, review ""now"""') || quoted.includes('Needs'))

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
