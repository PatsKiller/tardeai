import type { CSSProperties } from 'react'
import { BB } from './watchlistTerminalTokens'

/** Hub title + tab chrome — Bloomberg when terminal UI is on. */
export function hubTitle(color?: string): CSSProperties {
  return { fontSize: 16, fontWeight: 800, color: color ?? BB.text0, letterSpacing: '.02em' }
}

export function hubSubtitle(terminal: boolean): CSSProperties {
  return {
    fontSize: terminal ? 9 : 11,
    color: terminal ? BB.text3 : 'var(--text3)',
    marginTop: 2,
    letterSpacing: terminal ? '.04em' : undefined,
  }
}

export function hubTab(active: boolean, terminal: boolean): CSSProperties {
  if (terminal) {
    return {
      padding: '3px 10px',
      fontSize: 9,
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
  return {
    padding: '4px 12px',
    fontSize: 11,
    borderRadius: 5,
    border: 'none',
    cursor: 'pointer',
    background: active ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
    color: active ? '#60a5fa' : 'var(--text3)',
    fontWeight: active ? 700 : 400,
  }
}

export function hubPanel(terminal: boolean): CSSProperties {
  if (terminal) {
    return { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '6px 10px' }
  }
  return { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }
}

export function hubStrip(terminal: boolean): CSSProperties {
  if (terminal) {
    return {
      background: BB.bgShift,
      border: `1px solid ${BB.border}`,
      borderRadius: 2,
      padding: '5px 10px',
      fontSize: 9,
      color: BB.text2,
      lineHeight: 1.4,
    }
  }
  return {
    background: 'linear-gradient(90deg, rgba(96,165,250,.14), rgba(96,165,250,.04))',
    border: '1px solid rgba(96,165,250,.35)',
    borderRadius: 10,
    padding: '10px 14px',
  }
}

export function hubFilterSelect(terminal: boolean): CSSProperties {
  if (terminal) {
    return {
      fontSize: 9,
      padding: '3px 8px',
      background: BB.bgShift,
      border: `1px solid ${BB.border}`,
      borderRadius: 2,
      color: BB.text0,
      fontWeight: 600,
    }
  }
  return {
    fontSize: 11,
    padding: '6px 9px',
    background: 'var(--bg2)',
    border: '1px solid var(--border)',
    borderRadius: 6,
    color: '#f8fafc',
  }
}

export function hubKpiChip(active: boolean, terminal: boolean): CSSProperties {
  if (terminal) {
    return {
      fontSize: 9,
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
  return {
    fontSize: 10,
    fontWeight: 700,
    padding: '3px 8px',
    borderRadius: 5,
    border: `1px solid ${active ? 'rgba(96,165,250,.4)' : 'var(--border)'}`,
    background: active ? 'rgba(96,165,250,.12)' : 'var(--bg2)',
    color: active ? '#60a5fa' : 'var(--text3)',
    cursor: 'pointer',
  }
}