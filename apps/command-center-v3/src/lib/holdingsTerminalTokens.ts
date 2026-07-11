/** Bloomberg Terminal–inspired tokens for Portfolio Holdings table (v2). */
export const HOLDINGS_CVD_KEY = 'cc-v3-holdings-cvd'

export const BB = {
  bg: '#0a0e1a',
  bgRow: '#0f172a',
  bgRowAlt: '#111827',
  bgRowHover: 'rgba(255, 176, 0, 0.08)',
  bgRowFocus: 'rgba(255, 176, 0, 0.14)',
  border: '#1e293b',
  borderSubtle: '#151c2e',
  text0: '#f8fafc',
  text1: '#e2e8f0',
  text2: '#cbd5e1',
  text3: '#94a3b8',
  amber: '#ffb000',
  amberAlt: '#ffa028',
  amberDim: 'rgba(255, 176, 0, 0.14)',
  green: '#22c55e',
  greenDim: 'rgba(34, 197, 94, 0.12)',
  red: '#ef4444',
  redDim: 'rgba(239, 68, 68, 0.12)',
  blue: '#3b82f6',
  blueDim: 'rgba(59, 130, 246, 0.12)',
  mono: "'JetBrains Mono', 'Consolas', monospace",
  rowH: 36,
  fontXs: 9,
  fontSm: 10,
  fontMd: 11,
} as const

export type StopStatusTone = 'stable' | 'concern' | 'action'
export type HoldingsCvdMode = 'default' | 'cvd'

export function getHoldingsCvdMode(): HoldingsCvdMode {
  try {
    return localStorage.getItem(HOLDINGS_CVD_KEY) === 'cvd' ? 'cvd' : 'default'
  } catch {
    return 'default'
  }
}

/** Positive / up / gain — green in default scheme, blue in CVD (Bloomberg PDFU COLORS pattern). */
export function semanticUp(cvd: HoldingsCvdMode = getHoldingsCvdMode()): string {
  return cvd === 'cvd' ? BB.blue : BB.green
}

/** Negative / down / loss — red in all schemes. */
export function semanticDown(): string {
  return BB.red
}

export function semanticSigned(value: number, cvd: HoldingsCvdMode = getHoldingsCvdMode()): string {
  if (value > 0) return semanticUp(cvd)
  if (value < 0) return semanticDown()
  return BB.text3
}

export function stopStatusColor(s: StopStatusTone): string {
  return s === 'stable' ? BB.green : s === 'concern' ? BB.amber : BB.red
}

export function stopStatusBg(s: StopStatusTone): string {
  return s === 'stable' ? BB.greenDim : s === 'concern' ? BB.amberDim : BB.redDim
}

export function primaryActionColor(tone: 'amber' | 'green' | 'red' | 'muted', cvd: HoldingsCvdMode = getHoldingsCvdMode()): string {
  if (tone === 'amber') return BB.amber
  if (tone === 'green') return semanticUp(cvd)
  if (tone === 'red') return BB.red
  return BB.text3
}

export function primaryActionBg(tone: 'amber' | 'green' | 'red' | 'muted', cvd: HoldingsCvdMode = getHoldingsCvdMode()): string {
  if (tone === 'amber') return BB.amberDim
  if (tone === 'green') return cvd === 'cvd' ? BB.blueDim : BB.greenDim
  return 'transparent'
}