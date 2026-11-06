import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import type { ConflictSection } from './ConflictSheet'
import { conflictSource, conflictTime } from '../../lib/watchConflictPresentation'
import { plainConflictGap } from '../../lib/auditPlainLanguage'

/**
 * The gap notice every conflict surface shares (FQ-061). The sentence says what could not be checked
 * and how that limits the figures on screen; the producer's raw reason stays in a closed
 * technical-detail toggle instead of being the operator's only explanation.
 */
export function ConflictGap({ reason }: { reason?: unknown }) {
  const gap = plainConflictGap(reason)
  return <div role="status" data-testid="conflict-gap" style={{ color: TOKENS.warning, fontSize: TYPE.base, lineHeight: 1.5 }}>
    <strong>Conflict check unavailable:</strong> <span>{gap.text}</span>
    {gap.raw ? <details style={{ marginTop: 2, color: TOKENS.text[3], fontSize: TYPE.sm }}>
      <summary style={{ cursor: 'pointer', width: 'fit-content' }}>technical detail</summary>
      <span style={{ fontFamily: "'JetBrains Mono', ui-monospace, Consolas, monospace", overflowWrap: 'anywhere' }}>{gap.raw}</span>
    </details> : null}
  </div>
}

/** The engine supplies the headline (including null). This component never classifies inputs. */
export default function ConflictLine({section, onOpen}: {
  section: ConflictSection; onOpen: (key: string) => void
}) {
  const headline = section.headline
  const gap = section.gap ? <ConflictGap reason={section.gap.reason} /> : null
  // A truncation is not an outage: the check ran and returned a bounded page. Say how much is shown.
  const truncated = section.truncated && section.truncated.total > section.truncated.shown
    ? <p role="status" data-testid="conflict-truncated" style={{color: TOKENS.text[2], fontSize: TYPE.sm}}>Showing first {section.truncated.shown} of {section.truncated.total} conflict records.</p>
    : null
  if (!headline) return <>{gap}{truncated}</>
  const first = section.findings[0]
  if (!first?.key) return <p role="status" style={{color: TOKENS.warning}}>Conflict check has no linked finding.</p>
  const kind = first.kind
  const color = kind === 'NEEDS_OPERATOR' || kind === 'DATA_ERROR' ? TOKENS.danger : TOKENS.warning
  return <>{gap}{truncated}<button type="button" data-testid="conflict-line" onClick={() => onOpen(first.key)}
    style={{display: 'block', width: '100%', minHeight: 44, padding: '8px 10px', textAlign: 'left',
      border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], color,
      fontSize: TYPE.base, lineHeight: 1.5, cursor: 'pointer', overflowWrap: 'anywhere'}}>
      <span data-testid="conflict-headline">{headline}</span>
      {first.sides.map((side, index) => <span key={index} style={{display: 'block', color: TOKENS.text[2], fontSize: TYPE.sm}}>{conflictSource(side)} · {conflictTime(side.as_of)}</span>)}
    </button></>
}
