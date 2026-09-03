// Pure-logic tests for operatorBoundary.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/operatorBoundary.test.ts
//
// Proves the two questions stay apart: a name is never an identity, and an
// unanswered or open gate never arms a control.
import { operatorBoundaryVerdict, operatorAuditLabel } from './operatorBoundary.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ── the gate is enforced ─────────────────────────────────────────────────────
{
  const v = operatorBoundaryVerdict(
    { write_gate_declared: true, write_gate_effective: true }, 'john')
  check('enforced gate reports ENFORCED', v.guard === 'ENFORCED')
  check('enforced gate lets controls arm', v.controlsMayArm === true)
  check('enforced gate has no disabled reason', v.disabledReason === '')
  check('identity is still never verified', v.identityVerified === false)
}

// ── declared but not configured: the door is open ────────────────────────────
{
  const v = operatorBoundaryVerdict(
    { write_gate_declared: true, write_gate_effective: false }, 'john')
  check('declared-but-unconfigured reports OPEN', v.guard === 'OPEN')
  check('an open door does not arm controls', v.controlsMayArm === false)
  check('the disabled reason names ADMIN_WRITE_TOKEN', v.disabledReason.includes('ADMIN_WRITE_TOKEN'))
  check('the reason explains declared vs effective', v.reason.includes('declared'))
}

// ── no gate at all ───────────────────────────────────────────────────────────
{
  const v = operatorBoundaryVerdict(
    { write_gate_declared: false, write_gate_effective: false }, 'john')
  check('no declared gate reports OPEN', v.guard === 'OPEN')
  check('no declared gate does not arm controls', v.controlsMayArm === false)
  check('no declared gate says so', v.disabledReason.includes('no server-side write gate'))
}

// ── the endpoint did not answer ──────────────────────────────────────────────
{
  for (const p of [null, undefined, { status: 'UNAVAILABLE', reason: 'ImportError: boom' }]) {
    const v = operatorBoundaryVerdict(p as never, 'john')
    check('an unanswered boundary is UNKNOWN', v.guard === 'UNKNOWN')
    check('UNKNOWN never arms a control', v.controlsMayArm === false)
    check('UNKNOWN gives an exact disabled reason', v.disabledReason.startsWith('disabled:'))
  }
  const withReason = operatorBoundaryVerdict({ status: 'UNAVAILABLE', reason: 'ImportError: boom' }, 'john')
  check('UNKNOWN surfaces the server reason verbatim', withReason.reason === 'ImportError: boom')
}

// ── the name is a label, not an identity ─────────────────────────────────────
{
  check('audit label is marked unverified', operatorAuditLabel('john') === 'john · unverified audit label')
  check('an empty name is not silently accepted', operatorAuditLabel('') === 'unnamed operator · unverified audit label')
  check('whitespace is not an operator', operatorAuditLabel('   ') === 'unnamed operator · unverified audit label')
  const v = operatorBoundaryVerdict({ write_gate_effective: true, write_gate_declared: true }, '  ')
  check('a blank operator falls back to unnamed', v.operatorLabel === 'unnamed operator')
}

console.log(`\noperatorBoundary: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
