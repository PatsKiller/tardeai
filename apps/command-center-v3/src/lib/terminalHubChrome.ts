import type { CSSProperties } from 'react'
import { BB } from './watchlistTerminalTokens'

/** Hub title + tab chrome — Bloomberg terminal (always on; no legacy branch). */
export function hubTitle(color?: string): CSSProperties {
  return { fontSize: 16, fontWeight: 800, color: color ?? BB.text0, letterSpacing: '.02em' }
}

export function hubSubtitle(_terminal = true): CSSProperties {
  return {
    fontSize: 10,
    color: BB.text3,
    marginTop: 2,
    letterSpacing: '.04em',
  }
}

export function hubTab(active: boolean, _terminal = true): CSSProperties {
  return {
    padding: '3px 10px',
    fontSize: 10,
    fontWeight: active ? 800 : 600,
    borderRadius: 2,
    border: `1px solid ${active ? BB.amber : BB.border}`,
    cursor: 'pointer',
    background: active ? BB.amberDim : BB.bgShift,
    color: active ? BB.amber : BB.text3,
    letterSpacing: '.06em',
    textTransform: 'uppercase',
  }
}

export function hubPanel(_terminal = true): CSSProperties {
  return { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '6px 10px' }
}

export function hubStrip(_terminal = true): CSSProperties {
  return {
    background: BB.bgShift,
    border: `1px solid ${BB.border}`,
    borderRadius: 2,
    padding: '5px 10px',
    fontSize: 10,
    color: BB.text2,
    lineHeight: 1.4,
  }
}

export function hubFilterSelect(_terminal = true): CSSProperties {
  return {
    fontSize: 10,
    padding: '3px 8px',
    background: BB.bgShift,
    border: `1px solid ${BB.border}`,
    borderRadius: 2,
    color: BB.text0,
    fontWeight: 600,
  }
}

export function hubKpiChip(active: boolean, _terminal = true): CSSProperties {
  return {
    fontSize: 10,
    fontWeight: 800,
    padding: '2px 8px',
    borderRadius: 2,
    border: `1px solid ${active ? BB.amber : BB.border}`,
    background: active ? BB.amberDim : 'transparent',
    color: active ? BB.amber : BB.text3,
    cursor: 'pointer',
    letterSpacing: '.04em',
  }
}