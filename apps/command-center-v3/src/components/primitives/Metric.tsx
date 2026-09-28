/** Metric (PR2, 2026-09-27) — the one label/value cell. Every Metric carries a guideKey,
 *  so the reader can always ask what it is, why it matters, how to read it, and a benchmark.
 *  Replaces the local `Metric`s in OptionProposalCardV4, OptionPositionCardV4, DetailDrawer,
 *  cio/CioBrainPanel, RetirementHub, HeroMetricChip / CompactMetricRow and the symbol page `Fact`. */
import type { CSSProperties, MouseEvent, ReactNode } from 'react'
import { numStyle, TOKENS, TYPE, toneVars, type Tone } from '../../lib/designTokens'
import type { MetricGuideKey } from '../../lib/metricGuide'
import { MetricGuide } from './Tooltip'
import { Sparkline, TrendIndicator, type Trend } from './Charts'

export function Metric({ guideKey, label, value, tone, size = 'md', trend, spark, asOf, provenance, values, onClick, style }: {
  guideKey: MetricGuideKey
  label?: string
  value: ReactNode
  tone?: Tone
  size?: 'sm' | 'md' | 'hero'
  trend?: Trend
  spark?: number[]
  asOf?: string | null
  provenance?: string | null
  /** payload values for {placeholders} in the guide text */
  values?: Record<string, unknown>
  onClick?: (e: MouseEvent) => void
  style?: CSSProperties
}) {
  const valueSize = size === 'hero' ? TYPE.lg : size === 'sm' ? TYPE.base : TYPE.md
  const labelSize = size === 'hero' ? TYPE.sm : TYPE.xs
  const color = tone ? toneVars(tone).color : TOKENS.text[0]
  const meta = [asOf ? `as of ${asOf}` : null, provenance ? `source ${provenance}` : null].filter(Boolean).join(' · ')
  return (
    <MetricGuide guideKey={guideKey} values={values} placement={size === 'sm' ? 'bottom' : 'top'}>
      <div
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0, cursor: onClick ? 'pointer' : 'help', ...style }}
      >
        {label && (
          <span style={{ fontSize: labelSize, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: TOKENS.text[3], whiteSpace: 'nowrap' }}>
            {label}
          </span>
        )}
        <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ ...numStyle, fontSize: valueSize, fontWeight: 800, color, whiteSpace: 'nowrap' }}>{value}</span>
          {trend && <TrendIndicator {...trend} />}
          {spark && spark.length > 1 && <Sparkline data={spark} tone={tone} width={size === 'hero' ? 72 : 48} height={size === 'hero' ? 20 : 14} />}
        </span>
        {meta && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{meta}</span>}
      </div>
    </MetricGuide>
  )
}

/** A row of metrics with the house gap; wraps on narrow widths. */
export function MetricRow({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 18px', alignItems: 'flex-end', ...style }}>{children}</div>
}
