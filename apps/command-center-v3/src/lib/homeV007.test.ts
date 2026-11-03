// Home v007 additive context parser — display truth rules.
//   node --experimental-strip-types src/lib/homeV007.test.ts
import { parseHomeV007 } from './homeV007.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(n: string, c: boolean, got?: unknown) { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) } }
const eq = (n: string, got: unknown, want: unknown) => check(n, got === want, got)

const abs = parseHomeV007(undefined)
eq('absent block is not present', abs.present, false)
eq('absent says why', abs.gaps[0].key, 'absent')

const NOW = '2026-11-02T21:00:00Z'
const ok = parseHomeV007({
  symbols: { SPCX: {
    quote: { state: 'ok', as_of: NOW, source: 'market_quotes:alpaca', age_seconds: 30, session: 'regular', session_date: '2026-11-02', expected_session_date: '2026-11-02', basis: 'last trade', value: { price: 49.87 } },
    day_change: { state: 'ok', value: { usd: 0.4, pct: 0.8, reference_close: 49.47, reference_date: '2026-10-30' } },
    since_exit: { state: 'ok', value: { usd: -0.1, pct: -0.3, exit_price: 50, exit_date: '2026-10-30' } },
    cio: { state: 'ok', stance: 'hold', conviction: 3, store_label: 'canonical', stale: false },
    market_risk_stance: { state: 'ok', value: 'elevated' },
    volume_vs_20d: { state: 'ok', value: { ratio: 1.4, sample_dates: ['2026-10-01'], not_time_adjusted: true } },
  } },
  risk: { score: 61, categories: [{ key: 'tech', label: 'Technology', chip: 'STRESS', state: 'ok', as_of: NOW }], next_evaluation: { at: '2026-11-03T14:00:00Z', basis: 'declared' } },
  hedge: { triggers: [{ label: 'Technology', current: 4.8, threshold: 10, met: false }], inverse_funds: [{ symbol: 'SH', day_pct: 0.6, state: 'ok' }] },
  budgets: [{ key: 'b1', label: 'Demo', current: 21000, budget: 15000, unit: 'usd', breach: true, clears_when: 'below 15000', state: 'ok', operator_decision: { state: 'unavailable', remediation: 'pending review' } }],
  gaps: [{ member: 'cio.rationale', key: 'not_exposed', reason: 'store does not expose it', remediation: 'ask owner' }],
})
eq('present', ok.present, true)
eq('quote price', ok.symbols[0].quote.price, 49.87)
eq('quote session kept', ok.symbols[0].quote.session, 'regular')
eq('cio stance kept separate', ok.symbols[0].cio.stance, 'hold')
eq('market stance separate from cio', ok.symbols[0].marketStance.value, 'elevated')
eq('volume ratio', ok.symbols[0].volume.ratio, 1.4)
eq('nine-category passthrough', ok.risk.categories[0].chip, 'STRESS')
eq('next evaluation is declared', ok.risk.nextEvaluation?.basis, 'declared')
eq('budget breach kept', ok.budgets[0].breach, true)
eq('intentional is not a button', ok.budgets[0].operatorDecision, 'unavailable')
eq('budget remediation shown', ok.budgets[0].decisionRemediation, 'pending review')
eq('gap carried', ok.gaps[0].key, 'not_exposed')

const stale = parseHomeV007({ symbols: { X: { quote: { state: 'stale', as_of: '2026-11-02T20:00:00Z', age_seconds: 5400, value: { price: 10 } } } } })
eq('stale keeps its value', stale.symbols[0].quote.price, 10)
eq('stale keeps its state', stale.symbols[0].quote.state, 'stale')
eq('stale keeps its age', stale.symbols[0].quote.ageSeconds, 5400)

const future = parseHomeV007({ symbols: { X: { quote: { state: 'ok', as_of: '2099-01-01T00:00:00Z', value: { price: 10 } } } } })
eq('a future clock is unknown', future.symbols[0].quote.state, 'unknown')
check('and says clock skew', (future.symbols[0].quote.reason ?? '').includes('future'))

const mismatch = parseHomeV007({ symbols: { X: { quote: { state: 'ok', session_date: '2026-10-30', expected_session_date: '2026-11-02', value: { price: 10 } } } } })
eq('wrong-session quote is unknown', mismatch.symbols[0].quote.state, 'unknown')
check('and names both sessions', (mismatch.symbols[0].quote.reason ?? '').includes('2026-10-30'))

const missing = parseHomeV007({ symbols: { X: { quote: { state: 'missing', reason: 'no canonical quote', remediation: 'wait for the reader' } } } })
eq('missing has no price', missing.symbols[0].quote.price, null)
eq('missing keeps the reason', missing.symbols[0].quote.reason, 'no canonical quote')

const na = parseHomeV007({ symbols: { X: { since_exit: { state: 'not_applicable' } } } })
eq('not_applicable is itself', na.symbols[0].sinceExit.state, 'not_applicable')
eq('and is not a gap', na.gaps.length, 0)

const junk = parseHomeV007({ symbols: 'nope', risk: { categories: 'x' }, budgets: {} })
eq('malformed members do not throw', junk.symbols.length, 0)
eq('malformed budgets are empty', junk.budgets.length, 0)

console.log(`homeV007: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
