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
  NONE:           { label: 'NO STOP',        color: RED },
}

export function StopKindPill({ kind, trailPct, orderType, small }: {
  kind?: string | null; trailPct?: number | null; orderType?: string | null; small?: boolean
}) {
  const k = String(kind || 'NONE').toUpperCase()
  const p = STOP_KIND_PILL[k] || STOP_KIND_PILL.NONE
  const isTrail = k === 'TRAILING' || k === 'TRAILING_LIMIT'
  const label = isTrail && trailPct != null ? `${p.label} ${trailPct}%` : p.label
  return (
    <span title={orderType ? `broker order type: ${orderType}` : p.label}
      style={{ display: 'inline-block', fontSize: small ? 10 : 11, fontWeight: 800, letterSpacing: '.02em',
               color: p.color, border: `1px solid ${p.color}`, background: `${p.color}1a`,
               borderRadius: 999, padding: small ? '0 6px' : '1px 8px', whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}
