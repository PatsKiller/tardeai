//   node apps/command-center-v3/src/lib/exportExecutionQualityCsv.test.ts
import { executionQualityToCsv, filterExecutionByDays } from './exportExecutionQualityCsv.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('exportExecutionQualityCsv')

const csv = executionQualityToCsv([{
  id: 1, symbol: 'DXCM', fill_quality: 'GOOD', slippage_pct: 0.05, fill_price: 74,
}])
check('header', csv.startsWith('id,symbol,'))
check('symbol', csv.includes('DXCM'))
check('quality', csv.includes('GOOD'))

const now = new Date().toISOString()
const old = new Date(Date.now() - 40 * 864e5).toISOString()
const rows = [
  { id: 1, created_at: now },
  { id: 2, order_filled_at: old },
]
check('filter 7d keeps recent', filterExecutionByDays(rows, 7).some(r => r.id === 1))
check('filter 7d drops old', !filterExecutionByDays(rows, 7).some(r => r.id === 2))
check('filter all keeps both', filterExecutionByDays(rows, 'all').length === 2)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
