/** Watch Desk v4 (WS-A): THE design-system entry point for all five Watch tabs.
 *
 * Extends the BB terminal tokens that Security Card v4 shipped with. Pages import
 * from HERE (single import); raw hexes are banned in Watch pages — the zero-hex
 * census is the acceptance gate.
 *
 * DEPRECATION MAP (v2/v3 ad-hoc palette → semantic replacement):
 *   hex-a855f7 (purple accents)        → T.extIntel.hermes (muted, badges only) or BB.text2
 *   hex-2dd4bf (teal one-offs)         → T.link or BB.text2
 *   hex-a78bfa (violet chips)          → T.extIntel.hermes
 *   hex-7dd3fc (sky chips)             → T.link
 *   hex-10a37f (openai green)          → T.extIntel.gpt (badge only)
 *   hex-ffa726 / hex-fbbf24 / hex-f5c76a /
 *   hex-eab308 / hex-fb923c (ambers/orange)→ BB.amber (attention) or BB.orange (warm metric)
 *   hex-34d399 / hex-86efac (soft greens) → BB.green / T.greenSoft
 *   hex-f87171 (soft red)              → BB.red
 *   hex-60a5fa / hex-93c5fd / hex-2563eb /
 *   hex-dbeafe (blues)                 → T.link (links/drills only, never data color)
 *   hex-64748b / hex-94a3b8 / hex-cbd5e1 /
 *   hex-f8fafc (slates)                → BB.text3 / text2 / text1 / text0
 *   hex-d8b4fe                         → T.extIntel.hermes
 *   purple-tinted dark shell family (hex-0f1117 hex-171923 hex-1a192b hex-1e2130 hex-232640
 *   hex-2d3148) → BB.bg / BB.bgPanel / BB.bgShift / BB.border — ONE dark ground.
 *
 * Type scale is LOCKED to 10/11/12/14/18/24. Nothing below 10 in Watch pages;
 * density comes from row padding on the 4px grid, not glyph shrinkage.
 */
import type { CSSProperties } from 'react'
import { BB, numStyle, terminalButton, terminalSigned } from './watchlistTerminalTokens'
import { BRAND, TOKENS, toneVars } from './designTokens'

// PR1 (2026-09-27): this file is now a COMPATIBILITY FACADE over src/lib/designTokens.ts +
// src/styles/tokens.css. Every colour below is a semantic var() so it follows the theme; the
// names are kept so the 60+ importers keep working while pages convert. New code imports
// designTokens directly. No hex may live here (scripts/check_ui_standards.mjs).
export { BRAND, TOKENS, toneVars }

export { BB, numStyle, terminalButton, terminalSigned }
export { terminalRail, terminalVerdictColor, terminalVerdictBg, terminalRrColor } from './watchlistTerminalTokens'
export { hubTitle, hubSubtitle, hubTab, hubPanel, hubStrip, hubFilterSelect, hubKpiChip } from './terminalHubChrome'

export const T = {
  /** Links / drill affordances only — never a data color. */
  link: 'var(--info-color)',
  greenSoft: 'rgba(34, 197, 94, 0.55)',
  /** External-intel brand tints — ONE muted tint each, badges only, defined nowhere else. */
  extIntel: {
    hermes: 'var(--ai-color)',
    gpt: 'var(--ai-color)',
    grok: 'var(--ai-color)',
  },
  heldBadge: {
    background: 'rgba(34, 197, 94, 0.12)',
    color: 'var(--success-color)',
    border: '1px solid rgba(34, 197, 94, 0.35)',
  },
  focusRing: 'var(--focus-ring)',
} as const

/** Rail semantics (A3): the 3px left spine every row-like element carries. */
export const RAIL = {
  favorable: BB.green,   // positive outcome / ready / winning
  attention: BB.amber,   // near-stop, overdue, needs-review, caution
  breach: BB.red,        // conflict / breach / underperforming
  neutral: 'var(--neutral-border)',    // slate — nothing notable
} as const
export type RailState = keyof typeof RAIL

export function rowRail(state: RailState): CSSProperties {
  return { borderLeft: `3px solid ${RAIL[state]}` }
}

/** Locked type scale (A2). Use these, never numeric literals below 10. */
export const TYPE = { xs: 10, sm: 11, base: 12, md: 14, lg: 18, xl: 24 } as const

/** Defense v3 D3.1 — THE house dashboard scale. body/data 12 · table rows 12–13 ·
 * section headers 14 · panel titles 16 · verdict headline 20–24 · chips 10 CAPS ONLY.
 * 7/8/9px are BANNED (check_design_tokens.sh enforces); 10 is legal only inside chips. */
export const DASH = { data: 12, row: 12.5, section: 14, panel: 16, verdict: 22, chip: 10 } as const

/** Defense Desk redesign v1 (2026-07-29). THREE tokens the mockup needs that the
 * existing palette has no value for. Everything else in that spec maps to an
 * existing BB/T token BY VALUE — never by name:
 *
 *   --bg0  hex-0a0e1a -> BB.bgPanel     --t0  hex-f8fafc -> BB.text0
 *   --bg1  hex-111827 -> BB.bgShift     --t1  hex-e2e8f0 -> BB.text1
 *   --line hex-1e293b -> BB.border      --t2  hex-94a3b8 -> BB.text3   <- NOT BB.text2
 *   --green/red/amber -> BB.*        --blue hex-60a5fa -> T.link
 *
 * The --t2 line is the trap: BB.text2 is hex-cbd5e1 and appears nowhere in the
 * mockup. A name-based mapping is wrong by one shade on every muted label,
 * which is the same class of error that derailed the previous attempt.
 *
 * NOT defined here, deliberately: the mockup's --bg2 (hex-161d2e) and --purple
 * (hex-a855f7) are declared in its :root but referenced ZERO times in its markup
 * or CSS. --purple is additionally a hex the design system already deprecates
 * in favour of T.extIntel.hermes (hex-a78bfa). Adding either would be dead weight.
 */
export const DD = {
  /** inset / sunken surface — footers, gap cells, progress-bar troughs */
  sunk: 'var(--bg-0)',
  /** emphasized border — buttons, table section rules */
  line2: 'var(--border-color)',
  /** dim metadata — table headers, .dim, the unknown-value class */
  t3: 'var(--text-3)',
} as const

/** v8.5c — LLM provider brand colors: now in designTokens.BRAND (re-exported above). */

/** Right-aligned tabular numeric cell (A2: one mono stack). */
export const numCell: CSSProperties = {
  ...numStyle,
  textAlign: 'right' as const,
}

/** A6 chip classes — construction IS the distinction. */
export function statePill(tone: 'green' | 'amber' | 'red' | 'slate' = 'slate'): CSSProperties {
  const map = {
    green: { background: BB.greenDim, color: BB.green },
    amber: { background: BB.amberDim, color: BB.amber },
    red: { background: BB.redDim, color: BB.red },
    slate: { background: 'rgba(148, 163, 184, 0.10)', color: BB.text3 },
  }[tone]
  return {
    ...map,
    fontSize: TYPE.xs,
    fontWeight: 800,
    letterSpacing: '.05em',
    textTransform: 'uppercase' as const,
    padding: '1px 6px',
    borderRadius: 2,
    whiteSpace: 'nowrap' as const,
    display: 'inline-block',
  }
}

export function metricChip(clickable = false): CSSProperties {
  return {
    ...numStyle,
    fontSize: TYPE.xs,
    color: BB.text2,
    border: `1px solid ${BB.borderHair}`,
    background: 'transparent',
    padding: '1px 6px',
    borderRadius: 2,
    whiteSpace: 'nowrap' as const,
    display: 'inline-block',
    cursor: clickable ? 'pointer' : 'default',
  }
}

export function actionChip(): CSSProperties {
  return {
    fontSize: TYPE.xs,
    fontWeight: 800,
    letterSpacing: '.04em',
    textTransform: 'uppercase' as const,
    border: `1px solid ${BB.amber}`,
    background: 'transparent',
    color: BB.amber,
    padding: '2px 10px',
    borderRadius: 999,
    cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
  }
}

export function countBubble(warn = false): CSSProperties {
  return {
    ...numStyle,
    fontSize: TYPE.xs,
    fontWeight: 800,
    background: warn ? BB.amberDim : 'rgba(148, 163, 184, 0.12)',
    color: warn ? BB.amber : BB.text2,
    padding: '0 6px',
    borderRadius: 999,
    display: 'inline-block',
    minWidth: 16,
    textAlign: 'center' as const,
  }
}

/** A5: the visible focus ring for keyboard nav. Apply on :focus-visible via style when focused. */
export function focusStyle(focused: boolean): CSSProperties {
  return focused ? { boxShadow: T.focusRing, outline: 'none' } : {}
}

/** Home v2 (WS-B): the Finviz day-change heat ramp — −3% deep red → 0 slate → +3% deep green.
 *  Exact stops here so every heat surface (treemap, news grid) shares one ramp. */
export function heatRamp(pct: number | null | undefined): string {
  const p = Math.max(-3, Math.min(3, Number(pct ?? 0)))
  if (!Number.isFinite(p) || p === 0) return 'var(--bg-3)'
  // interpolate darkness by |p|/3 between slate and the deep end
  const t = Math.abs(p) / 3
  const mix = (a: number[], b: number[]) => a.map((x, i) => Math.round(x + (b[i] - x) * t))
  const rgb = p > 0 ? mix([54, 74, 61], [22, 163, 74]) : mix([82, 56, 60], [220, 38, 38])
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`
}
