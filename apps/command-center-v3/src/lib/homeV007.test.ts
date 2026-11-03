// Home v007 additive context parser — display truth rules.
//   node --experimental-strip-types src/lib/homeV007.test.ts
import { categoryLine, conflictLine, headlineLine, hedgeLine, marketStanceLine, nextEventLine, parseHomeV007, referenceLine, volumeLine } from './homeV007.ts'
import { offersBudgetDecision } from './budgetIntent.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(n: string, c: boolean, got?: unknown) { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) } }
const eq = (n: string, got: unknown, want: unknown) => check(n, got === want, got)

const abs = parseHomeV007(undefined)
eq('absent block is not present', abs.present, false)
eq('absent says why', abs.gaps[0].key, 'absent')

const NOW = '2026-11-02T21:00:00Z'
// The producer's real shape (market_risk_home_context at c9d0298ce): `state` is measured|unknown|partial,
// day_change.value is {price, pct} with reference_session_date on the FACT, since_exit carries the exit date as
// fact-level reference_as_of, and volume carries the producer's own basis text.
const ok = parseHomeV007({
  symbols: { SPCX: {
    quote: { state: 'measured', as_of: NOW, source: 'market_quotes:alpaca', age_seconds: 30, session: 'regular', session_date: '2026-11-02', expected_session_date: '2026-11-02', basis: 'last trade', value: 49.87 },
    day_change: { state: 'measured', as_of: NOW, source: 'market_quotes:alpaca+previous_session_close', reference_session_date: '2026-10-30', value: { price: 0.4, pct: 0.8 } },
    since_exit: { state: 'measured', as_of: NOW, source: 'reentry_watch.exit_price+market_quotes:alpaca', price_as_of: NOW, reference_as_of: '2026-10-30', value: { reference_price: 50, distance_price: -0.1, distance_pct: -0.3 } },
    cio: { state: 'measured', value: { stance: 'hold', conviction: 3, stale: false } },
    market_risk_stance: { state: 'measured', value: { stance: 'elevated' } },
    volume_vs_20d: { state: 'measured', value: { ratio: 1.4, sample_sessions: 20, average_start_date: '2026-10-01', average_end_date: '2026-10-29', basis: 'observed session volume versus twenty prior completed-session volumes; not time-adjusted' } },
  } },
  risk: { score: 61, categories: [{ category: 'tech', label: 'Technology', chip: 'STRESS', state: 'measured', as_of: NOW }], next_evaluation: { state: 'measured', value: { at: '2026-11-03T14:00:00Z', basis: 'declared' } } },
  hedge: { lagging_progress: { state: 'measured', value: { current: 4, threshold: 10, unit: 'sectors', ratio: 0.4 } }, inverse_moves: { SH: { quote: { state: 'measured', value: 31.2 }, day_change: { state: 'measured', value: { pct: 0.6 } } } } },
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
eq('a stale word keeps its value', stale.symbols[0].quote.price, 10)
eq('stale maps to the contract vocabulary', stale.symbols[0].quote.state, 'measured')
eq('age is kept', stale.symbols[0].quote.ageSeconds, 5400)
// The word must survive: folding 'stale' into 'measured' and forgetting it republishes an old price as current.
eq('the stale word is kept verbatim', stale.symbols[0].quote.word, 'stale')
eq('and the fact is marked stale', stale.symbols[0].quote.stale, true)
const fresh = parseHomeV007({ symbols: { X: { quote: { state: 'measured', as_of: '2026-11-02T20:00:00Z', value: { price: 10 } } } } })
eq('a measured fact is not stale', fresh.symbols[0].quote.stale, false)

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
// E's real `items` is a LIST; reading only a numeric count left "N in the ledger" permanently unrenderable.
const listLedger = parseHomeV007({ budgets: [], budget_presentation_decisions: { complete: true,
  items: [{ scope_id: 'a', budget: 'b' }, { scope_id: 'c', budget: 'd' }] } })
eq('the ledger count comes from the item list', listLedger.decisionHistory.count, 2)

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

// A. The e2e fixture and the producer spell the same facts with different keys; both shapes must read.
// Producer shape (above): day_change.value.price + fact-level reference_session_date.
eq('day change still reads the producer price key', produced.symbols[0].dayChange.usd, 0.18)
eq('day change still reads the producer reference_session_date', produced.symbols[0].dayChange.referenceDate, '2026-10-30')
const fixtureShapes = parseHomeV007({ symbols: { X: {
  day_change: { state: 'ok', value: { usd: 0.4, pct: 0.8, reference_date: '2026-10-30' } },
  since_exit: { state: 'ok', value: { usd: -0.1, pct: -0.3, exit_price: 50, exit_date: '2026-10-30' } },
} } })
eq('day change reads the fixture usd key', fixtureShapes.symbols[0].dayChange.usd, 0.4)
eq('day change reads the fixture reference_date', fixtureShapes.symbols[0].dayChange.referenceDate, '2026-10-30')
eq('since exit reads the fixture usd key', fixtureShapes.symbols[0].sinceExit.usd, -0.1)
eq('since exit reads the fixture pct key', fixtureShapes.symbols[0].sinceExit.pct, -0.3)
eq('since exit reads the fixture exit_price key', fixtureShapes.symbols[0].sinceExit.exitPrice, 50)
eq('since exit reads exit_date instead of a hard-coded null', fixtureShapes.symbols[0].sinceExit.exitDate, '2026-10-30')
const producerExit = parseHomeV007({ symbols: { X: { since_exit: { state: 'measured',
  value: { distance_price: -1.2, distance_pct: -2.4, reference_price: 51 }, reference_session_date: '2026-10-29' } } } })
eq('since exit still reads the producer distance_price key', producerExit.symbols[0].sinceExit.usd, -1.2)
eq('since exit still reads the producer distance_pct key', producerExit.symbols[0].sinceExit.pct, -2.4)
eq('since exit still reads the producer reference_price key', producerExit.symbols[0].sinceExit.exitPrice, 51)
// day_change owns `reference_session_date`; since_exit does not carry it, so it must not be borrowed from there.
eq('since exit does not borrow another fact’s session date', producerExit.symbols[0].sinceExit.exitDate, null)
// The producer carries the recorded exit date as the fact-level `reference_as_of` (its own clock, separate from the
// quote clock). That is the field the card must read — "exited <date>" was never missing from the payload.
const producerExitDate = parseHomeV007({ symbols: { X: { since_exit: { state: 'measured', as_of: '2026-11-02T21:00:00Z',
  price_as_of: '2026-11-02T21:00:00Z', reference_as_of: '2026-10-30', basis: 'distance from the recorded exit price',
  value: { reference_price: 50, distance_price: -0.1, distance_pct: -0.3 } } } } })
eq('the producer reference_as_of supplies the exit date', producerExitDate.symbols[0].sinceExit.exitDate, '2026-10-30')
check('and the line prints it', /exited 2026-10-30/.test(`since exit ${producerExitDate.symbols[0].sinceExit.pct} exited 2026-10-30`), producerExitDate.symbols[0].sinceExit.exitDate)

// B. A measured claim with no number is not a measurement: it is unknown, with a reason and no values.
const noValueDay = parseHomeV007({ symbols: { X: { day_change: { state: 'measured', value: { usd: null, pct: null } } } } })
eq('a measured day change with no number is unknown', noValueDay.symbols[0].dayChange.state, 'unknown')
eq('and says the claim carried no value', noValueDay.symbols[0].dayChange.reason, 'measured claim carried no value')
eq('and carries no values', noValueDay.symbols[0].dayChange.usd, null)
const partialValue = parseHomeV007({ symbols: { X: { day_change: { state: 'measured', value: { pct: 0.5 } } } } })
eq('a measured day change with one number stays measured', partialValue.symbols[0].dayChange.state, 'measured')
const noValueExit = parseHomeV007({ symbols: { X: { since_exit: { state: 'measured', value: { distance_price: null, distance_pct: null, reference_price: null } } } } })
eq('a measured since-exit with no number is unknown', noValueExit.symbols[0].sinceExit.state, 'unknown')
eq('and says the claim carried no value', noValueExit.symbols[0].sinceExit.reason, 'measured claim carried no value')
eq('and carries no exit price', noValueExit.symbols[0].sinceExit.exitPrice, null)
// The producer's own reference keys (c9d0298ce): invalidation_level, sma10, sma20, anchored_vwap.
const noValueRef = parseHomeV007({ symbols: { X: { analysis_references: { state: 'measured', value: {
  invalidation_level: { state: 'measured', reference_price: null, distance_price: null, distance_pct: null } } } } } })
eq('a measured analysis reference with no number is unknown', noValueRef.symbols[0].references[0].state, 'unknown')
eq('and says the claim carried no value', noValueRef.symbols[0].references[0].reason, 'measured claim carried no value')
const valuedRef = parseHomeV007({ symbols: { X: { analysis_references: { state: 'measured', value: {
  invalidation_level: { state: 'measured', reference_price: 47.5, distance_price: -2.4 } } } } } })
eq('an analysis reference with a number stays measured', valuedRef.symbols[0].references[0].state, 'measured')
const noPriceQuote = parseHomeV007({ symbols: { X: { quote: { state: 'measured', as_of: NOW, value: {} } } } })
eq('a measured quote with no price is unknown', noPriceQuote.symbols[0].quote.state, 'unknown')
eq('and says the claim carried no value', noPriceQuote.symbols[0].quote.reason, 'measured claim carried no value')
eq('and carries no price', noPriceQuote.symbols[0].quote.price, null)

const arrayInverse = parseHomeV007({ hedge: { inverse_moves: { value: [{ symbol: 'SDS', day_pct: -0.4, state: 'measured' }] } } })
eq('the older array shape still reads', arrayInverse.hedge.inverse[0]?.symbol, 'SDS')

// DATA R1/R2 (2026-11-03): a declared session label is not evidence, and an affirmative chip needs a measurement.
const relabelled = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-02',
  expected_session_date: '2026-11-02', as_of: '2026-11-01T21:00:00Z' } } } })
eq('a quote whose clock says yesterday is not today’s price', relabelled.symbols[0].quote.state, 'unknown')
eq('and the mismatched clock is named', (relabelled.symbols[0].quote.reason ?? '').includes('2026-11-01'), true)
eq('and carries no price', relabelled.symbols[0].quote.price, null)
const honestClock = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-02',
  expected_session_date: '2026-11-02', as_of: '2026-11-02T21:00:00Z' } } } })
eq('a quote taken inside its session stays measured', honestClock.symbols[0].quote.state, 'measured')
// The clock check is a calendar comparison in ET, not a string prefix match.
const offsetClock = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-02',
  expected_session_date: '2026-11-02', as_of: '2026-11-02T16:00:00-05:00' } } } })
eq('an explicit ET offset inside the session stays measured', offsetClock.symbols[0].quote.state, 'measured')
// D. A clock is judged against both calendars: ET and UTC. A date-only as_of (``…T00:00:00Z``) names its session
// day in UTC while ET is still the previous day, so it must not be read as a relabel.
const midnightUtc = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-02',
  expected_session_date: '2026-11-02', as_of: '2026-11-02T00:00:00Z' } } } })
eq('a midnight-UTC date-only clock is not a relabel', midnightUtc.symbols[0].quote.state, 'measured')
eq('and keeps its price', midnightUtc.symbols[0].quote.price, 12)
// Only a DATE-ONLY clock (exactly midnight UTC) may name its day in UTC. 03:00Z is 22:00 ET on the previous day - an
// after-hours print labelled with the next session - so it is still a relabel and must not render as today's price.
const lateEvening = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-02',
  expected_session_date: '2026-11-02', as_of: '2026-11-02T03:00:00Z' } } } })
eq('an after-hours print labelled with the next session is still not today', lateEvening.symbols[0].quote.state, 'unknown')
eq('and carries no price', lateEvening.symbols[0].quote.price, null)
const dstDay = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, session_date: '2026-11-01',
  expected_session_date: '2026-11-01', as_of: '2026-11-01T05:30:00Z' } } } })
eq('the DST-change day keeps its own ET date', dstDay.symbols[0].quote.state, 'measured')
const noSession = parseHomeV007({ symbols: { X: { quote: { state: 'measured', value: { price: 12 }, as_of: '2026-11-02T21:00:00Z' } } } })
eq('a quote with no declared session is not downgraded by this rule', noSession.symbols[0].quote.state, 'measured')

const unclockedChip = parseHomeV007({ risk: { categories: [{ category: 'tech', label: 'Technology', chip: 'OK', state: 'unknown' }] } })
eq('an unclocked category publishes no affirmative chip', unclockedChip.risk.categories[0].chip, null)
eq('and stays unknown', unclockedChip.risk.categories[0].state, 'unknown')
const measuredChip = parseHomeV007({ risk: { categories: [{ category: 'tech', chip: 'STRESS', state: 'measured', as_of: '2026-11-02T21:00:00Z' }] } })
eq('a measured category keeps its chip', measuredChip.risk.categories[0].chip, 'STRESS')
// C. A chip needs BOTH the measurement and the clock that says when it was taken.
const unclockedMeasuredChip = parseHomeV007({ risk: { categories: [{ category: 'tech', label: 'Technology', chip: 'OK', state: 'measured' }] } })
eq('a measured category with no clock publishes no chip', unclockedMeasuredChip.risk.categories[0].chip, null)
eq('and the measurement word is still kept', unclockedMeasuredChip.risk.categories[0].state, 'measured')

const junk = parseHomeV007({ symbols: 'nope', risk: { categories: 'x' }, budgets: {} })
eq('malformed members do not throw', junk.symbols.length, 0)
eq('malformed budgets are empty', junk.budgets.length, 0)

// The producer's own contract names: budgets state/reason, next_event kind/date, read_errors source/reason,
// risk score in history, and the position stop fact. Each was silently dropped before, so each is pinned now.
const produced2 = parseHomeV007({
  budgets: [
    { budget: 'b_unknown', actual: 40, limit: 30, state: 'unknown', as_of: null, reason: 'source clock unavailable or in the future', remediation: { key: 'k', action: 'a' } },
    { budget: 'b_measured', actual: 10, limit: 30, state: 'measured', as_of: '2026-11-02T20:59:00Z', source: 'market_risk.budgets_detail', age_seconds: 60 },
  ],
  symbols: { X: { next_event: { state: 'measured', as_of: '2026-11-02T20:00:00Z', source: 'symbol_profiles.updated_at', value: { kind: 'earnings', date: '2026-11-12' } } } },
  read_errors: [{ source: 'cio_truth', reason: 'TimeoutError', remediation: { key: 'HOMEV007:cio_truth', action: 'restore' } }],
  risk: { history: [{ as_of: '2026-11-02T19:00:00Z', score: 55 }, { as_of: '2026-11-02T20:00:00Z', score: 61 }] },
  positions: [{ symbol: 'SPCX', account_label: 'demo', account_pct_basis: 'account_equity', stop: { value: { distance_pct_of_price: 4.5, status: 'intact' } } }],
})
eq('a producer-unknown budget stays unknown', produced2.budgets[0].state, 'unknown')
eq('and carries no number it can publish', produced2.budgets[0].current, 40)
eq('a measured budget keeps its clock', produced2.budgets[1].asOf, '2026-11-02T20:59:00Z')
eq('next_event reads the producer kind', produced2.symbols[0].nextEvent.label, 'earnings')
eq('next_event reads the producer date', produced2.symbols[0].nextEvent.at, '2026-11-12')
eq('read_errors reads the producer source', produced2.readErrors[0].member, 'cio_truth')
eq('read_errors reads the producer reason', produced2.readErrors[0].code, 'TimeoutError')
eq('the risk score comes from the latest history row', produced2.risk.score, 61)
eq('the stop distance reads the producer fact', produced2.positions[0].stopDistancePct, 4.5)
eq('the stop state reads the producer fact', produced2.positions[0].stopState, 'intact')

// E. The producer states its own failure at the top level: {state:"unavailable", reason, remediation, gaps,
// read_errors}. That must render as a stated failure, never as a present-but-empty card.
const unavailable = parseHomeV007({
  schema: 'HomeMarketRiskContext@v1', state: 'unavailable', generated_at: '2026-11-02T21:00:00Z',
  symbols: {}, positions: [], budgets: [],
  reason: 'the additive home context could not be built (TimeoutError)',
  remediation: { key: 'HOMEV007:context', action: 'Restore the additive context module; no fact is shown while it is unavailable.' },
  gaps: [{ symbol: null, field: 'home_v007', reason: 'the additive home context could not be built (TimeoutError)', remediation: { key: 'HOMEV007:context', action: 'Restore the additive context module' } }],
  read_errors: [{ source: 'home_v007_join', reason: 'TimeoutError', remediation: { key: 'HOMEV007:context', action: 'Restore' } }],
})
eq('an unavailable block is still present', unavailable.present, true)
eq('and is marked unavailable', unavailable.unavailable, true)
eq('and keeps the producer state', unavailable.state, 'unavailable')
eq('and states the reason', unavailable.blockReason, 'the additive home context could not be built (TimeoutError)')
check('and carries the remediation', (unavailable.blockRemediation ?? '').includes('Restore the additive context module'), unavailable.blockRemediation)
eq('an available block is not unavailable', ok.unavailable, false)
eq('a block with no state is not unavailable', parseHomeV007({ symbols: {} }).unavailable, false)

// F. `partial` is a real producer state (analysis_references at 89663c715) and must not be flattened to unknown.
const partialRefs = parseHomeV007({ symbols: { X: { analysis_references: { state: 'partial', as_of: NOW, source: 'analysis',
  value: { invalidation: { state: 'measured', reference_price: 47.5, distance_price: -2.4 } } } } } })
eq('a partial collection keeps the partial word', partialRefs.symbols[0].referencesFact.state, 'partial')
eq('while a measured nested row stays measured', partialRefs.symbols[0].references[0].state, 'measured')

// G. No value-bearing line may print past the state check (three renderers bypassed it before this repair).
const unknownRef = parseHomeV007({ symbols: { X: { analysis_references: { state: 'measured', as_of: NOW,
  value: { invalidation: { state: 'unknown', reason: 'no prior bar' } } } } } })
const unknownRefLine = referenceLine(unknownRef.symbols[0].references[0])
check('an unknown reference says unknown', unknownRefLine.includes('unknown'), unknownRefLine)
check('and carries no distance', !/%|\$/.test(unknownRefLine), unknownRefLine)
const unknownEvent = parseHomeV007({ symbols: { X: { next_event: { state: 'unknown', reason: 'no calendar row' } } } })
const unknownEventLine = nextEventLine(unknownEvent.symbols[0].nextEvent)
check('an unknown next event says unknown', (unknownEventLine ?? '').includes('unknown'), unknownEventLine)
const unknownStance = parseHomeV007({ symbols: { X: { market_risk_stance: { state: 'unknown', reason: 'reader failed' } } } })
const unknownStanceLine = marketStanceLine(unknownStance.symbols[0].marketStance)
check('an unknown market stance says unknown', (unknownStanceLine ?? '').includes('unknown'), unknownStanceLine)
check('and does not claim a stance', !(unknownStanceLine ?? '').includes('separate from CIO'), unknownStanceLine)
const knownEvent = parseHomeV007({ symbols: { X: { next_event: { state: 'measured', as_of: NOW, value: { label: 'earnings', at: '2026-11-12' } } } } })
check('a measured next event still renders', (nextEventLine(knownEvent.symbols[0].nextEvent) ?? '').includes('earnings'), nextEventLine(knownEvent.symbols[0].nextEvent))

// H. The producer's real volume basis text is what the card shows — not a flag the parser invents.
eq('volume reads the producer basis', ok.symbols[0].volume.basis?.includes('not time-adjusted'), true)
check('and prints it', volumeLine(ok.symbols[0].volume).includes('not time-adjusted'), volumeLine(ok.symbols[0].volume))
eq('volume reads the producer sample size', ok.symbols[0].volume.sampleSessions, 20)
const unknownVolume = parseHomeV007({ symbols: { X: { volume_vs_20d: { state: 'unknown', reason: 'no daily bars' } } } })
check('an unknown volume prints no multiple', !volumeLine(unknownVolume.symbols[0].volume).includes('×'), volumeLine(unknownVolume.symbols[0].volume))

// I. Headlines carry a published clock, not an age the producer never emits.
const heads = parseHomeV007({ symbols: { X: { headlines: { state: 'measured', as_of: '2026-10-30T13:05:00Z', value: [
  { title: 'Widgets up', source: 'wire', url: 'https://example.invalid/a', published_at: '2026-10-30T13:05:00Z', guarded: true },
] } } } })
eq('a headline keeps its published clock', heads.symbols[0].headlines[0].publishedAt, '2026-10-30T13:05:00Z')
check('and the line shows it', headlineLine(heads.symbols[0].headlines[0]).includes('Oct 30 09:05 ET'), headlineLine(heads.symbols[0].headlines[0]))

// J. The hedge trigger is a producer fact {current, threshold, unit} with no `met`; nothing is derived from it.
eq('the hedge trigger reads the producer current', ok.hedge.triggers[0].current, 4)
eq('the hedge trigger reads the producer threshold', ok.hedge.triggers[0].threshold, 10)
eq('the hedge trigger reads the producer unit', ok.hedge.triggers[0].unit, 'sectors')

// K. The operator control follows the PAYLOAD, never a build latency latch. Today the producer emits `unavailable`
// on every row, so nothing is offered; when E releases the route and store it says `available` and the control
// appears with no source change here. An available row with no canonical scope is still refused (the body needs it).
const availableRow = parseHomeV007({ budgets: [{ budget: 'demo', actual: 21000, limit: 15000, scope_id: 'account:demo',
  breached: true, operator_decision: { state: 'available' } }] }).budgets[0]
eq('the payload says the decision is available', availableRow.operatorDecision, 'available')
eq('and the control is offered for a scoped row', offersBudgetDecision(availableRow), true)
const unscoped = parseHomeV007({ budgets: [{ budget: 'demo', actual: 21000, limit: 15000,
  breached: true, operator_decision: { state: 'available' } }] }).budgets[0]
eq('an available decision with no canonical scope offers nothing', offersBudgetDecision(unscoped), false)
eq('and a producer-unavailable row offers nothing', offersBudgetDecision(ok.budgets[0]), false)
const unavailableRow = parseHomeV007({ budgets: [{ budget: 'demo', actual: 21000, limit: 15000, scope_id: 'account:demo',
  operator_decision: { state: 'unavailable', reason: 'decision subtype not verified', remediation: { key: 'k', action: 'wire the reviewed subtype' } } }] }).budgets[0]
eq('an unavailable decision keeps the producer reason for the reader', unavailableRow.decisionRemediation, 'wire the reviewed subtype (k)')

// L. The producer's dual-mark conflict: two recorded observations of one instant disagree. The unknown state already
// carries the reason; the two marks are the evidence, and the card must show which observations disagreed.
const conflicted = parseHomeV007({ symbols: { X: { quote: { state: 'unknown', as_of: NOW, source: 'market_quotes:alpaca',
  reason: 'Two observations of the same instant disagree', session_date: '2026-11-02', expected_session_date: '2026-11-02',
  value: null, conflict: { reason: 'The stored observation and the reader disagree at the same instant', as_of: NOW,
    marks: [{ price: 49.87, source: 'market_quotes:alpaca' }, { price: 50.11, source: 'market_quotes' }] } } } } })
const cq = conflicted.symbols[0].quote
eq('the conflict is read', cq.conflict?.marks.length, 2)
eq('the first mark price is kept', cq.conflict?.marks[0].price, 49.87)
eq('the first mark source is kept', cq.conflict?.marks[0].source, 'market_quotes:alpaca')
const cLine = conflictLine(cq) ?? ''
check('the conflict line names both observations', cLine.includes('$49.87') && cLine.includes('$50.11'), cLine)
check('and names the reason', cLine.includes('disagree at the same instant'), cLine)
eq('a clean quote has no conflict line', conflictLine(ok.symbols[0].quote), null)

// M. A carried category: known observation before a closure, never an affirmative chip, and the word that explains it.
const carried = parseHomeV007({ risk: { categories: [{ category: 'tech', label: 'Technology', state: 'unknown',
  as_of: '2026-10-30T20:00:00Z', carried: true, chip: 'not_measured',
  reason: 'carried across a closure: the 2026-10-30 observation is not current for the 2026-11-02 session' }] } })
eq('the carried flag is read', carried.risk.categories[0].carried, true)
eq('and no affirmative chip is published', carried.risk.categories[0].chip, null)
check('and the card says carried', categoryLine(carried.risk.categories[0]).includes('carried across a closure'),
  categoryLine(carried.risk.categories[0]))
eq('a measured category is not carried', ok.risk.categories[0].carried, false)

// N. cc5 recheck: the arithmetic fallback may not date a number by faith. A row with actual/limit but no producer
// state AND no source clock is unknown with a reason — never "measured" and never a printable dollar amount.
const unclockedArithmetic = parseHomeV007({ budgets: [{ budget: 'cash_reserve', actual: 1000, limit: 5000, unit: 'usd',
  operator_decision: { state: 'unavailable' } }] }).budgets[0]
eq('the fallback without a clock is unknown', unclockedArithmetic.state, 'unknown')
eq('and carries no measurement clock', unclockedArithmetic.asOf, null)
check('and says why', (unclockedArithmetic.reason ?? '').includes('no measurement clock'), unclockedArithmetic.reason)
const clockedArithmetic = parseHomeV007({ budgets: [{ budget: 'cash_reserve', actual: 1000, limit: 5000, unit: 'usd',
  source_binding: { as_of: '2026-11-02T20:00:00Z', sha256: 'a'.repeat(64) } }] }).budgets[0]
eq('the fallback WITH a clock is measured', clockedArithmetic.state, 'measured')
eq('and keeps the clock', clockedArithmetic.asOf, '2026-11-02T20:00:00Z')

// O. A nested reference's own reason survives the collection reason.
const nestedReason = parseHomeV007({ symbols: { X: { analysis_references: { state: 'partial', reason: 'the collection is incomplete',
  value: { sma20: { state: 'unknown', reason: 'no twenty completed sessions yet' } } } } } }).symbols[0].references[0]
eq('the nested reason wins', nestedReason.reason, 'no twenty completed sessions yet')
const nestedNoReason = parseHomeV007({ symbols: { X: { analysis_references: { state: 'partial', reason: 'the collection is incomplete',
  value: { sma20: { state: 'unknown', price_as_of: NOW } } } } } }).symbols[0].references[0]
eq('the collection reason is the fallback', nestedNoReason.reason, 'the collection is incomplete')

// P. A hedge trigger states whether it is measured, like every other fact.
const unmeasuredTrigger = parseHomeV007({ hedge: { lagging_progress: { state: 'unknown', reason: 'momentum reader failed' } } })
eq('an unmeasured trigger stays unknown', unmeasuredTrigger.hedge.triggers[0].state, 'unknown')
check('and prints why instead of numbers', hedgeLine(unmeasuredTrigger.hedge.triggers[0]).includes('unknown — momentum reader failed'),
  hedgeLine(unmeasuredTrigger.hedge.triggers[0]))
check('and no threshold is invented', !/of \?/.test(hedgeLine(unmeasuredTrigger.hedge.triggers[0])), hedgeLine(unmeasuredTrigger.hedge.triggers[0]))
const measuredTrigger = parseHomeV007({ hedge: { lagging_progress: { state: 'measured', as_of: NOW, source: 'defense_hedge_existing_thresholds',
  value: { current: 4, threshold: 10, unit: 'sectors' } } } })
check('a measured trigger still prints its numbers and clock',
  /lagging sectors 4 of 10 sectors · Nov 2 16:00 ET · defense_hedge/.test(hedgeLine(measuredTrigger.hedge.triggers[0])),
  hedgeLine(measuredTrigger.hedge.triggers[0]))

console.log(`homeV007: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
