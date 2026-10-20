import { rotationAvailability, rotationAvailabilityMessage } from '../lib/rotationPublication'
import { RADIUS } from '../lib/designTokens'

export default function RotationPublicationNotice({ summary, error }: { summary: unknown; error?: unknown }) {
  const observation = rotationAvailability(summary, error)
  return <div role="status" style={{ padding: 14, border: '1px solid var(--border)', borderRadius: RADIUS.md, color: 'var(--text2)', marginBottom: 12 }}>
    <strong>Rotation advisory {observation.status}</strong>
    {!observation.ready && <div>Advisory output withheld. {rotationAvailabilityMessage(observation)}</div>}
    <div style={{ marginTop: 5, fontSize: 11 }}>
      Source as of: {observation.sourceAsOf ?? 'UNAVAILABLE'} · Generated: {observation.generatedAt ?? 'UNAVAILABLE'}
    </div>
    {observation.validatedAt && <div style={{ fontSize: 11 }}>Checked at: {observation.validatedAt}</div>}
  </div>
}
