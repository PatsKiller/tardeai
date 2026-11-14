/** The two Deploys facts, kept apart (LQ-20261113-3077/3084): what is SERVED, then the poller's last decision.
 *  Pure of hooks so a render test can pin it; DeploysPanel draws it. */
import { Chip } from '../primitives/Chip'
import type { DeploysSummary } from '../../lib/deploys'
import { readableTime } from '../../lib/readableTime'
import { TOKENS, TYPE } from '../../lib/designTokens'

const row = { fontSize: TYPE.sm, color: TOKENS.text[1] } as const

export function DeploysSummaryRows({ s }: { s: DeploysSummary }) {
  return (
    <>
      <div data-testid="deploys-served" style={row}>
        Serving: <Chip tone={s.servedSha ? 'neutral' : 'warning'}>{s.servedText}</Chip>{s.servedAt ? ` · activated ${readableTime(s.servedAt)}` : ''}
      </div>
      <div data-testid="deploys-last" style={row}>
        Poller, last decision: <Chip tone={s.lastTone}>{s.lastText}</Chip>{s.lastAt ? ` · ${readableTime(s.lastAt)}` : ''}
        {s.pollerVsServed === 'differs' ? ' · not the served release' : ''}{s.pollerBeforeServed ? ' · before it was activated' : ''}
      </div>
    </>
  )
}
