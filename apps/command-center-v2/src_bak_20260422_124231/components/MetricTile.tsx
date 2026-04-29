interface MetricTileProps {
  label: string
  value: string
  delta?: string
  deltaColor?: string
}

export default function MetricTile({ label, value, delta, deltaColor }: MetricTileProps) {
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius)',
      padding: '8px 12px',
      minWidth: 100,
      boxShadow: 'var(--shadow-sm)',
    }}>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 3, fontFamily: 'var(--sans)', textTransform: 'uppercase', letterSpacing: '.4px' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.2 }}>{value}</div>
      {delta && (
        <div style={{ fontSize: 10, color: deltaColor || 'var(--text2)', marginTop: 1 }}>{delta}</div>
      )}
    </div>
  )
}
