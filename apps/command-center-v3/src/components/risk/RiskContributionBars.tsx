import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { riskContributionRows } from '../../lib/riskMath'

const COLORS = ['#ef4444', '#f59e0b', '#60a5fa', '#a855f7', '#22c55e', '#06b6d4', '#fb923c', '#e879f9']

type Props = {
  positions: any[]
  title?: string
  mode?: 'risk' | 'exposure'
  max?: number
  height?: number
}

export default function RiskContributionBars({
  positions, title = 'Risk contribution', mode = 'risk', max = 10, height = 200,
}: Props) {
  const rows = riskContributionRows(positions, { max, useMaxLoss: mode === 'risk' })
  if (!rows.length) {
    return (
      <div style={{ fontSize: 10, color: 'var(--text3)', padding: 12, fontStyle: 'italic' }}>
        No {mode === 'risk' ? 'risk' : 'exposure'} data
      </div>
    )
  }
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 12, top: 4, bottom: 4 }}>
          <XAxis type="number" tick={{ fontSize: 9, fill: 'var(--text3)' }} tickFormatter={v => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} />
          <YAxis type="category" dataKey="name" width={44} tick={{ fontSize: 9, fill: 'var(--text1)', fontFamily: 'monospace' }} />
          <Tooltip
            contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
            formatter={(v: number) => [`$${Math.round(v).toLocaleString()}`, mode === 'risk' ? 'Max risk' : 'Exposure']}
            labelFormatter={l => String(l)}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {rows.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
        {mode === 'risk' ? 'Sorted by max_loss at stop' : 'Sorted by market value'} · top {rows.length} names
      </div>
    </div>
  )
}