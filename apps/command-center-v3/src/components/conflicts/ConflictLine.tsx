import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import type { ConflictSection } from './ConflictSheet'
import { conflictSource, conflictTime } from '../../lib/watchConflictPresentation'

/** The engine supplies the headline (including null). This component never classifies inputs. */
export default function ConflictLine({section, onOpen}: {
  section: ConflictSection; onOpen: (key: string) => void
}) {
  const headline = section.headline
  const gap = section.gap ? <p role="status" data-testid="conflict-gap" style={{color: TOKENS.warning, fontSize: TYPE.base}}>Conflict check unavailable: {typeof section.gap.reason === 'string' ? section.gap.reason : 'engine result not supplied'}</p> : null
  if (!headline) return gap
  const first = section.findings[0]
  if (!first?.key) return <p role="status" style={{color: TOKENS.warning}}>Conflict check has no linked finding.</p>
  const kind = first.kind
  const color = kind === 'NEEDS_OPERATOR' || kind === 'DATA_ERROR' ? TOKENS.danger : TOKENS.warning
  return <>{gap}<button type="button" data-testid="conflict-line" onClick={() => onOpen(first.key)}
    style={{display: 'block', width: '100%', minHeight: 44, padding: '8px 10px', textAlign: 'left',
      border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], color,
      fontSize: TYPE.base, lineHeight: 1.5, cursor: 'pointer', overflowWrap: 'anywhere'}}>
      <span data-testid="conflict-headline">{headline}</span>
      {first.sides.map((side, index) => <span key={index} style={{display: 'block', color: TOKENS.text[2], fontSize: TYPE.sm}}>{conflictSource(side)} · {conflictTime(side.as_of)}</span>)}
    </button></>
}
