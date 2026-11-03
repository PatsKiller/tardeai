// Budget intent requests — the body can only carry what the decide route allows.
//   node --experimental-strip-types src/lib/budgetIntent.test.ts
import {
  BUDGET_DECIDE_PATH, basisUrl, currentBasis, futureUtcZ, humanError, intentBody, requestId, toUtcZ,
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

eq('a source change is explained, not guessed', humanError({ ok: false, status: 409, code: 'BUDGET_SOURCE_CHANGED', data: null }).startsWith('The measurement changed'), true)
eq('an unknown code still says nothing was written', humanError({ ok: false, status: 500, code: 'X', data: null }).includes('Nothing was written'), true)
eq('the basis url carries both identifiers', basisUrl('account:demo', 'demo_taxable'), '/api/v2/governance/budget-presentation?scope_id=account%3Ademo&budget=demo_taxable')
eq('the decide path is the contract path', BUDGET_DECIDE_PATH, '/api/v2/governance/budget-presentation/decide')
check('request ids are unique and allowed', /^[A-Za-z0-9_-]{8,80}$/.test(requestId()) && requestId() !== requestId())

// A binding that is not the clicked row's must never be substituted: the body carries exactly what it was given.
const other = intentBody({ ...base, binding: { as_of: '2026-11-03T04:59:00Z', sha256: OTHER } }, NOW)
eq('a different binding is carried as given, never merged', other.source_binding.sha256, OTHER)

console.log(`budgetIntent: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
