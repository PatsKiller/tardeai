// node --experimental-strip-types src/lib/recoveryCases.test.ts
// Recovery & re-entry (piece D): the view model over /api/v2/recovery → recovery_cases. Synthetic fixtures only.
// No node:assert: CI's tsc has no @types/node, so this test carries a local check like the other lib tests.
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  ok(v: unknown, m = 'expected truthy') { if (!v) fail(m) },
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
  deepEqual(a: unknown, b: unknown, m?: string) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(m ?? `expected ${x} to deep-equal ${y}`) },
  match(s: string, re: RegExp, m?: string) { if (!re.test(s)) fail(m ?? `expected ${JSON.stringify(s)} to match ${re}`) },
}
import { actionStates, byImpact, caseView, eligibilityLine, homeCase, quoteLabel, recoveryProjection, reviewGate, stateCounts, NOT_WIRED, RECOVERY_ACTIONS } from './recoveryCases.ts'

const CASE = {
  schema: 'RecoveryCase@v1', case_key: 'DEMO::synthetic_ira::c1', symbol: 'demo', account: 'synthetic_ira', state: 'RECOVERING',
  state_since: '2026-11-02T21:00:00+00:00', materiality_tier: 'T1', realized_pnl: -1200, case_version: '2026-11-06T14:00:00+00:00',
  updated_at: '2026-11-06T14:00:00+00:00', as_of: '2026-11-06T14:00:00+00:00', source: 'synthetic',
  exits: [{ date: '2026-10-30', price: 50, stop_price: 50 }],
  eligibility: [{ account: 'synthetic_ira', eligible: true, eligible_from: null, reason: 'IRA', pending_operator_decision: true, answered: false },
    { account: 'synthetic_taxable', eligible: false, eligible_from: '2026-11-29', reason: 'house hold', pending_operator_decision: false, answered: true }],
  pending_operator_decision: true, plan: null, gaps: [], operator_decision: 'none',
  quote: { price: 52.5, observed_at: '2026-11-06T14:55:00+00:00', source: 'synthetic' },
}
const T3 = { ...CASE, case_key: 'ALT::synthetic_taxable::c2', symbol: 'ALT', materiality_tier: 'T3', state: 'WATCHING', exits: [{ date: '2026-11-03', price: 10 }], quote: null }
const SNOOZED = { ...CASE, case_key: 'ZZZ::synthetic_taxable::c3', symbol: 'ZZZ', state: 'SNOOZED' }
const resp = (cases: unknown[], extra: Record<string, unknown> = {}) => ({ items: [], recovery_cases: { schema: 'RecoveryCaseProjection@v1', state: 'ok', count: cases.length, generated_at: '2026-11-06T15:00:00+00:00', cases, actions: { names: [...RECOVERY_ACTIONS], wired: false, endpoint: null, reason: 'No server endpoint validates recovery-case actions yet.' }, ...extra } })

// 1. The projection renders the store's values; nothing is computed.
const p = recoveryProjection(resp([CASE, T3, SNOOZED]))
assert.equal(p.state, 'ok')
assert.equal(p.count, 3)
const c = p.cases[0]
assert.equal(c.symbol, 'DEMO')
assert.equal(c.stateLabel, 'Recovering', 'state label comes from the store state')
assert.equal(c.exitPrice, 50)
assert.equal(c.realizedPnl, -1200)
assert.equal(c.version, '2026-11-06T14:00:00+00:00')
assert.ok(!('size' in c) && !('stop' in c) && !('target' in c), 'no size, stop or target is invented')

// 2. The quote is always labelled with its observation time; absent → unavailable, never 0.
const q = quoteLabel(c.quote)
assert.equal(q.value, '$52.50')
assert.match(q.detail, /^Quote observed Nov 6, 9:55 AM EST · synthetic$/)
assert.deepEqual(quoteLabel(null), { value: 'Unavailable', detail: 'Quote source unavailable' })
assert.equal(caseView({ ...CASE, quote: { price: 0, observed_at: 'x' } })!.quote, null, 'a zero price is not a quote')
assert.match(quoteLabel(caseView({ ...CASE, quote: { price: 1, observed_at: null } })!.quote).detail, /time unavailable/)
assert.equal(caseView({ ...CASE, realized_pnl: null })!.realizedPnl, null, 'unknown P&L stays unknown')

// 3. Unavailable is unavailable, never zero.
const down = recoveryProjection({ items: [], recovery_cases: { state: 'unavailable', reason: 'recovery case store not reachable', count: null, cases: [], actions: { wired: false } } })
assert.equal(down.state, 'unavailable')
assert.equal(down.count, null)
assert.equal(stateCounts(down), null, 'no counts for an unanswered read')
const err = recoveryProjection(null, 'HTTP 503')
assert.equal(err.state, 'unavailable')
assert.equal(err.count, null)
const old = recoveryProjection({ items: [{ symbol: 'X' }] })
assert.equal(old.state, 'missing', 'a server without the block is not "no cases"')
assert.equal(old.count, null)
assert.deepEqual(stateCounts(recoveryProjection(resp([]))), { needsReview: 0, watching: 0, snoozed: 0, closed: 0 }, 'zero only for an answered empty read')

// 4. Home: the open T1 case only; ordering uses the recorded tier.
assert.equal(homeCase(p)!.key, CASE.case_key)
assert.equal(homeCase(recoveryProjection(resp([T3, SNOOZED]))), null, 'no T1 open case → no Home card')
assert.deepEqual([...p.cases].sort(byImpact).map(x => x.symbol), ['DEMO', 'ZZZ', 'ALT'])

// 5. Actions: exactly the four, disabled "not wired yet" while the server has no validating endpoint.
const acts = actionStates(p, c, 'fresh', false)
assert.deepEqual(acts.map(a => a.action), ['create_reentry_plan', 'watch', 'close_case', 'snooze'])
assert.ok(acts.every(a => !a.enabled && a.why === NOT_WIRED))
const fake = recoveryProjection(resp([CASE], { actions: { wired: true, endpoint: null } }))
assert.equal(fake.actionsWired, false, 'wired without an endpoint is not wired')
const wired = recoveryProjection(resp([CASE], { actions: { wired: true, endpoint: '/api/v2/recovery/cases/action' } }))
assert.ok(actionStates(wired, wired.cases[0], 'fresh', false).every(a => a.enabled))
assert.ok(actionStates(wired, wired.cases[0], 'changed', false).every(a => !a.enabled), 'a changed case requires a fresh review')
assert.ok(actionStates(wired, wired.cases[0], 'fresh', true).every(a => !a.enabled), 'unavailable source pauses decisions')

// 6. Review gate: a new version on screen is "changed"; a case without a version can never be bound.
const v2 = caseView({ ...CASE, case_version: '2026-11-06T15:20:00+00:00' })!
assert.equal(reviewGate(undefined, c), 'fresh')
assert.equal(reviewGate(c.version, c), 'fresh')
assert.equal(reviewGate(c.version, v2), 'changed')
assert.equal(reviewGate(null, caseView({ ...CASE, case_version: null })!), 'changed')

// 7. Eligibility is the store's answer, labelled; pending stays pending.
assert.deepEqual(eligibilityLine(c.eligibility[0]), { value: 'Eligibility pending', tone: 'warning' })
assert.deepEqual(eligibilityLine(c.eligibility[1]), { value: 'Hold through 2026-11-29', tone: 'warning' })

console.log('recoveryCases: ok')
