/** Bloomberg Terminal tokens for Watchlist Security Card (v4 terminal build). */
import type { ActionUrgency, CardVerdict } from './watchlistCardAction'
import { verdictWord } from './watchlistCardTokens'

export const BB = {
  bg: '#0f172a',
  bgPanel: '#0a0e1a',
  bgShift: '#111827',
  border: '#1e293b',
  borderHair: 'rgba(30, 41, 59, 0.9)',
  text0: '#f8fafc',
  text1: '#e2e8f0',
  text2: '#cbd5e1',
  text3: '#94a3b8',
  amber: '#ffb000',
  amberDim: 'rgba(255, 176, 0, 0.14)',
  green: '#22c55e',
  greenDim: 'rgba(34, 197, 94, 0.12)',
  red: '#ef4444',
  redDim: 'rgba(239, 68, 68, 0.12)',
  orange: '#f59e0b',
  mono: "'JetBrains Mono', ui-monospace, Consolas, monospace",
} as const

export const numStyle = { fontFamily: BB.mono, fontVariantNumeric: 'tabular-nums' } as const

export function terminalVerdictColor(v: CardVerdict, u: ActionUrgency): string {
  if (v === 'READY' || u === 'green') return BB.green
  if (v === 'SKIP') return BB.text3
  if (u === 'red' || v === 'FIX') return BB.red
  if (v === 'STALE' || v === 'WAIT' || v === 'BUILD' || u === 'amber') return BB.amber
  return BB.text2
}

export function terminalVerdictBg(v: CardVerdict, u: ActionUrgency): string {
  if (v === 'READY' || u === 'green') return BB.greenDim
  if (u === 'red' || v === 'FIX') return BB.redDim
  if (v === 'STALE' || v === 'WAIT' || v === 'BUILD' || u === 'amber') return BB.amberDim
  if (v === 'SKIP') return 'rgba(148, 163, 184, 0.06)'
  return 'rgba(148, 163, 184, 0.05)'
}

export function terminalRail(v: CardVerdict, u: ActionUrgency): string {
  return terminalVerdictColor(v, u)
}

export function terminalSigned(n: number): string {
  if (n > 0) return BB.green
  if (n < 0) return BB.red
  return BB.text3
}

export function terminalRrColor(rr: number): string {
  return rr >= 2 ? BB.green : rr >= 1.5 ? BB.amber : BB.red
}

export function terminalButton(
  kind: 'primary' | 'secondary' | 'ghost' | 'danger',
): Record<string, string | number> {
  const base = {
    fontSize: 10,
    fontWeight: 800,
    padding: '4px 10px',
    borderRadius: 2,
    cursor: 'pointer',
    letterSpacing: '.04em',
    textTransform: 'uppercase' as const,
    whiteSpace: 'nowrap' as const,
  }
  if (kind === 'primary') {
    return { ...base, border: `1px solid ${BB.amber}`, background: BB.amberDim, color: BB.amber }
  }
  if (kind === 'danger') {
    return { ...base, border: `1px solid ${BB.red}`, background: BB.redDim, color: BB.red }
  }
  if (kind === 'secondary') {
    return { ...base, border: `1px solid ${BB.border}`, background: BB.bgShift, color: BB.text2 }
  }
  return { ...base, border: '1px solid transparent', background: 'transparent', color: BB.text3, padding: '4px 6px' }
}

export { verdictWord }