// The one place a failed response becomes a sentence the operator reads.
//
// BOARD row 35: a 403 used to render "this operator is not permitted this surface" for EVERY refusal, including
// the one that means "you did not present your identity". Those are different facts with different remedies, and
// the operator can only act on the second. The classification lives in lib/httpOutcome (classifyStatus); this
// component renders it, so the rendered sentence and the classification are one path.
import type { CSSProperties } from 'react'
import { TOKENS, TYPE } from '../lib/designTokens'
import type { Outcome } from '../lib/httpOutcome'

export function OutcomeNotice({ outcome, prefix }: { outcome: Outcome; prefix?: string }) {
  const identity = outcome.kind === 'IDENTITY_REQUIRED'
  const style: CSSProperties = {
    fontSize: TYPE.sm,
    color: identity ? 'var(--amber)' : TOKENS.danger,
    margin: 0,
  }
  return (
    <div role={identity ? 'alert' : 'status'} data-outcome={outcome.kind} style={style}>
      {prefix ? `${prefix}: ` : ''}{outcome.message}
    </div>
  )
}

export default OutcomeNotice
