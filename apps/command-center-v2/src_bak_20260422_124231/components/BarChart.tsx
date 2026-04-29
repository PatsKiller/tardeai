interface BarChartProps {
  data: { label: string; value: number; color?: string }[]
  height?: number
}

export default function BarChart({ data, height = 100 }: BarChartProps) {
  const max = Math.max(...data.map(d => Math.abs(d.value)), 0.01)

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height, padding: '0 2px' }}>
      {data.map((d, i) => {
        const pct = (Math.abs(d.value) / max) * 100
        const isNeg = d.value < 0
        const color = d.color || (isNeg ? 'var(--red)' : 'var(--green)')
        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            <div style={{ fontSize: 9, color: isNeg ? 'var(--red)' : 'var(--green)', fontWeight: 600, whiteSpace: 'nowrap' }}>
              {d.value >= 0 ? '+' : ''}{d.value.toFixed(1)}%
            </div>
            <div style={{
              width: '100%',
              maxWidth: 28,
              height: `${Math.max(pct, 6)}%`,
              background: `linear-gradient(180deg, ${color}, color-mix(in srgb, ${color} 40%, transparent))`,
              borderRadius: '2px 2px 0 0',
              minHeight: 3,
              transition: 'height 300ms ease',
            }} />
            <div style={{ fontSize: 8, color: 'var(--text3)', fontWeight: 600 }}>{d.label}</div>
          </div>
        )
      })}
    </div>
  )
}
