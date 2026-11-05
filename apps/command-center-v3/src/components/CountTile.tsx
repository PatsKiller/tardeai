import type { CSSProperties, ReactNode } from 'react'
import { Tooltip } from './primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import { countText, type MeasuredCount } from '../lib/measuredCount'

/**
 * One count tile. A count that cannot be measured renders "—" plus its reason, never 0, and never in the
 * tile's alarm/success tone (a gap is not a result). A floor ("2+") keeps its tone and says why it is a floor.
 */
export default function CountTile({ label, count, tone = 'neutral', tip, testId, size = 'xl', style }: {
  label: string; count: MeasuredCount; tone?: Tone; tip?: ReactNode; testId?: string; size?: 'lg' | 'xl'; style?: CSSProperties
}) {
  const gap = count.value === null
  const t = toneVars(gap ? 'neutral' : tone)
  const body = <div data-testid={testId} data-measured={gap ? 'false' : 'true'} style={{
    background: t.bg, border: `1px ${gap ? 'dashed' : 'solid'} ${t.border}`, borderRadius: RADIUS.md,
    padding: '8px 12px', minWidth: 0, cursor: tip ? 'help' : undefined, ...style,
  }}>
    <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{label}</div>
    <strong aria-label={gap ? `${label}: not measured` : undefined} style={{ fontFamily: FONT.mono, fontSize: TYPE[size], color: gap ? TOKENS.text[2] : t.color }}>{countText(count)}</strong>
    {count.reason && <div data-testid={testId ? `${testId}-reason` : undefined} style={{ marginTop: 4, fontSize: TYPE.sm, color: gap ? TOKENS.warning : TOKENS.text[2], overflowWrap: 'anywhere' }}>{count.reason}</div>}
  </div>
  return tip ? <Tooltip content={tip} as="div">{body}</Tooltip> : body
}
