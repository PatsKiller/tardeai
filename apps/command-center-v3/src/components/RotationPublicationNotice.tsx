import { rotationAvailability, rotationAvailabilityMessage, rotationReasonChips } from '../lib/rotationPublication'
import { fmtAsOf } from '../lib/asOfDisplay'
import { RADIUS, TYPE, toneVars } from '../lib/designTokens'

/**
 * Rotation publication notice: ONE line — reasons as chips, clocks in ET, a date-only source shown as a
 * date (P3, operator-approved mockup 2026-10-23). A withheld advisory used to be the largest text on the
 * page, with raw ISO stamps in microseconds and UTC. Amber when withheld, neutral when ready (Rotation →
 * Review renders it in both states). The sentences and the raw stamps stay in the tooltip.
 */
export default function RotationPublicationNotice({ summary, error }: { summary: unknown; error?: unknown }) {
  const observation = rotationAvailability(summary, error)
  const tone = toneVars(observation.ready ? 'neutral' : 'warning')
  const chips = rotationReasonChips(observation)
  const source = fmtAsOf(observation.sourceAsOf) ?? 'UNAVAILABLE'
  const generated = fmtAsOf(observation.generatedAt) ?? 'UNAVAILABLE'
  const checked = fmtAsOf(observation.validatedAt)
  const tip = [
    `Rotation advisory ${observation.status}.`,
    observation.ready ? null : `Advisory output withheld. ${rotationAvailabilityMessage(observation)}`,
    `Source as of: ${observation.sourceAsOf ?? 'UNAVAILABLE'}`,
    `Generated: ${observation.generatedAt ?? 'UNAVAILABLE'}`,
    observation.validatedAt ? `Checked at: ${observation.validatedAt}` : null,
    observation.reasons.length ? `Reason codes: ${observation.reasons.join(', ')}` : null,
  ].filter(Boolean).join('\n')
  return <div role="status" aria-label={`Rotation advisory ${observation.status}`} title={tip}
    data-testid="rotation-publication-notice" data-rotation-status={observation.status}
    style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px 8px', padding: '6px 10px', marginBottom: 12,
      fontSize: TYPE.base, color: observation.ready ? 'var(--text2)' : tone.color, background: tone.bg,
      border: `1px solid ${tone.border}`, borderRadius: RADIUS.md }}>
    {/* The status word stays visible: the retained-response contract (rotationRetainedError.browser.test.mjs)
        reads "Rotation advisory UNAVAILABLE|STALE" off the page to prove retained advice is withheld. */}
    <strong>Rotation advisory {observation.status}{observation.ready ? '' : ' · withheld'}</strong>
    {chips.map(c => <span key={c} data-testid="rotation-reason-chip"
      style={{ border: `1px solid ${tone.border}`, borderRadius: RADIUS.sm, padding: '0 5px', whiteSpace: 'nowrap' }}>{c}</span>)}
    <span style={{ color: 'var(--text3)' }}>
      Source as of {source}{checked ? ` · checked ${checked}` : ` · generated ${generated}`}
    </span>
  </div>
}
