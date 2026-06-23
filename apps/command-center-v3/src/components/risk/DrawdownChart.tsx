import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

type Point = { date: string; value: number; drawdown?: number }

type Props = {
  data: Point[]
  title?: string
  height?: number
  valueKey?: 'drawdown' | 'value'
}

export default function DrawdownChart({ data, title = 'Underwater / drawdown', height = 160, valueKey = 'drawdown' }: Props) {
  if (!data.length) {
    return <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>No drawdown series</div>
  }
  const key = valueKey
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <defs>
            <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
          <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} width={40} />
          <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
          <ReferenceLine y={0} stroke="rgba(148,163,184,.35)" />
          <Area type="monotone" dataKey={key} stroke="#ef4444" fill="url(#ddFill)" strokeWidth={1.5} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}