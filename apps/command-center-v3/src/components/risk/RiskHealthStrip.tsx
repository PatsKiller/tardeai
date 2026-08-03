import RiskGauge from './RiskGauge'

type Props = {
  heatPct?: number
  healthScore?: number
  unprotected?: number
  brokerStale?: number
  optionsAlerts?: number
}

export default function RiskHealthStrip({ heatPct = 0, healthScore, unprotected = 0, brokerStale = 0, optionsAlerts = 0 }: Props) {
  const items = [
    { label: 'Portfolio heat', value: heatPct, max: 15, threshold: 5, unit: '%' },
    { label: 'Health score (0–100)', value: healthScore ?? 0, max: 100, threshold: 65, unit: '' },
    { label: 'Unprotected', value: unprotected, max: Math.max(unprotected, 10), threshold: 3, unit: '' },
    { label: 'Broker stale', value: brokerStale, max: Math.max(brokerStale, 5), threshold: 1, unit: '' },
    { label: 'Options alerts', value: optionsAlerts, max: Math.max(optionsAlerts, 5), threshold: 1, unit: '' },
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
          unit={it.unit}
          height={90}
        />
      ))}
    </div>
  )
}