import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import { zoneColor, type ThesisValidity } from '../../lib/brokerThesis'
import { thesisValidityScore } from '../../lib/riskMath'

type Props = { tv?: ThesisValidity | null; size?: 'sm' | 'md' }

export default function ThesisValidityGauge({ tv, size = 'sm' }: Props) {
  const score = thesisValidityScore(tv)
  const color = tv?.ok ? zoneColor(tv.zone_status, tv.zone_color) : '#94a3b8'
  const h = size === 'md' ? 72 : 56
  const r = size === 'md' ? 28 : 22
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: size === 'md' ? 120 : 90 }}>
      <div style={{ width: h, height: h, position: 'relative' }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={[{ value: score }, { value: 100 - score }]}
              cx="50%" cy="50%" innerRadius={r - 6} outerRadius={r}
              startAngle={90} endAngle={-270} dataKey="value" stroke="none"
            >
              <Cell fill={color} />
              <Cell fill="rgba(15,23,42,.6)" />
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: size === 'md' ? 13 : 11, fontWeight: 900, color,
        }}>{score}</div>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', lineHeight: 1.35 }}>
        <div style={{ fontWeight: 800, color, textTransform: 'uppercase' }}>
          {String(tv?.zone_status || 'n/a').replace(/_/g, ' ')}
        </div>
        {tv?.current_rr != null && <div>R:R {tv.current_rr}:1</div>}
        {tv?.price_stale && <div style={{ color: '#f59e0b' }}>stale price</div>}
      </div>
    </div>
  )
}