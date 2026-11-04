// FQ-002: a missing indicator is not a missing quote. Synthetic closed-journal evidence only.
// Pure helper tests; actual-page integration and build registration belong to the parent.
import { advisoryReentryPresentation } from './advisoryReason.ts'

declare const process: { exit(code?: number): never }
let passed = 0, failed = 0
function equal(name: string, actual: unknown, expected: unknown) {
  if (actual === expected) { passed++; console.log(`PASS ${name}`) }
  else { failed++; console.error(`FAIL ${name}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`) }
}
function check(name: string, condition: boolean) { equal(name, condition, true) }
const field = (value: unknown, state = 'AVAILABLE') => ({ value, state })
const missing = (reason: string) => ({ value: null, state: 'DATA_UNAVAILABLE', reason })
function row(price: unknown, rsi: unknown, extra: Record<string, unknown> = {}): any {
  return { symbol: 'SYNTHA', row_class: 'closed_journal', verdict: 'WAIT',
    reentry: { state: field('MISSING MARKET'),
      ...(price === undefined ? {} : { price }), ...(rsi === undefined ? {} : { rsi }) }, ...extra }
}
const reasons = {
  rsi: 'A price is recorded, but RSI is unavailable. Waiting for refreshed technical evidence.',
  quote: 'RSI is recorded, but a quote is unavailable. Waiting for refreshed quote evidence.',
  both: 'A quote and RSI are unavailable. Waiting for refreshed market and technical evidence.',
  complete: 'Market evidence is incomplete. Waiting for refreshed re-entry evidence.',
}
function presentation(name: string, input: unknown, stateLabel: string | null, reason: string | null) {
  const result = advisoryReentryPresentation(input)
  equal(`${name}: state`, result.stateLabel, stateLabel)
  equal(`${name}: reason`, result.reason, reason)
}

presentation('recorded quote, typed missing RSI', row(field(22.5), missing('no_rsi')),
  'RSI unavailable', reasons.rsi)
presentation('typed missing quote, recorded RSI', row(missing('no_current_quote'), field(55)),
  'Quote unavailable', reasons.quote)
presentation('both typed fields missing', row(missing('no_current_quote'), missing('no_rsi')),
  'Quote and RSI unavailable', reasons.both)
presentation('both present never invent a missing field', row(field(22.5), field(55)),
  'Market evidence incomplete', reasons.complete)
presentation('RSI zero is recorded evidence', row(field(22.5), field(0)),
  'Market evidence incomplete', reasons.complete)
presentation('RSI zero does not hide a missing quote', row(missing('no_current_quote'), field(0)),
  'Quote unavailable', reasons.quote)

// An explicit canonical missing state is stronger than an old convenience scalar.
presentation('typed missing RSI beats populated legacy RSI',
  row(field(22.5), missing('no_rsi'), { reentry_rsi: 55 }), 'RSI unavailable', reasons.rsi)
presentation('typed missing quote beats populated legacy price',
  row(missing('no_quote'), field(55), { reentry_price: 22.5 }), 'Quote unavailable', reasons.quote)
presentation('typed missing ignores contradictory own value and scalar',
  row({ state: 'DATA_UNAVAILABLE', value: 22.5 }, field(55), { reentry_price: 25 }),
  'Quote unavailable', reasons.quote)
presentation('typed null quote blocks legacy scalar',
  row(field(null), field(55), { reentry_price: 22.5 }), 'Quote unavailable', reasons.quote)
presentation('typed undefined RSI blocks legacy scalar',
  row(field(22.5), field(undefined), { reentry_rsi: 55 }), 'RSI unavailable', reasons.rsi)
presentation('missing reentry quote cannot borrow present watch quote',
  row(missing('no_quote'), field(55), { watch_intelligence: {
    available: true, quote: { last: field(99), price_as_of: '2031-01-02T15:00:00Z' } } }),
  'Quote unavailable', reasons.quote)
presentation('legacy values remain compatible when typed fields absent',
  row(undefined, undefined, { reentry_price: 22.5, reentry_rsi: 0 }),
  'Market evidence incomplete', reasons.complete)

for (const [label, value] of [['zero', 0], ['negative', -1], ['infinite', Infinity],
  ['NaN', NaN], ['numeric string', '22.5'], ['boolean', true]] as const) {
  presentation(`invalid quote ${label}`, row(field(value), field(55)), 'Quote unavailable', reasons.quote)
}
for (const [label, value] of [['infinite', Infinity], ['NaN', NaN], ['numeric string', '55'],
  ['boolean', false]] as const) {
  presentation(`invalid RSI ${label}`, row(field(22.5), field(value)), 'RSI unavailable', reasons.rsi)
}

// Existing higher-priority product states and the actual page's headline order stay intact.
for (const state of ['WASH BLOCK', 'CURRENTLY HELD', 'STALE', 'MISSING PLAN']) {
  const input = row(missing('no_quote'), missing('no_rsi'))
  input.reentry.state = field(state)
  input.why_call = `Retain recorded ${state} condition.`
  presentation(`priority ${state}`, input, state, input.why_call)
}
const priority = row(field(22.5), missing('no_rsi'), { reentry_state: 'MISSING MARKET',
  why_call: 'First recorded headline.', rationale_signals: ['Second recorded headline.'],
  rationale: 'Third recorded headline.' })
priority.reentry.state = field('CURRENTLY HELD')
priority.reentry.why = 'Nested detail.'
presentation('canonical nonmissing state beats legacy missing state', priority,
  'CURRENTLY HELD', 'First recorded headline.')
const signal = { ...priority, why_call: undefined }
presentation('rationale signal beats rationale and nested why', signal,
  'CURRENTLY HELD', 'Second recorded headline.')
presentation('rationale beats nested detail', { ...signal, rationale_signals: [] },
  'CURRENTLY HELD', 'Third recorded headline.')
presentation('nested detail is retained when row headline absent',
  { ...signal, rationale_signals: [], rationale: undefined }, 'CURRENTLY HELD', 'Nested detail.')

const internal = { ...priority, why_call: 'indicator_confluence_cache unavailable; run indicator_cache_refresh' }
const rendered = advisoryReentryPresentation(internal)
check('known internal cache/job names leave operator reason',
  !/indicator_confluence_cache|indicator_cache_refresh/.test(rendered.reason || ''))
check('internal-name mapping leaves a meaningful reason', !!rendered.reason && rendered.reason.length > 15)
presentation('unrelated source identifiers remain verbatim',
  { ...priority, why_call: 'watchlist_strategy_cards and enrichment_cache remain audit source labels.' },
  'CURRENTLY HELD', 'watchlist_strategy_cards and enrichment_cache remain audit source labels.')
presentation('ordinary text is not blindly rewritten',
  { ...priority, why_call: 'Review the recorded evidence; do not change the advisory decision.' },
  'CURRENTLY HELD', 'Review the recorded evidence; do not change the advisory decision.')

function deepFreeze(value: any): any {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) deepFreeze(child)
    Object.freeze(value)
  }
  return value
}
const immutable = deepFreeze(row(field(22.5), missing('no_rsi'), {
  verdict: 'WAIT', allowed_action_now: 'WATCH_ONLY', proposal_allowed: false,
  reentry_state: 'MISSING MARKET' }))
const before = JSON.stringify(immutable)
presentation('frozen source remains renderable', immutable, 'RSI unavailable', reasons.rsi)
equal('projection does not mutate source verdict/action/raw state', JSON.stringify(immutable), before)
for (const input of [null, undefined, 17, 'synthetic malformed row', []]) {
  presentation('malformed row has no invented state or reason', input, null, null)
}
console.log(`advisoryReason: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
