import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import { TOKENS, toneVars, type Tone } from '../../lib/designTokens'

type Props = {
  value?: number | null
  max?: number
  label: string
  threshold?: number
  unit?: string
  height?: number
  /** A producer's qualitative verdict, when the quantity is not a high-is-bad risk measure. */
  tone?: Tone
}

export default function RiskGauge({ value, max = 15, label, threshold, unit = '%', height = 120, tone }: Props) {
  const measured = typeof value === 'number' && Number.isFinite(value)
  const v = measured ? Math.max(0, Math.min(max, value)) : 0
  const over = threshold != null && v > threshold
  const color = !measured ? TOKENS.text[2] : tone ? toneVars(tone).color
    : over ? TOKENS.danger : v > (threshold ?? max) * 0.6 ? TOKENS.warning : TOKENS.success
  return (
    <div role="group" aria-label={label} data-measured={measured} style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{label}</div>
      {measured ? <ResponsiveContainer width="100%" height={height}>
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
      </ResponsiveContainer> : <div aria-hidden="true" style={{ height }} />}
      <div data-testid="risk-gauge-value" style={{ fontSize: 22, fontWeight: 800, color, marginTop: -24 }}>
        {/* Home v2 D1: counts are integers (unit='') — '4.0 stops' reads as dev-speak */}
        {measured ? `${unit === '' ? String(Math.round(value)) : value.toFixed(1)}${unit}` : 'Unknown'}
      </div>
      {measured && threshold != null && (
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>threshold {threshold}{unit}</div>
      )}
    </div>
  )
}