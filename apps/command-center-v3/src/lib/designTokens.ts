/** Design tokens — TypeScript mirror of src/styles/tokens.css (PR1, 2026-09-27).
 *
 * Components use these names, never a colour literal. Every value here is a `var(--…)`
 * reference so it follows the active theme; the ONLY hex literals in this file are
 * CHART_HEX and BRAND, for chart libraries and vendor pills that cannot read CSS vars.
 * scripts/check_ui_standards.mjs allows hex in this file and tokens.css only.
 */
import type { CSSProperties } from 'react'

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'ai' | 'neutral'
export const TONES: readonly Tone[] = ['success', 'warning', 'danger', 'info', 'ai', 'neutral'] as const

/** What each tone MEANS (the standard, not a suggestion). */
export const TONE_MEANING: Record<Tone, string> = {
  success: 'positive outcome, ready, winning',
  warning: 'watch, caution, needs review',
  danger: 'risk, breach, loss, error',
  info: 'informational, links, neutral emphasis',
  ai: 'AI-sourced insight or decision',
  neutral: 'nothing notable',
}

export const TOKENS = {
  bg: { 0: 'var(--bg-0)', 1: 'var(--bg-1)', 2: 'var(--bg-2)', 3: 'var(--bg-3)' },
  text: { 0: 'var(--text-0)', 1: 'var(--text-1)', 2: 'var(--text-2)', 3: 'var(--text-3)' },
  border: 'var(--border-color)',
  borderSubtle: 'var(--border-subtle)',
  primary: 'var(--primary-color)',
  secondary: 'var(--secondary-color)',
  focusRing: 'var(--focus-ring)',
  success: 'var(--success-color)',
  warning: 'var(--warning-color)',
  danger: 'var(--danger-color)',
  info: 'var(--info-color)',
  ai: 'var(--ai-color)',
  neutral: 'var(--neutral-color)',
  chart: ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)'],
} as const

/** The three vars a tone carries: text/stroke colour, soft fill, border. */
export function toneVars(tone: Tone): { color: string; bg: string; border: string } {
  return { color: `var(--${tone}-color)`, bg: `var(--${tone}-bg)`, border: `var(--${tone}-border)` }
}

/** Legacy verdict / urgency / rail vocab → tone (one mapping, used by the facades). */
export function toneFromVerdict(v?: string | null): Tone {
  const s = String(v || '').toUpperCase()
  if (s === 'READY' || s === 'GO' || s === 'APPROVE' || s === 'BUY' || s === 'GREEN' || s === 'FAVORABLE') return 'success'
  if (s === 'WAIT' || s === 'WATCH' || s === 'AMBER' || s === 'ATTENTION' || s === 'MONITOR_ONLY' || s === 'HOLD') return 'warning'
  if (s === 'FIX' || s === 'BLOCKED' || s === 'REJECT' || s === 'RED' || s === 'BREACH' || s === 'AVOID' || s === 'NO TRADE') return 'danger'
  if (s === 'AI' || s === 'LLM' || s === 'HERMES' || s === 'GPT' || s === 'GROK') return 'ai'
  if (s === 'INFO' || s === 'BLUE' || s === 'LINK') return 'info'
  return 'neutral'
}

export const SPACE = { 1: 'var(--space-1)', 2: 'var(--space-2)', 3: 'var(--space-3)', 4: 'var(--space-4)',
  5: 'var(--space-5)', 6: 'var(--space-6)', 7: 'var(--space-7)', 8: 'var(--space-8)' } as const
export const RADIUS = { sm: 'var(--radius-sm)', md: 'var(--radius-md)', lg: 'var(--radius-lg)', pill: 'var(--radius-pill)' } as const
export const SHADOW = { 1: 'var(--shadow-1)', 2: 'var(--shadow-2)', 3: 'var(--shadow-3)' } as const

/** Locked type scale (numbers, because inline styles need numbers). xs is for chips only. */
export const TYPE = { xs: 10, sm: 11, base: 12, md: 14, lg: 18, xl: 24 } as const
export const FONT = { sans: 'var(--font-sans)', mono: 'var(--font-mono)' } as const

export const numStyle: CSSProperties = { fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' }

export type ThemeName = 'dark' | 'light'

/** Hex for chart libraries (recharts / lightweight-charts props cannot take var()). Read via
 *  useTheme() so the series follow the active theme. Keep in sync with tokens.css. */
export const CHART_HEX: Record<ThemeName, { series: string[]; grid: string; text: string; success: string; danger: string; warning: string }> = {
  dark: { series: ['#7db4ff', '#34d27a', '#f5b83d', '#c4a6ff', '#f26d6d', '#5fd3d3'], grid: '#2d3148', text: '#9ea6ba',
    success: '#34d27a', danger: '#f26d6d', warning: '#f5b83d' },
  light: { series: ['#1d4ed8', '#137236', '#8f5106', '#6d28d9', '#b91c1c', '#0f766e'], grid: '#d5d9e3', text: '#3f4a5f',
    success: '#137236', danger: '#b91c1c', warning: '#8f5106' },
}

/** LLM provider brand colours for oversight pills — vendor identity, not a tone. */
export const BRAND = { anthropic: '#D97757', openai: '#10A37F', xai: '#B8C2CC', deepseek: '#3B82F6' } as const

/** Chip construction from a tone (the single chip recipe; primitives/Chip wraps it). */
export function chipStyle(tone: Tone, variant: 'solid' | 'outline' | 'soft' = 'soft', size: 'sm' | 'md' = 'sm'): CSSProperties {
  const t = toneVars(tone)
  const base: CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: size === 'sm' ? TYPE.xs : TYPE.sm, fontWeight: 700, letterSpacing: '.04em',
    lineHeight: 1.4, padding: size === 'sm' ? '1px 6px' : '2px 8px',
    borderRadius: RADIUS.pill, whiteSpace: 'nowrap',
  }
  if (variant === 'solid') return { ...base, background: t.color, color: TOKENS.bg[0], border: `1px solid ${t.color}` }
  if (variant === 'outline') return { ...base, background: 'transparent', color: t.color, border: `1px solid ${t.border}` }
  return { ...base, background: t.bg, color: t.color, border: `1px solid ${t.border}` }
}
