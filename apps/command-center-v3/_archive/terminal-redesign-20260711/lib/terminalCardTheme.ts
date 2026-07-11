import type { CSSProperties } from 'react'
import { WL } from './watchlistCardTokens'
import { BB } from './watchlistTerminalTokens'

/** Card shell + module rhythm — terminal vs legacy v4. */
export function cardShell(rail: string, terminal: boolean): CSSProperties {
  if (terminal) {
    return {
      background: BB.bg,
      border: `1px solid ${BB.border}`,
      borderLeft: `3px solid ${rail}`,
      borderRadius: 2,
      cursor: 'pointer',
      minWidth: 0,
      width: '100%',
      boxSizing: 'border-box',
      overflow: 'hidden',
      color: BB.text1,
      fontSize: 10,
      lineHeight: 1.35,
    }
  }
  return {
    background: WL.surface.card,
    border: `1px solid ${WL.surface.edge}`,
    borderLeft: `3px solid ${rail}`,
    borderRadius: WL.card.radius,
    cursor: 'pointer',
    boxShadow: WL.card.shadow,
    minWidth: 0,
    width: '100%',
    boxSizing: 'border-box',
    overflow: 'hidden',
    color: WL.text.primary,
  }
}

export function modRow(terminal: boolean): CSSProperties {
  return terminal
    ? { padding: '6px 10px', borderTop: `1px solid ${BB.border}` }
    : { padding: '11px 18px', borderTop: `1px solid ${WL.surface.divider}` }
}

export function modLabel(terminal: boolean): CSSProperties {
  return terminal
    ? { fontSize: 8, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: BB.text3, marginBottom: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }
    : { fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: WL.text.dim, marginBottom: 7, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }
}

export function statusStrip(bg: string, terminal: boolean): CSSProperties {
  return terminal
    ? { display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderBottom: `1px solid ${BB.border}`, background: bg, flexWrap: 'wrap' }
    : { background: bg, borderTop: `1px solid ${BB.border}`, borderBottom: `1px solid ${BB.border}`, padding: '11px 18px 10px', display: 'flex', flexDirection: 'column', gap: 7 }
}

export function ctxLine(terminal: boolean): CSSProperties {
  return terminal
    ? { fontSize: 9.5, color: BB.text2, lineHeight: 1.4 }
    : { fontSize: 11, color: WL.text.secondary, lineHeight: 1.55 }
}

export function ctxKey(terminal: boolean): CSSProperties {
  return terminal
    ? { color: BB.text3, fontWeight: 800 }
    : { color: WL.text.dim, fontWeight: 700 }
}

export function gridClass(terminal: boolean): string {
  return terminal ? 'wlc-term-grid' : 'wlc-grid'
}

export function gridCellClass(terminal: boolean): string {
  return terminal ? 'wlc-term-cell' : 'wlc-cell'
}