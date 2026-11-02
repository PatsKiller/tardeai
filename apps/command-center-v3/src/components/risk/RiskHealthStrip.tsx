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

export default function RiskHealthStrip({ heatPct, healthScore, healthStatus, unprotected, brokerStale, optionsAlerts }: Props) {
  // Health is higher-is-better. Its producer verdict owns the color; risk gauges retain their existing thresholds.
  const healthTone: Tone = healthStatus === 'healthy' ? 'success' : healthStatus === 'degraded' ? 'warning' : healthStatus === 'unhealthy' ? 'danger' : 'neutral'
  const items = [
    { label: 'Portfolio heat', value: heatPct, max: 15, threshold: 5, unit: '%' },
    { label: 'Health score', value: healthScore, max: 100, tone: healthTone, unit: '' },
    { label: 'Unprotected', value: unprotected, max: Math.max(unprotected ?? 0, 10), threshold: 3, unit: '' },
    { label: 'Broker stale', value: brokerStale, max: Math.max(brokerStale ?? 0, 5), threshold: 1, unit: '' },
    { label: 'Options alerts', value: optionsAlerts, max: Math.max(optionsAlerts ?? 0, 5), threshold: 1, unit: '' },
  ]
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
      gap: 10,
      padding: 12,
      background: 'var(--bg1)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      marginBottom: 14,
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
  )
}