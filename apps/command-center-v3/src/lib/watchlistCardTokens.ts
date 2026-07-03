/** Institutional watchlist card design tokens — color only for urgency/importance. */
export const WL = {
  text: { primary: '#f8fafc', secondary: '#cbd5e1', muted: '#94a3b8', dim: '#64748b' },
  urgency: { green: '#16a34a', amber: '#d97706', red: '#dc2626' },
  price: { up: '#16a34a', down: '#dc2626' },
  hero: {
    bg: 'rgba(30,41,59,.52)',
    border: 'rgba(71,85,105,.35)',
    labelSize: 8.5,
    textLarge: 16,
    textMedium: 14,
    subtextSize: 10,
  },
  body: {
    bg: 'rgba(15,23,42,.28)',
    border: 'rgba(148,163,184,.12)',
    radius: 10,
  },
  tag: {
    background: 'rgba(30,41,59,.75)',
    border: '1px solid rgba(71,85,105,.45)',
    color: '#cbd5e1',
  },
  card: {
    bg: 'var(--bg1)',
    border: '1px solid rgba(148,163,184,.2)',
    radius: 12,
    shadow: '0 6px 20px rgba(0,0,0,.14)',
  },
} as const

export function urgencyColor(u: 'none' | 'amber' | 'green' | 'red'): string | undefined {
  if (u === 'red') return WL.urgency.red
  if (u === 'amber') return WL.urgency.amber
  if (u === 'green') return WL.urgency.green
  return undefined
}