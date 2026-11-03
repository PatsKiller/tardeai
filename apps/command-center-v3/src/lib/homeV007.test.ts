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
    cio: { state: 'measured', value: { stance: 'hold', conviction: 3, store_label: 'canonical', stale: false } },
    market_risk_stance: { state: 'measured', value: { stance: 'elevated' } },
    volume_vs_20d: { state: 'ok', value: { ratio: 1.4, sample_dates: ['2026-10-01'], not_time_adjusted: true } },
  } },
  risk: { score: 61, categories: [{ key: 'tech', label: 'Technology', chip: 'STRESS', state: 'ok', as_of: NOW }], next_evaluation: { state: 'measured', value: { at: '2026-11-03T14:00:00Z', basis: 'declared' } } },
  hedge: { triggers: [{ label: 'Technology', current: 4.8, threshold: 10, met: false }], inverse_funds: [{ symbol: 'SH', day_pct: 0.6, state: 'ok' }] },
  budgets: [{ budget: 'demo', actual: 21000, limit: 15000, unit: 'usd', clears_when: 'below 15000', source_binding: { as_of: NOW, sha256: '0'.repeat(64) }, operator_decision: { state: 'unavailable', remediation: { key: 'pending_review', action: 'pending review' } } }],
  gaps: [{ symbol: 'SPCX', field: 'cio.rationale', reason: 'store does not expose it', remediation: { key: 'ask_owner', action: 'ask owner' } }],
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
eq('budget remediation shown', ok.budgets[0].decisionRemediation, 'pending review (pending_review)')
eq('gap carried', ok.gaps[0].key, 'ask owner (ask_owner)')

const stale = parseHomeV007({ symbols: { X: { quote: { state: 'stale', as_of: '2026-11-02T20:00:00Z', age_seconds: 5400, value: { price: 10 } } } } })
eq('a stale word maps to measured and keeps its value', stale.symbols[0].quote.price, 10)
eq('stale maps to the contract vocabulary', stale.symbols[0].quote.state, 'measured')
eq('age is kept', stale.symbols[0].quote.ageSeconds, 5400)

const future = parseHomeV007({ symbols: { X: { quote: { state: 'ok', as_of: '2099-01-01T00:00:00Z', value: { price: 10 } } } } })
eq('a future clock is unknown', future.symbols[0].quote.state, 'unknown')
check('and says clock skew', (future.symbols[0].quote.reason ?? '').includes('future'))

const mismatch = parseHomeV007({ symbols: { X: { quote: { state: 'ok', session_date: '2026-10-30', expected_session_date: '2026-11-02', value: { price: 10 } } } } })
eq('wrong-session quote is unknown', mismatch.symbols[0].quote.state, 'unknown')
check('and names both sessions', (mismatch.symbols[0].quote.reason ?? '').includes('2026-10-30'))

// The data owner's rule: expected_session_date comes from the canonical calendar even when the reader fails.
const expectedOnly = parseHomeV007({ symbols: { X: { quote: { state: 'measured', expected_session_date: '2026-11-02', value: { price: 10 } } } } })
eq('an expected session with no quote session is not a mismatch', expectedOnly.symbols[0].quote.state, 'measured')
eq('and keeps its price', expectedOnly.symbols[0].quote.price, 10)
const unknownMismatch = parseHomeV007({ symbols: { X: { quote: { state: 'unknown', reason: 'reader failed', session_date: '2026-10-30', expected_session_date: '2026-11-02' } } } })
eq('an unknown quote stays unknown', unknownMismatch.symbols[0].quote.state, 'unknown')
eq('and keeps its own reason rather than the session one', unknownMismatch.symbols[0].quote.reason, 'reader failed')
eq('with no price invented', unknownMismatch.symbols[0].quote.price, null)

const missing = parseHomeV007({ symbols: { X: { quote: { state: 'missing', reason: 'no canonical quote', remediation: 'wait for the reader' } } } })
eq('missing has no price', missing.symbols[0].quote.price, null)
eq('missing keeps the reason', missing.symbols[0].quote.reason, 'no canonical quote')

const na = parseHomeV007({ symbols: { X: { since_exit: { state: 'not_applicable' } } } })
eq('not_applicable is itself', na.symbols[0].sinceExit.state, 'not_applicable')
eq('and is not a gap', na.gaps.length, 0)

// E's budget decision contract: the canonical breach word wins, the two bindings stay distinct, an active
// intentional decision is read back beside a breach that is still true.
const SHA_A = 'a'.repeat(64), SHA_B = 'b'.repeat(64)
const decided = parseHomeV007({ budgets: [{
  budget: 'demo_taxable', actual: 21000, limit: 15000, unit: 'usd', scope_id: 'account:demo',
  breached: true, plain_breach: true,
  source_binding: { as_of: '2026-11-02T20:00:00Z', sha256: SHA_A },
  presentation_binding: { sha256: SHA_B },
  budget_presentation_decision: { active: true, intentional_until: '2026-11-09T05:00:00Z', actor: 'operator',
    receipt: 'rcpt-123456789', history: [{ state: 'previous' }, { state: 'older' }] },
  operator_decision: { state: 'available', subtype: 'market_risk_budget_presentation' },
}] })
const db = decided.budgets[0]
eq('canonical breach is kept', db.breach, true)
eq('scope id is kept', db.scopeId, 'account:demo')
eq('a decision is active', db.decision.active, true)
eq('its expiry is kept', db.decision.intentionalUntil, '2026-11-09T05:00:00Z')
eq('its actor is kept', db.decision.actor, 'operator')
eq('its history is counted', db.decision.history, 2)
eq('the raw and composite bindings stay distinct', db.sourceSha !== db.presentationSha, true)
eq('the raw binding keeps its clock', db.sourceAsOf, '2026-11-02T20:00:00Z')
eq('an available decision is not also described as unavailable', db.operatorDecision, 'available')
const notBreached = parseHomeV007({ budgets: [{ budget: 'b', actual: 10, limit: 100, breached: false }] })
eq('a stated not-breached is believed over the arithmetic', notBreached.budgets[0].breach, false)
const partial = parseHomeV007({ budgets: [], budget_presentation_decisions: { complete: false, items: 3, history: [{}, {}] } })
eq('an incomplete ledger is not silent', partial.decisionHistory.complete, false)
eq('it reports how many decisions it holds', partial.decisionHistory.count, 3)
eq('and how much history it kept', partial.decisionHistory.history, 2)
const complete = parseHomeV007({ budgets: [], budget_presentation_decisions: { complete: true, items: 9 } })
eq('a complete ledger is complete', complete.decisionHistory.complete, true)
eq('a payload without a ledger claims nothing', parseHomeV007({ budgets: [] }).decisionHistory.complete, null)

const noDecision = parseHomeV007({ budgets: [{ budget: 'b', actual: 10, limit: 100 }] })
eq('no decision row means not active', noDecision.budgets[0].decision.active, false)

// Measured against the producer's own shapes at e50b8627: inverse_moves is a {symbol: symbol-context}
// map, and next_evaluation carries a bare ISO timestamp in `value`.
const produced = parseHomeV007({
  symbols: { SH: {
    quote: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'canonical_stored_quote', value: 31.2, session: 'regular', session_date: '2026-11-02', expected_session_date: '2026-11-02' },
    day_change: { state: 'measured', value: { price: 0.18, pct: 0.58 }, reference_session_date: '2026-10-30' },
  } },
  risk: { next_evaluation: { value: '2026-11-03T14:00:00Z', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk_evaluation_schedule', basis: 'registry declaration' } },
  hedge: { inverse_moves: {
    SH: { quote: { state: 'measured', value: 31.2 }, day_change: { state: 'measured', value: { price: 0.18, pct: 0.58 } } },
    PSQ: { quote: { state: 'unknown', reason: 'no quote' }, day_change: { state: 'unknown' } },
  } },
})
eq('a bare quote value is still the price', produced.symbols[0].quote.price, 31.2)
eq('inverse moves read from the producer map', produced.hedge.inverse.length, 2)
eq('and carry their symbol', produced.hedge.inverse[0].symbol, 'SH')
eq('and their day move', produced.hedge.inverse[0].dayPct, 0.58)
eq('an unknown inverse quote stays unknown', produced.hedge.inverse[1].state, 'unknown')
eq('a bare next-evaluation value is the time', produced.risk.nextEvaluation?.at, '2026-11-03T14:00:00Z')
eq('and keeps its declared basis', produced.risk.nextEvaluation?.basis, 'registry declaration')
const arrayInverse = parseHomeV007({ hedge: { inverse_moves: { value: [{ symbol: 'SDS', day_pct: -0.4, state: 'measured' }] } } })
eq('the older array shape still reads', arrayInverse.hedge.inverse[0]?.symbol, 'SDS')

const junk = parseHomeV007({ symbols: 'nope', risk: { categories: 'x' }, budgets: {} })
eq('malformed members do not throw', junk.symbols.length, 0)
eq('malformed budgets are empty', junk.budgets.length, 0)

console.log(`homeV007: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
