// FQ-050: the portfolio price line printed internal price-source keys as "data broker.market quotes:alpaca".
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/pricingStamp.test.ts
import { priceSourceLabel, pricingStampLine } from './pricingStamp.ts'
declare const process: { exit(code?: number): void }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, JSON.stringify(got) === JSON.stringify(want), got)

// Keys captured from /api/v2/portfolio/holdings on 2026-11-04 (live).
eq('data broker quote key', priceSourceLabel('data_broker.market_quotes:alpaca'), 'Alpaca quotes')
eq('second provider', priceSourceLabel('data_broker.market_quotes:yfinance'), 'Yahoo quotes')
eq('cash unit', priceSourceLabel('cash_unit'), 'Cash balances')
eq('technical snapshot', priceSourceLabel('technical_snapshot'), 'Technical snapshot')
eq('known source unchanged', priceSourceLabel('finviz_live'), 'Finviz live')

const line = pricingStampLine({
  last_repriced: '2026-11-04 10:00:03 ET',
  reprice_source: 'finviz_live',
  price_sources: {
    'data_broker.market_quotes:alpaca': 23,
    cash_unit: 5,
    'data_broker.market_quotes:yfinance': 1,
    technical_snapshot: 3,
  },
}, { includeTechnicals: true })
check('no internal key reaches the face', !/data_broker|data broker|market quotes:/.test(String(line)), line)
check('counts survive', /Alpaca quotes \(23\)/.test(String(line)) && /Cash balances \(5\)/.test(String(line)), line)

console.log(`pricingStamp: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
