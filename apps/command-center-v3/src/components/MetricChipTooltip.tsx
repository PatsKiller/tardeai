import { Fragment, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import {
  getOptionsMetricTooltip,
  type MetricChipItem,
  type OptionsMetricContext,
  type OptionsMetricKey,
  type OptionsMetricTooltip,
} from '../lib/optionsMetricTooltips'
import {
  metricChipHoverEnter,
  metricChipHoverLeave,
  metricChipMoreClick,
  metricChipTap,
  type MetricChipPhase,
} from '../lib/metricChipTooltipState'

const POPOVER: CSSProperties = {
  position: 'absolute',
  zIndex: 40,
  top: 'calc(100% + 4px)',
  left: 0,
  minWidth: 200,
  maxWidth: 280,
  padding: '8px 10px',
  borderRadius: 8,
  background: 'var(--bg1)',
  border: '1px solid rgba(96,165,250,.35)',
  boxShadow: '0 8px 24px rgba(0,0,0,.35)',
  fontSize: 10,
  lineHeight: 1.5,
  color: 'var(--text2)',
  fontWeight: 500,
}

const INFO: CSSProperties = {
  fontSize: 9,
  opacity: 0.65,
  marginLeft: 2,
  lineHeight: 1,
  userSelect: 'none',
}

function TooltipBody({ tip, phase }: { tip: OptionsMetricTooltip; phase: MetricChipPhase }) {
  if (phase === 'closed') return null
  return (
    <>
      <div style={{ color: 'var(--text1)', fontWeight: 700 }}>{tip.short}</div>
      {phase === 'more' && (
        <div style={{ marginTop: 6 }}>
          <div>{tip.more}</div>
          {tip.watch && (
            <div style={{ marginTop: 6, color: '#93c5fd' }}>
              <b>Watch:</b> {tip.watch}
            </div>
          )}
          {tip.warning && (
            <div style={{ marginTop: 4, color: '#f59e0b', fontWeight: 700 }}>{tip.warning}</div>
          )}
        </div>
      )}
    </>
  )
}

export function MetricChipTooltip({
  metricKey,
  label,
  context,
  tooltip: tooltipOverride,
  style,
  valueStyle,
  showIcon = true,
}: {
  metricKey?: OptionsMetricKey | string
  label: ReactNode
  context?: OptionsMetricContext
  tooltip?: OptionsMetricTooltip
  style?: CSSProperties
  valueStyle?: CSSProperties
  showIcon?: boolean
}) {
  const tip = tooltipOverride ?? getOptionsMetricTooltip(metricKey || 'edge', context)
  const [phase, setPhase] = useState<MetricChipPhase>('closed')
  const [coarse, setCoarse] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const mq = window.matchMedia('(hover: none), (pointer: coarse)')
    const apply = () => setCoarse(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (phase === 'closed') return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPhase('closed')
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [phase])

  return (
    <span
      ref={rootRef}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'baseline', ...style }}
      onMouseEnter={() => { if (!coarse) setPhase(p => metricChipHoverEnter(p)) }}
      onMouseLeave={() => { if (!coarse) setPhase(p => metricChipHoverLeave(p)) }}
      onClick={e => {
        e.stopPropagation()
        setPhase(p => metricChipTap(p, coarse))
      }}
    >
      <span style={{ cursor: 'help', ...valueStyle }}>{label}</span>
      {showIcon && <span style={INFO} aria-hidden>ⓘ</span>}
      {phase !== 'closed' && (
        <div role="tooltip" style={POPOVER} onClick={e => e.stopPropagation()}>
          <TooltipBody tip={tip} phase={phase} />
          {phase === 'short' && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); setPhase(metricChipMoreClick()) }}
              style={{
                marginTop: 6,
                fontSize: 9,
                fontWeight: 800,
                color: '#60a5fa',
                background: 'none',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
              }}
            >
              More →
            </button>
          )}
        </div>
      )}
    </span>
  )
}

export function CompactMetricRow({
  items,
  context,
  style,
  separator = ' · ',
}: {
  items: MetricChipItem[]
  context?: OptionsMetricContext
  style?: CSSProperties
  separator?: string
}) {
  if (!items.length) return null
  return (
    <div style={{ display: 'inline', lineHeight: 1.55, ...style }}>
      {items.map((item, i) => (
        <Fragment key={`${item.key}-${i}`}>
          {i > 0 && <span style={{ color: 'var(--text3)', margin: '0 2px' }}>{separator}</span>}
          <MetricChipTooltip metricKey={item.key} label={item.label} context={context} />
        </Fragment>
      ))}
    </div>
  )
}

/** Hero-row metric: label + value with novice tooltip on the whole chip. */
export function HeroMetricChip({
  metricKey,
  label,
  value,
  context,
  color,
}: {
  metricKey: OptionsMetricKey
  label: string
  value: ReactNode
  context?: OptionsMetricContext
  color?: string
}) {
  return (
    <MetricChipTooltip
      metricKey={metricKey}
      label={(
        <>
          <span style={{ color: 'var(--text3)', fontWeight: 700 }}>{label} </span>
          <span style={{ fontWeight: 700, color }}>{value}</span>
        </>
      )}
      context={context}
      showIcon
    />
  )
}