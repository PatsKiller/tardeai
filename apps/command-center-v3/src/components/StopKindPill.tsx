// Shared stop-kind pill — the single source of truth for how a protective stop's
// KIND (fixed / stop-limit / trailing / trailing-limit / monitored / none) is shown.
// Imported by both the Stop Management desk and the Portfolio > Holdings table so the
// two surfaces never drift. House palette matches StopManagement.tsx.

export { deriveStopKind } from '../lib/stopManagement'

const BLUE = '#60a5fa', CYAN = '#22d3ee', GREEN = '#22c55e', PURPLE = '#a855f7', AMBER = '#f59e0b', RED = '#ef4444'

export const STOP_KIND_PILL: Record<string, { label: string; color: string }> = {
  FIXED:          { label: 'FIXED',          color: BLUE },
  STOP_LIMIT:     { label: 'STOP LIMIT',     color: CYAN },
  TRAILING:       { label: 'TRAILING',       color: GREEN },
  TRAILING_LIMIT: { label: 'TRAILING LIMIT', color: PURPLE },
  MONITORED:      { label: 'MONITORED',      color: AMBER },
  PLANNED:        { label: 'PLANNED',        color: AMBER },
  CASH:           { label: 'CASH',           color: AMBER },
  NONE:           { label: 'NO STOP',        color: RED },
}

const fmtPct = (n: number) => (Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1))

export function StopKindPill({ kind, trailPct, distPct, orderType, small }: {
  kind?: string | null; trailPct?: number | null; distPct?: number | null
  orderType?: string | null; small?: boolean
}) {
  const k = String(kind || 'NONE').toUpperCase()
  const p = STOP_KIND_PILL[k] || STOP_KIND_PILL.NONE
  const isTrail = k === 'TRAILING' || k === 'TRAILING_LIMIT'
  const isCash = k === 'CASH'
  const hasStop = k !== 'NONE' && !isCash
  // Trailing kinds show the trail %; static kinds (fixed / stop-limit / monitored) show how
  // far the stop sits BELOW price — so every row states the type AND the % at a glance.
  const pct = isTrail ? trailPct : distPct
  const suffix = isTrail ? 'trail' : 'below'
  const label = hasStop && pct != null ? `${p.label} ${fmtPct(pct)}%` : p.label
  const title = isCash
    ? 'cash holding — protective stops do not apply'
    : hasStop
      ? `${p.label} stop${pct != null ? ` — ${fmtPct(pct)}% ${suffix} price` : ''}${orderType ? ` · broker order type: ${orderType}` : ''}`
      : 'no protective stop'
  return (
    <span title={title}
      style={{ display: 'inline-block', fontSize: small ? 10 : 11, fontWeight: 800, letterSpacing: '.02em',
               color: p.color, border: `1px solid ${p.color}`, background: `${p.color}1a`,
               borderRadius: 999, padding: small ? '0 6px' : '1px 8px', whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}
