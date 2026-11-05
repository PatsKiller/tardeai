/** Chip (PR2, 2026-09-27) — the one pill/badge/chip. Colour comes from `tone` only. */
import type { CSSProperties, KeyboardEvent, MouseEvent, ReactNode } from 'react'
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
      // cx-openai-3's F7 at 25b3348e: the chip announced itself as a button and then ignored the keyboard. Enter and
      // Space do what a pointer does, which is what role="button" promises.
      onKeyDown={onClick ? (e: KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e as unknown as MouseEvent) }
      } : undefined}
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
