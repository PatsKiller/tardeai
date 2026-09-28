/** Chip (PR2, 2026-09-27) — the one pill/badge/chip. Colour comes from `tone` only. */
import type { CSSProperties, MouseEvent, ReactNode } from 'react'
import { chipStyle, type Tone } from '../../lib/designTokens'
import { MetricGuide } from './Tooltip'
import type { MetricGuideKey } from '../../lib/metricGuide'

export function Chip({ tone = 'neutral', variant = 'soft', size = 'sm', icon, guideKey, title, onClick, style, children }: {
  tone?: Tone
  variant?: 'solid' | 'outline' | 'soft'
  size?: 'sm' | 'md'
  icon?: ReactNode
  guideKey?: MetricGuideKey
  title?: string
  onClick?: (e: MouseEvent) => void
  style?: CSSProperties
  children: ReactNode
}) {
  const body = (
    <span
      title={guideKey ? undefined : title}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      style={{ ...chipStyle(tone, variant, size), cursor: onClick ? 'pointer' : 'default', ...style }}
    >
      {icon}
      {children}
    </span>
  )
  return guideKey ? <MetricGuide guideKey={guideKey} phase="short">{body}</MetricGuide> : body
}

/** A row of chips with consistent gap. */
export function ChipRow({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, alignItems: 'center', ...style }}>{children}</span>
}
