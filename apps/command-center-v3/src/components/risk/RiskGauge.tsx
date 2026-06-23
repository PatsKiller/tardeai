import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

type Props = {
  value: number
  max?: number
  label: string
  threshold?: number
  unit?: string
  height?: number
}

export default function RiskGauge({ value, max = 15, label, threshold, unit = '%', height = 120 }: Props) {
  const v = Math.max(0, Math.min(max, value))
  const over = threshold != null && v > threshold
  const color = over ? '#ef4444' : v > (threshold ?? max) * 0.6 ? '#f59e0b' : '#22c55e'
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{label}</div>
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={[{ value: v }, { value: Math.max(0, max - v) }]}
            cx="50%" cy="88%" startAngle={180} endAngle={0}
            innerRadius={48} outerRadius={62} dataKey="value" stroke="none"
          >
            <Cell fill={color} />
            <Cell fill="var(--bg2)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 22, fontWeight: 800, color, marginTop: -24 }}>
        {typeof value === 'number' ? value.toFixed(1) : '—'}{unit}
      </div>
      {threshold != null && (
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>threshold {threshold}{unit}</div>
      )}
    </div>
  )
}