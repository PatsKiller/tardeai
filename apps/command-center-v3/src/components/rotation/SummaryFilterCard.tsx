/**
 * Rotation summary filter tile — a real control, not a clickable div (RR-009).
 *
 * Why (2026-11-14, sprint 8H-2): the six summary counters were `<div onClick title=…>` with
 * `cursor:pointer`. No role, no keyboard path, no accessible name, no selected state — a keyboard
 * or screen-reader user could not operate the filter at all, and the selected filter was conveyed
 * only by a border colour. A counter that filters a queue is a button: `aria-pressed` carries the
 * selected state, Enter/Space work for free, and focus is visible.
 *
 * Non-clickable tiles (a count with no queue behind it) stay static text — never a dead button.
 * The page's card style is passed in so the visual treatment is unchanged.
 */
import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { TYPE } from '../../lib/designTokens'

export type SummaryFilterCardProps = {
  label: string
  value: ReactNode
  color?: string
  onClick?: () => void
  active?: boolean
  /** Base card style from the page; the tile merges its own layout on top. */
  style?: CSSProperties
  /** Optional explanation of what the count means and where it comes from. */
  hint?: string
}

export function SummaryFilterCard({ label, value, color, onClick, active, style, hint }: SummaryFilterCardProps) {
  const [focused, setFocused] = useState(false)
  const accent = color ?? BB.blue
  const clickable = typeof onClick === 'function'
  const base: CSSProperties = {
    ...style,
    textAlign: 'center',
    padding: '14px 10px',
    borderColor: active ? accent : 'var(--border)',
    boxShadow: active ? `0 0 0 1px ${accent}` : undefined,
    transition: 'border-color .15s',
    cursor: clickable ? 'pointer' : 'default',
    // Button defaults would otherwise override the tile: inherit the page's typography and let the
    // passed card style keep its background.
    font: 'inherit',
    color: 'inherit',
    appearance: 'none',
    width: '100%',
    outline: focused && clickable ? `2px solid ${accent}` : 'none',
    outlineOffset: 2,
  }
  const body = (
    <>
      <div style={{ fontSize: TYPE.xl, fontWeight: 800, color: color ?? 'var(--text0)' }}>{value}</div>
      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>
        {label}{clickable && <span aria-hidden="true" style={{ color: accent }}> ▾</span>}
      </div>
      {hint ? <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 3 }}>{hint}</div> : null}
    </>
  )

  if (!clickable) {
    return (
      <div data-testid="rotation-summary-card" data-state={active ? 'selected' : 'idle'} style={base}>
        {body}
      </div>
    )
  }

  return (
    <button
      type="button"
      data-testid="rotation-summary-card"
      data-filter={label}
      aria-pressed={!!active}
      aria-label={`${label}: ${typeof value === 'number' || typeof value === 'string' ? value : 'filter'}${active ? ', filter on' : ''}`}
      title={hint ?? `Show ${label}`}
      onClick={onClick}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={base}
    >
      {body}
    </button>
  )
}
