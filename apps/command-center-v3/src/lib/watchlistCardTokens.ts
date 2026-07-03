import type { ActionUrgency, CardVerdict } from './watchlistCardAction'

/** Institutional watchlist card tokens — color signals actionability only. */
export const WL = {
  text: { primary: '#f1f5f9', secondary: '#cbd5e1', muted: '#94a3b8', dim: '#64748b' },
  urgency: { green: '#22c55e', teal: '#14b8a6', amber: '#f59e0b', red: '#ef4444' },
  price: { up: '#22c55e', down: '#ef4444' },
  surface: {
    card: 'linear-gradient(180deg, rgba(15,23,42,.92) 0%, rgba(15,23,42,.78) 100%)',
    raised: 'rgba(30,41,59,.55)',
    inset: 'rgba(2,6,23,.35)',
    divider: 'rgba(148,163,184,.14)',
  },
  hero: {
    textLarge: 17,
    textMedium: 15,
    subtextSize: 11,
    labelSize: 9,
  },
  body: { radius: 8 },
  tag: {
    background: 'rgba(30,41,59,.5)',
    border: '1px solid rgba(71,85,105,.35)',
    color: '#94a3b8',
  },
  card: {
    bg: 'var(--bg1)',
    border: '1px solid rgba(148,163,184,.16)',
    radius: 10,
    shadow: '0 1px 0 rgba(255,255,255,.04) inset, 0 8px 24px rgba(0,0,0,.18)',
  },
} as const

export function urgencyColor(u: ActionUrgency): string | undefined {
  if (u === 'red') return WL.urgency.red
  if (u === 'amber') return WL.urgency.amber
  if (u === 'green') return WL.urgency.teal
  return undefined
}

/** Hero panel treatment from verdict — one accent per card state. */
export function heroStateStyle(verdict: CardVerdict, urgency: ActionUrgency) {
  if (verdict === 'READY' || urgency === 'green') {
    return {
      bg: 'rgba(20,184,166,.1)',
      border: 'rgba(20,184,166,.28)',
      accent: WL.urgency.teal,
      rail: WL.urgency.teal,
      label: 'ACTIONABLE',
    }
  }
  if (verdict === 'FIX' || urgency === 'red') {
    return {
      bg: 'rgba(239,68,68,.08)',
      border: 'rgba(239,68,68,.24)',
      accent: WL.urgency.red,
      rail: WL.urgency.red,
      label: 'ATTENTION',
    }
  }
  if (verdict === 'STALE' || verdict === 'WAIT' || verdict === 'BUILD' || urgency === 'amber') {
    return {
      bg: 'rgba(245,158,11,.08)',
      border: 'rgba(245,158,11,.22)',
      accent: WL.urgency.amber,
      rail: WL.urgency.amber,
      label: 'CAUTION',
    }
  }
  if (verdict === 'SKIP') {
    return {
      bg: 'rgba(100,116,139,.12)',
      border: 'rgba(100,116,139,.22)',
      accent: WL.text.muted,
      rail: WL.text.dim,
      label: 'AVOID',
    }
  }
  return {
    bg: 'rgba(30,41,59,.45)',
    border: 'rgba(71,85,105,.3)',
    accent: WL.text.secondary,
    rail: WL.text.dim,
    label: 'MONITOR',
  }
}

export const sectionLabel = {
  fontSize: 9,
  fontWeight: 800,
  letterSpacing: '.1em',
  textTransform: 'uppercase',
  color: WL.text.dim,
  marginBottom: 8,
}