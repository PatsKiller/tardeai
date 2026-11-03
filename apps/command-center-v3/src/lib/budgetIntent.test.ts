// Budget intent requests — the body can only carry what the decide route allows.
//   node --experimental-strip-types src/lib/budgetIntent.test.ts
import {
  BUDGET_DECIDE_PATH, basisUrl, currentBasis, futureUtcZ, historyRecords, humanError, intentBody, networkOutcomeUnknown, reconcile, refusedText, requestId, toUtcZ,
} from './budgetIntent.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (n: string, got: unknown, want: unknown) => check(n, got === want, got)
const throws = (n: string, fn: () => unknown) => { try { fn(); check(n, false, 'no throw') } catch { check(n, true) } }

const SHA = 'a'.repeat(64), OTHER = 'b'.repeat(64)
const NOW = Date.parse('2026-11-03T05:00:00Z')
const UNTIL = '2026-11-10T05:00:00Z'
const base = { scopeId: 'account:demo', budget: 'demo_taxable', binding: { as_of: '2026-11-03T04:59:00Z', sha256: SHA }, untilUtc: UNTIL, requestId: 'req-12345678', dryRun: false }

const body = intentBody(base, NOW)
eq('subtype is the contract word', body.subtype, 'market_risk_budget_presentation')
eq('action is intentional_until', body.action, 'intentional_until')
eq('scope is carried', body.scope_id, 'account:demo')
eq('budget is carried', body.budget, 'demo_taxable')
eq('the binding is carried verbatim', body.source_binding.sha256, SHA)
eq('expiry is the UTC instant', body.intentional_until, UNTIL)
check('a real write sends no dry_run key', !('dry_run' in body), Object.keys(body))

const keys = Object.keys(body).sort()
check('no actor, amount, limit or breach can be sent', !keys.some(k => ['actor', 'actual', 'limit', 'breached', 'breach', 'price'].includes(k)), keys)
check('only allowlisted fields are present', keys.every(k => ['subtype', 'action', 'scope_id', 'budget', 'source_binding', 'intentional_until', 'request_id', 'comment', 'dry_run'].includes(k)), keys)

const preview = intentBody({ ...base, dryRun: true }, NOW)
eq('a preview is dry_run: true', preview.dry_run, true)
check('a preview still names subtype/action', preview.subtype === 'market_risk_budget_presentation' && preview.action === 'intentional_until')

const withComment = intentBody({ ...base, comment: '  raise for review  ' }, NOW)
eq('a comment is trimmed', withComment.comment, 'raise for review')
check('an empty comment is omitted', !('comment' in intentBody({ ...base, comment: '   ' }, NOW)))
check('a long comment is bounded', (intentBody({ ...base, comment: 'x'.repeat(5000) }, NOW).comment ?? '').length === 4000)

throws('a past expiry is refused', () => intentBody({ ...base, untilUtc: '2026-11-02T05:00:00Z' }, NOW))
eq('an offset expiry is normalised to the same UTC instant', intentBody({ ...base, untilUtc: '2026-11-10T05:00:00+02:00' }, NOW).intentional_until, '2026-11-10T03:00:00Z')
throws('a missing binding is refused', () => intentBody({ ...base, binding: null }, NOW))
throws('a short sha is refused', () => intentBody({ ...base, binding: { as_of: '2026-11-03T04:59:00Z', sha256: 'abc' } }, NOW))
throws('a missing scope is refused', () => intentBody({ ...base, scopeId: null }, NOW))
throws('a missing request id is refused', () => intentBody({ ...base, requestId: 'short' }, NOW))

eq('toUtcZ converts a local value to Z', /Z$/.test(String(toUtcZ('2026-11-10T05:00'))), true)
eq('toUtcZ refuses junk', toUtcZ('not a date'), null)
eq('futureUtcZ accepts a future instant', futureUtcZ('2026-11-10T05:00', NOW), toUtcZ('2026-11-10T05:00'))
eq('futureUtcZ refuses a past instant', futureUtcZ('2026-10-01T05:00', NOW), null)

const basis = currentBasis({ current: { source_binding: { as_of: '2026-11-03T04:59:00Z', sha256: SHA }, breached: true, snapshot_as_of: '2026-11-03T05:00:00Z' }, budget_presentation_decisions: { complete: true } })
eq('the basis binding is read', basis.binding?.sha256, SHA)
eq('the breach is read', basis.breached, true)
eq('the snapshot clock is read', basis.asOf, '2026-11-03T05:00:00Z')
const unavailable = currentBasis({ current: null, budget_presentation_decisions: { complete: false } })
eq('a 503 basis carries no binding', unavailable.binding, null)
eq('and asserts no breach either', unavailable.breached, null)

eq('a source change is explained, not guessed', humanError({ ok: false, status: 409, code: 'BUDGET_SOURCE_CHANGED', data: null, outcome: 'refused' }).startsWith('The measurement changed'), true)
// E(i). An unrecognised code (and an unknown outcome) must never be reported as "nothing was written".
const unknownCodeText = humanError({ ok: false, status: 500, code: 'X', data: null, outcome: 'refused' })
check('an unknown code does not claim nothing was written', !/nothing was written/i.test(unknownCodeText), unknownCodeText)
check('and points at the history before retrying', /could not be confirmed/.test(unknownCodeText) && /history/.test(unknownCodeText), unknownCodeText)
const unknownOutcomeText = humanError({ ok: false, status: 0, code: null, data: null, outcome: 'unknown' })
check('a no-code unknown outcome does not claim nothing was written', !/nothing was written/i.test(unknownOutcomeText), unknownOutcomeText)
eq('the basis url carries both identifiers', basisUrl('account:demo', 'demo_taxable'), '/api/v2/governance/budget-presentation?scope_id=account%3Ademo&budget=demo_taxable')
eq('the decide path is the contract path', BUDGET_DECIDE_PATH, '/api/v2/governance/budget-presentation/decide')
check('request ids are unique and allowed', /^[A-Za-z0-9_-]{8,80}$/.test(requestId()) && requestId() !== requestId())

// A binding that is not the clicked row's must never be substituted: the body carries exactly what it was given.
const other = intentBody({ ...base, binding: { as_of: '2026-11-03T04:59:00Z', sha256: OTHER } }, NOW)
eq('a different binding is carried as given, never merged', other.source_binding.sha256, OTHER)

eq('a 503 source is explained, not called a missing binding', humanError({ ok: false, status: 503, code: 'SOURCE_UNAVAILABLE', data: null, outcome: 'refused' }).includes('source is unavailable'), true)
eq('an unintegrated route says so', humanError({ ok: false, status: 404, code: 'NOT_FOUND', data: null, outcome: 'refused' }).includes('not available on the running backend'), true)
eq('an invalid field is named', humanError({ ok: false, status: 400, code: 'INVALID_PRESENTATION_FIELDS', data: null, outcome: 'refused' }).includes('does not accept'), true)
check('a dropped reply never claims nothing was written', networkOutcomeUnknown(new TypeError('Failed to fetch')).includes('outcome is unknown'))
check('and names the safe retry', /same request|replays/.test(networkOutcomeUnknown(new TypeError('Failed to fetch'))))

// R1/R2 (cx4 reviewer2, 2026-11-03): history is evidence, and an uncertain outcome is never "nothing was written".
const event = { event: 'BUDGET_PRESENTATION_DECISION', request_id: 'req-12345678', scope_id: 'account:demo', budget: 'demo_taxable',
  source_binding: { as_of: '2026-11-03T04:59:00Z', sha256: SHA }, intentional_until: UNTIL, hash_self: 'c'.repeat(64), active: false }
const ledger = historyRecords({ budget_presentation_decisions: { complete: true, items: [event], history: [event] } })
eq('history items and history are merged without duplicates', ledger.length, 1)
eq('the receipt is kept', ledger[0].receipt, 'c'.repeat(64))
eq('an inactive decision is not called active', ledger[0].active, false)
const pendingReal = { ...preview, dry_run: undefined } as any
eq('the pending request is found by id and payload', reconcile(ledger, pendingReal)?.requestId, 'req-12345678')
eq('a different binding is not a match', reconcile(ledger, { ...pendingReal, source_binding: { as_of: pendingReal.source_binding.as_of, sha256: OTHER } }), null)
// E(ii). The binding is the SOURCE and its clock: the same sha at a different as_of is a different measurement.
eq('the same sha at a different as_of is not a match', reconcile(ledger, { ...pendingReal, source_binding: { ...pendingReal.source_binding, as_of: '2026-11-03T04:58:00Z' } }), null)
eq('a different expiry is not a match', reconcile(ledger, { ...pendingReal, intentional_until: '2026-11-11T05:00:00Z' }), null)
eq('a different scope is not a match', reconcile(ledger, { ...pendingReal, scope_id: 'account:other' }), null)
eq('a 503 basis carries its history', historyRecords({ current: null, budget_presentation_decisions: { complete: false, history: [event] } }).length, 1)
eq('an empty ledger is an empty list, not an error', historyRecords({ budget_presentation_decisions: { complete: true, items: [] } }).length, 0)
check('a refusal never claims nothing was written', refusedText('BUDGET_SOURCE_CHANGED').includes('not proof'))
check('an unknown code still says a refusal is not proof', refusedText('X').includes('not proof'))

// E's REAL projected shape (cx4 review artifacts): the item carries the receipt and active flag, its nested
// history events carry the request id and the composite binding. Reading only the item's top level finds no id.
const projected = { budget_presentation_decisions: { complete: true, items: [{
  scope_id: 'scope_synthetic_a', budget: 'single_sector_pct', breached: true, active: true,
  intentional_until: '2032-04-12T14:05:00Z', actor: 'tailnet:fixture-operator@example.test', receipt: 'f'.repeat(64),
  history: [{ event: 'BUDGET_PRESENTATION_DECISION', request_id: 'review2-actual-ui-body-001', scope_id: 'scope_synthetic_a',
    budget: 'single_sector_pct', intentional_until: '2032-04-12T14:05:00Z',
    source_binding: { as_of: '2032-04-12T13:59:00Z', sha256: 'f78f8000fb187028dabdbe57772470f4e4d6e202f044b26d54994d446f6bb050' } }] }] } }
const projectedRecords = historyRecords(projected)
eq('a projected decision is one record, not two', projectedRecords.length, 1)
eq('the request id comes from the nested event', projectedRecords[0].requestId, 'review2-actual-ui-body-001')
eq('the receipt comes from the item', projectedRecords[0].receipt, 'f'.repeat(64))
eq('the active flag comes from the item', projectedRecords[0].active, true)
const projectedPending = { ...preview, request_id: 'review2-actual-ui-body-001', scope_id: 'scope_synthetic_a', budget: 'single_sector_pct',
  intentional_until: '2032-04-12T14:05:00Z', source_binding: { as_of: '2032-04-12T13:59:00Z', sha256: 'f78f8000fb187028dabdbe57772470f4e4d6e202f044b26d54994d446f6bb050' } } as any
eq('an uncertain write reconciles against the projected shape', reconcile(projectedRecords, projectedPending)?.requestId, 'review2-actual-ui-body-001')
check('and a different binding still does not match', reconcile(projectedRecords, { ...projectedPending, source_binding: { ...projectedPending.source_binding, sha256: OTHER } }) === null)

console.log(`budgetIntent: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
