/** Bloomberg Terminal tokens for Watchlist Security Card (v4 terminal build). */
import type { ActionUrgency, CardVerdict } from './watchlistCardAction'
import { verdictWord } from './watchlistCardTokens'

export const BB = {
  // Dark elevated card surfaces (redesign 2026-07-31)
  bg: '#0c1220',
  bgPanel: '#080e18',
  bgShift: '#121a2b',
  bgElevated: '#141e30',
  border: '#243044',
  borderHair: 'rgba(36, 48, 68, 0.95)',
  borderGlow: 'rgba(255, 176, 0, 0.22)',
  text0: '#f8fafc',
  text1: '#e8eef7',
  text2: '#c5d0e0',
  text3: '#8b9bb0',
  amber: '#ffb000',
  amberDim: 'rgba(255, 176, 0, 0.16)',
  amberFill: 'rgba(255, 176, 0, 0.22)',
  green: '#22c55e',
  greenDim: 'rgba(34, 197, 94, 0.14)',
  greenFill: 'rgba(34, 197, 94, 0.20)',
  red: '#ef4444',
  redDim: 'rgba(239, 68, 68, 0.14)',
  orange: '#f59e0b',
  mono: "'JetBrains Mono', ui-monospace, Consolas, monospace",
  shadow: '0 10px 32px rgba(0,0,0,.55)',
  radius: 10,
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
  kind: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success',
): Record<string, string | number> {
  const base = {
    fontSize: 11,
    fontWeight: 800,
    padding: '8px 14px',
    borderRadius: 6,
    cursor: 'pointer',
    letterSpacing: '.04em',
    textTransform: 'uppercase' as const,
    whiteSpace: 'nowrap' as const,
  }
  if (kind === 'primary') {
    return {
      ...base,
      fontSize: 12,
      padding: '10px 16px',
      border: `1px solid ${BB.amber}`,
      background: `linear-gradient(180deg, ${BB.amberFill}, ${BB.amberDim})`,
      color: BB.amber,
      boxShadow: `0 0 0 1px rgba(255,176,0,.08), 0 4px 14px rgba(255,176,0,.12)`,
    }
  }
  if (kind === 'success') {
    return {
      ...base,
      fontSize: 12,
      padding: '10px 16px',
      border: `1px solid ${BB.green}`,
      background: `linear-gradient(180deg, ${BB.greenFill}, ${BB.greenDim})`,
      color: BB.green,
      boxShadow: `0 4px 14px rgba(34,197,94,.12)`,
    }
  }
  if (kind === 'danger') {
    return { ...base, border: `1px solid ${BB.red}`, background: BB.redDim, color: BB.red }
  }
  if (kind === 'secondary') {
    return { ...base, border: `1px solid ${BB.border}`, background: BB.bgElevated, color: BB.text1 }
  }
  return { ...base, border: '1px solid transparent', background: 'transparent', color: BB.text3, padding: '6px 8px' }
}

export { verdictWord }