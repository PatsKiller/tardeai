/** Chart primitives (PR2, 2026-09-27): Sparkline, TrendIndicator, interactive Legend.
 *  Colours from CHART_HEX per resolved theme (chart libraries cannot read CSS vars). */
import type { CSSProperties } from 'react'
import { LineChart, Line, ResponsiveContainer, ReferenceLine } from 'recharts'
import { CHART_HEX, TOKENS, TYPE, type Tone } from '../../lib/designTokens'
import { useTheme } from '../../hooks/useTheme'
import { Chip } from './Chip'

export type Trend = { dir: 'up' | 'down' | 'flat'; delta?: string; goodWhen?: 'up' | 'down' }

/** Arrow + delta, coloured by whether the direction is good for the reader. */
export function TrendIndicator({ dir, delta, goodWhen = 'up' }: Trend) {
  const good = dir === 'flat' ? null : (dir === goodWhen)
  const color = good === null ? TOKENS.text[3] : good ? TOKENS.success : TOKENS.danger
  const glyph = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '▬'
  return (
    <span aria-label={`trend ${dir}${delta ? ` ${delta}` : ''}`} style={{ fontSize: TYPE.xs, fontWeight: 800, color, whiteSpace: 'nowrap' }}>
      {glyph}{delta ? ` ${delta}` : ''}
    </span>
  )
}

/** Axis-less line for a metric's recent history. `baseline` draws a dotted reference. */
export function Sparkline({ data, tone, width = 64, height = 18, baseline, style }: {
  data: number[]
  tone?: Tone
  width?: number
  height?: number
  baseline?: number
  style?: CSSProperties
}) {
  const [, , theme] = useTheme()
  const hex = CHART_HEX[theme]
  const stroke = tone === 'success' ? hex.success : tone === 'danger' ? hex.danger : tone === 'warning' ? hex.warning : hex.series[0]
  const rows = data.map((v, i) => ({ i, v }))
  return (
    <span aria-hidden style={{ display: 'inline-block', width, height, verticalAlign: 'middle', ...style }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 2, right: 1, bottom: 2, left: 1 }}>
          {baseline !== undefined && <ReferenceLine y={baseline} stroke={hex.grid} strokeDasharray="2 2" />}
          <Line type="monotone" dataKey="v" stroke={stroke} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </span>
  )
}

/** Interactive legend: click a series to hide/show it. Caller keeps `hidden` in state. */
export function Legend({ series, hidden, onToggle, style }: {
  series: Array<{ key: string; label: string; tone?: Tone; colorIndex?: number }>
  hidden: Set<string>
  onToggle: (key: string) => void
  style?: CSSProperties
}) {
  return (
    <div role="group" aria-label="legend" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, ...style }}>
      {series.map(s => (
        <Chip key={s.key} tone={s.tone || 'neutral'} variant={hidden.has(s.key) ? 'outline' : 'soft'} onClick={() => onToggle(s.key)}
          style={hidden.has(s.key) ? { opacity: 0.55, textDecoration: 'line-through' } : undefined}>
          {s.label}
        </Chip>
      ))}
    </div>
  )
}
