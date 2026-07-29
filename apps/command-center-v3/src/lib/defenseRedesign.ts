/** Defense Desk redesign v1 — shared primitives.
 *
 * No feature flag. The redesign IS the Defense Desk as of 2026-07-29; it shipped
 * gated for one deploy and the operator removed the gate. Rollback is `git revert`
 * of the commit, not a runtime toggle.
 *
 * SECTOR_LEADERS_V1 is untouched — the Sector Leaders card is a section of this
 * page and keeps its own flag for the card itself.
 */
import type { CSSProperties } from 'react'
import { BB, DD, T } from './watchTokens'

/** The mockup's token set, mapped BY VALUE to the page's own palette.
 *
 * DEVIATION (operator-authorized 2026-07-29): `bg0` is the mockup's #0a0e1a but
 * we keep BB.bg (#0f172a) as the page ground. The design's intent is the
 * contrast RELATIONSHIP between page / panel / sunken, not the specific hex —
 * and BB.bg is shared with other pages, so repainting it is not a defense-page
 * decision. Five units of luminance is not worth that blast radius.
 */
export const S = {
  bg0: BB.bg,            // page ground — see deviation note above
  bg1: BB.bgShift,       // #111827 panel surface
  sunk: DD.sunk,         // #0d121f inset / footer
  line: BB.border,       // #1e293b hairline
  line2: DD.line2,       // #2a3750 emphasized
  t0: BB.text0,          // #f8fafc headings, primary values
  t1: BB.text1,          // #e2e8f0 body
  t2: BB.text3,          // #94a3b8 muted / labels  — NOT BB.text2
  t3: DD.t3,             // #64748b dim / metadata
  green: BB.green,
  red: BB.red,
  amber: BB.amber,
  blue: T.link,          // #60a5fa selected state, held-position chip
  mono: BB.mono,
} as const

export const panel: CSSProperties = {
  background: S.bg1, border: `1px solid ${S.line}`, borderRadius: 10, overflow: 'hidden',
}
export const ph: CSSProperties = {
  padding: '12px 16px', borderBottom: `1px solid ${S.line}`,
  display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
}
/** Every number renders mono + tabular so columns of figures align vertically. */
export const mono: CSSProperties = { fontFamily: S.mono, fontVariantNumeric: 'tabular-nums' }

export type ChipTone = 'n' | 'g' | 'r' | 'a' | 'b'
const CHIP_BG: Record<ChipTone, string> = {
  n: 'rgba(148,163,184,.1)', g: 'rgba(34,197,94,.13)', r: 'rgba(239,68,68,.13)',
  a: 'rgba(255,176,0,.14)', b: 'rgba(96,165,250,.13)',
}
const CHIP_FG: Record<ChipTone, string> = {
  n: S.t2, g: S.green, r: S.red, a: S.amber, b: S.blue,
}
export function chip(tone: ChipTone = 'n'): CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', padding: '2px 7px', borderRadius: 3,
    fontSize: 10, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
    whiteSpace: 'nowrap', background: CHIP_BG[tone], color: CHIP_FG[tone],
  }
}

export const th: CSSProperties = {
  fontSize: 10, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
  color: S.t3, textAlign: 'right', padding: '7px 10px',
}
export const thL: CSSProperties = { ...th, textAlign: 'left' }
export const td: CSSProperties = { padding: '8px 10px', textAlign: 'right', borderTop: `1px solid ${S.line}` }
export const tdL: CSSProperties = { ...td, textAlign: 'left' }
/** Left-aligned prose cell — the Read / flags columns. Sans, not mono. */
export const tdProse: CSSProperties = {
  ...td, textAlign: 'left', paddingLeft: 18, fontFamily: 'inherit',
}

export function btn(primary = false): CSSProperties {
  return {
    border: `1px solid ${primary ? 'rgba(96,165,250,.4)' : S.line2}`,
    background: primary ? 'rgba(96,165,250,.12)' : 'transparent',
    color: primary ? S.blue : S.t1,
    borderRadius: 6, padding: '5px 11px', font: 'inherit', fontSize: 12, cursor: 'pointer',
  }
}
