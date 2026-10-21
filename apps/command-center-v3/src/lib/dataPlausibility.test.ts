import { plausibilityFrom, plausibilityTone } from './dataPlausibility.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const ok = plausibilityFrom({ status: 'OK', checked: 12, violations: 0, blocking: 0, blocking_items: [], ran_at: '2026-10-21T10:20:45Z', age_h: 3, rules: null, note: 'receipt predates per-rule rows' })
check('old receipt: counts, no rules, note kept', ok.status === 'OK' && ok.checked === 12 && ok.rules === null && !!ok.note)
const b = plausibilityFrom({ status: 'BLOCK', checked: 2, violations: 1, blocking: 1, blocking_items: ['t.a'],
  rules: [{ table: 't', column: 'a', status: 'VIOLATION', severity: 'BLOCK', violations: 4, total: 10, detail: 'pct' }] })
check('BLOCK carries per-rule rows', b.status === 'BLOCK' && b.rules?.[0].name === 't.a' && b.rules?.[0].violations === 4 && b.blockingItems[0] === 't.a')
check('BLOCK tone danger, STALE warning', plausibilityTone('BLOCK') === 'danger' && plausibilityTone('STALE') === 'warning')
check('unknown status is UNAVAILABLE', plausibilityFrom({ status: 'WAT' }).status === 'UNAVAILABLE')
check('NO_RECEIPT is not green', plausibilityTone(plausibilityFrom({ status: 'NO_RECEIPT' }).status) === 'danger')
check('no payload UNAVAILABLE', plausibilityFrom(null, { error: 'HTTP 500' }).note === 'HTTP 500')
console.log(`dataPlausibility: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
