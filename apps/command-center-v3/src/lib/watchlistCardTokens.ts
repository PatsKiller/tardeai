import type { ActionUrgency, CardVerdict } from './watchlistCardAction'

/** Security Card v2 tokens — one elevated surface, hairline dividers, color = signal only.
 *  Four signal colors with strict ownership:
 *    teal  = actionable / conviction        amber = caution / stale
 *    red   = risk / plan defect             green = price/P&L numerals ONLY (never actions)
 *  Everything else is a neutral. */
export const WL = {
  text: { primary: '#ecf1f8', secondary: '#aeb9ca', muted: '#8b98ac', dim: '#66748c' },
  signal: { teal: '#2dd4bf', amber: '#f5a623', red: '#ef5350' },
  price: { up: '#4ade80', down: '#ef5350' },
  surface: {
    card: '#111927',
    edge: '#202b3d',
    divider: 'rgba(148,163,184,.10)',
    inset: 'rgba(2,6,23,.35)',
  },
  hero: {
    textLarge: 17,
    textMedium: 15,
    subtextSize: 12,
    labelSize: 10.5,
  },
  card: {
    radius: 10,
    shadow: '0 8px 24px rgba(0,0,0,.28)',
  },
  /** Full-bleed section row inside the card — replaces the old boxes-in-boxes panels. */
  row: { padX: 18, padY: 13 },
} as const

export function urgencyColor(u: ActionUrgency): string | undefined {
  if (u === 'red') return WL.signal.red
  if (u === 'amber') return WL.signal.amber
  if (u === 'green') return WL.signal.teal
  return undefined
}

/** Verdict → the single state word shown in the banner label. */
export function verdictWord(v: CardVerdict): string {
  const map: Record<CardVerdict, string> = {
    READY: 'READY', WAIT: 'HOLD', SKIP: 'AVOID', STALE: 'STALE',
    FIX: 'FIX', BUILD: 'BUILD', WATCH: 'MONITOR',
  }
  return map[v]
}

/** Banner treatment from verdict — the banner is the only tinted surface on the card.
 *  No inner rail: the card's single left rail carries the state color. */
export function heroStateStyle(verdict: CardVerdict, urgency: ActionUrgency) {
  if (verdict === 'READY' || urgency === 'green') {
    return { bg: 'rgba(45,212,191,.08)', border: 'rgba(45,212,191,.28)', accent: WL.signal.teal, rail: WL.signal.teal }
  }
  if (verdict === 'FIX' || urgency === 'red') {
    return { bg: 'rgba(239,83,80,.07)', border: 'rgba(239,83,80,.25)', accent: WL.signal.red, rail: WL.signal.red }
  }
  if (verdict === 'STALE' || verdict === 'WAIT' || verdict === 'BUILD' || urgency === 'amber') {
    return { bg: 'rgba(245,166,35,.07)', border: 'rgba(245,166,35,.25)', accent: WL.signal.amber, rail: WL.signal.amber }
  }
  if (verdict === 'SKIP') {
    return { bg: 'rgba(148,163,184,.05)', border: 'rgba(148,163,184,.14)', accent: WL.text.dim, rail: WL.text.dim }
  }
  // WATCH / monitor — neutral, no urgency invented where none exists
  return { bg: 'rgba(148,163,184,.06)', border: 'rgba(148,163,184,.16)', accent: WL.text.secondary, rail: WL.text.dim }
}

/** Quiet uppercase row label — 10.5px floor, nothing on the card renders smaller. */
export const sectionLabel = {
  fontSize: 10.5,
  fontWeight: 700,
  letterSpacing: '.09em',
  textTransform: 'uppercase',
  color: WL.text.dim,
  marginBottom: 8,
} as const

export const MONO = 'ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace'

/** Numerals only — prices, levels, R:R. Prose never renders in mono. */
export const numStyle = { fontFamily: MONO, fontVariantNumeric: 'tabular-nums' } as const
