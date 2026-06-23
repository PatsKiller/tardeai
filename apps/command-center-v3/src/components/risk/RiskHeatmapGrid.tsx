import { heatColor } from '../../lib/riskMath'

type Cell = { key: string; label: string; value: number; sub?: string }

type Props = {
  cells: Cell[]
  title?: string
  valueLabel?: string
  columns?: number
}

export default function RiskHeatmapGrid({ cells, title = 'Risk heatmap', valueLabel = 'risk', columns = 4 }: Props) {
  if (!cells.length) {
    return <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>No heatmap data</div>
  }
  const max = Math.max(...cells.map(c => c.value), 0.01)
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{title}</div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gap: 6,
      }}>
        {cells.map(c => (
          <div
            key={c.key}
            title={`${c.label}: ${c.value.toLocaleString()} ${valueLabel}${c.sub ? ` · ${c.sub}` : ''}`}
            style={{
              padding: '8px 10px',
              borderRadius: 8,
              background: heatColor(c.value, max),
              border: '1px solid rgba(148,163,184,.2)',
              minHeight: 52,
            }}
          >
            <div style={{ fontSize: 10, fontWeight: 800, fontFamily: 'monospace', color: 'var(--text0)' }}>{c.label}</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginTop: 2 }}>
              {c.value >= 1000 ? `$${(c.value / 1000).toFixed(1)}k` : `$${Math.round(c.value)}`}
            </div>
            {c.sub && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{c.sub}</div>}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, fontSize: 8, color: 'var(--text3)' }}>
        <span><span style={{ color: '#22c55e' }}>■</span> low</span>
        <span><span style={{ color: '#f59e0b' }}>■</span> medium</span>
        <span><span style={{ color: '#ef4444' }}>■</span> high {valueLabel}</span>
      </div>
    </div>
  )
}