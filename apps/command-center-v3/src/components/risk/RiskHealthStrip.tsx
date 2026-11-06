import RiskGauge from './RiskGauge'
import type { Tone } from '../../lib/designTokens'

type Props = {
  heatPct?: number | null
  healthScore?: number | null
  healthStatus?: string | null
  unprotected?: number | null
  brokerStale?: number | null
  optionsAlerts?: number | null
}

export function healthVerdictTone(status: unknown): Tone {
  return status === 'healthy' ? 'success' : status === 'degraded' ? 'warning' : status === 'unhealthy' ? 'danger' : 'neutral'
}

export default function RiskHealthStrip({ heatPct, healthScore, healthStatus, unprotected, brokerStale, optionsAlerts }: Props) {
  // Health is higher-is-better. Its producer verdict owns the color; risk gauges retain their existing thresholds.
  const healthTone = healthVerdictTone(healthStatus)
  const items = [
    { label: 'Portfolio heat', value: heatPct, max: 15, threshold: 5, unit: '%' },
    { label: 'Health score', value: healthScore, max: 100, tone: healthTone, unit: '' },
    { label: 'Unprotected', value: unprotected, max: Math.max(unprotected ?? 0, 10), threshold: 3, unit: '' },
    { label: 'Broker stale', value: brokerStale, max: Math.max(brokerStale ?? 0, 5), threshold: 1, unit: '' },
    { label: 'Options alerts', value: optionsAlerts, max: Math.max(optionsAlerts ?? 0, 5), threshold: 1, unit: '' },
  ]
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(min(120px, 100%), 1fr))',
        gap: 10,
        padding: 12,
        background: 'var(--bg1)',
        border: '1px solid var(--border)',
        borderRadius: 10,
      }}>
        {items.map(it => (
          <RiskGauge
            key={it.label}
            label={it.label}
            value={it.value}
            max={it.max}
            threshold={it.threshold}
            tone={it.tone}
            unit={it.unit}
            height={90}
          />
        ))}
      </div>
      {/* FQ-036: the scope of the score beside the Unprotected gauge. The score grades the health
          agent's own checks; it never counts stop coverage. Without this line a green Health score
          beside a red Unprotected gauge reads as a contradiction. */}
      <p data-testid="risk-health-scope" style={{
        margin: '6px 2px 0', fontSize: 10.5, lineHeight: 1.45, color: 'var(--text3)',
      }}>
        <b style={{ color: 'var(--text2)' }}>What the health score covers:</b> the health agent’s own
        checks — data freshness, execution, intelligence and retirement. It does not count whether a
        position has a stop. <b style={{ color: 'var(--text2)' }}>Unprotected</b> counts open positions
        with no stop recorded, and is not part of the score; a green score with a red Unprotected gauge
        means the monitored checks pass while stops are still missing.
      </p>
    </div>
  )
}