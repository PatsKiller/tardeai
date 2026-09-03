/**
 * operatorBoundary.ts — what the operator name and the write token actually mean.
 *
 * Two questions were rendered as one:
 *
 *   "who is this?"      `admin_operator` is a string the browser owns. Nothing
 *                       verifies it. It labels the append-only audit row; it
 *                       authenticates nobody.
 *   "may they write?"   `admin_write_guard.access_ok()` compares the supplied
 *                       token to ADMIN_WRITE_TOKEN — but returns true when that
 *                       variable is UNSET ("air-gapped default: access is open").
 *                       So the gate is DECLARED in code and EFFECTIVE only when
 *                       the running process is configured.
 *
 * A UI that shows a name and an armed button answers both questions with one
 * unverified value. This module keeps them apart and refuses to guess: an
 * unreachable authority endpoint yields UNKNOWN, and UNKNOWN is never treated as
 * authorized.
 *
 * Client half of OperatorIdentityBoundary@v1. Pure functions. No network, no
 * React, no side effects.
 */

export type OperatorBoundaryPayload = {
  schema?: string
  status?: string
  reason?: string | null
  client_storage_is_security_boundary?: boolean
  write_gate_declared?: boolean
  write_gate_effective?: boolean
  operator_identity_verified?: boolean
  identity_display_source?: string
  ui_requirement?: string
}

export type GuardState = 'ENFORCED' | 'OPEN' | 'UNKNOWN'

export type OperatorBoundaryVerdict = {
  /** Whether the server proved a write gate is actually in force. */
  guard: GuardState
  /** Operator-facing sentence. Always populated. */
  reason: string
  /** The audit label the browser holds. Never an identity. */
  operatorLabel: string
  /** Always false — nothing verifies the client-supplied name. */
  identityVerified: false
  /**
   * May a guarded control render armed? Only when the server said the gate is
   * effective. OPEN and UNKNOWN both disarm: an open door is not a permission,
   * and an unanswered question is not a yes.
   */
  controlsMayArm: boolean
  /** Exact reason to show on a disabled control. Empty when controls may arm. */
  disabledReason: string
}

export function operatorBoundaryVerdict(
  payload: OperatorBoundaryPayload | null | undefined,
  operatorLabel: string,
): OperatorBoundaryVerdict {
  const label = (operatorLabel || '').trim() || 'unnamed operator'

  if (!payload || payload.status === 'UNAVAILABLE') {
    return {
      guard: 'UNKNOWN',
      reason:
        payload?.reason ||
        'the operator-identity boundary endpoint did not answer; the server has not said whether a write gate is in force',
      operatorLabel: label,
      identityVerified: false,
      controlsMayArm: false,
      disabledReason:
        'disabled: the server has not confirmed that a write gate is in force, so this control cannot be proven safe',
    }
  }

  const declared = payload.write_gate_declared === true
  const effective = payload.write_gate_effective === true

  if (effective) {
    return {
      guard: 'ENFORCED',
      reason: 'the server compares the supplied token against a secret the browser never had',
      operatorLabel: label,
      identityVerified: false,
      controlsMayArm: true,
      disabledReason: '',
    }
  }

  return {
    guard: 'OPEN',
    reason: declared
      ? 'a write gate is declared in admin_write_guard.access_ok() but ADMIN_WRITE_TOKEN is not configured in the serving process, so the guarded door is open'
      : 'no server-side write gate was found',
    operatorLabel: label,
    identityVerified: false,
    controlsMayArm: false,
    disabledReason: declared
      ? 'disabled: ADMIN_WRITE_TOKEN is not configured in the serving process, so this control would write through an open door'
      : 'disabled: no server-side write gate was found for this control',
  }
}

/** The operator name, stated as what it is. Never rendered as a verified identity. */
export function operatorAuditLabel(name: string): string {
  const n = (name || '').trim() || 'unnamed operator'
  return `${n} · unverified audit label`
}
