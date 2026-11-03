// Descriptive rotation data stays visible while the advisory is withheld.
//   node --experimental-strip-types src/lib/rotationDescriptive.test.ts
import { fmtUsd, rotationDescriptive } from './rotationDescriptive.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (n: string, got: unknown, want: unknown) => check(n, got === want, got)

const withData = {
  generated_at: '2026-11-02T21:52:00Z', portfolio_total: 1234567,
  sector_overweights: [{ theme: 'Materials', pct: 12.4, target: 10, excess_dollars: 21000, top_holdings: ['AAA', 'BBB'] }],
  sector_underweights: [{ theme: 'Staples', pct: 4.1, floor: 6, gap_pct: -1.9 }],
  degraded_holdings: [{ symbol: 'XYZ' }, { symbol: 'ABC' }, 'not-a-row'],
}

const d = rotationDescriptive(withData)
eq('has data', d.hasAny, true)
eq('portfolio total', d.portfolioTotal, '$1,234,567')
eq('as of', d.asOf, '2026-11-02T21:52:00Z')
eq('three blocks', d.blocks.length, 3)
eq('overweight row label', d.blocks[0].rows[0].label, 'Materials')
eq('overweight value shows target', d.blocks[0].rows[0].value, '+12.4% vs +10.0% target')
check('overweight detail carries excess and top holdings', /excess \$21,000/.test(d.blocks[0].rows[0].detail ?? '') && /AAA, BBB/.test(d.blocks[0].rows[0].detail ?? ''))
eq('underweight row', d.blocks[1].rows[0].value, '+4.1% vs +6.0% floor')
eq('underweight gap', d.blocks[1].rows[0].detail, 'gap -1.9%')
check('degraded count ignores non-objects', d.blocks[2].empty === '2 holding(s) flagged', d.blocks[2].empty)
eq('no gaps', d.gaps.length, 0)

const empty = rotationDescriptive({ sector_overweights: [], sector_underweights: [], degraded_holdings: [] })
eq('empty has no rows', empty.hasAny, false)
check('empty says so per block', empty.blocks.every(b => b.rows.length === 0) && empty.blocks[0].empty.includes('No overweight'))
eq('empty total unknown', empty.portfolioTotal, null)

const bad = rotationDescriptive({ sector_overweights: 'nope', sector_underweights: {}, degraded_holdings: 7 })
eq('non-list fields are gaps, not crashes', bad.gaps.length, 3)
eq('and nothing is invented', bad.hasAny, false)

eq('no summary at all', rotationDescriptive(null).gaps[0], 'no rotation summary in the response')
eq('array summary is not a record', rotationDescriptive([]).hasAny, false)
eq('unnamed group is explicit', rotationDescriptive({ sector_overweights: [{ pct: 3 }] }).blocks[0].rows[0].label, 'unnamed group')
eq('unknown share is stated', rotationDescriptive({ sector_overweights: [{ theme: 'X' }] }).blocks[0].rows[0].value, 'share unknown')
eq('null portfolio total is not $0', rotationDescriptive({ portfolio_total: null }).portfolioTotal, null)
eq('fmtUsd rounds', fmtUsd(1234.7), '$1,235')
eq('fmtUsd rejects strings', fmtUsd('1234'), null)

console.log(`rotationDescriptive: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
