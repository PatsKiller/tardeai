import { desk } from '../lib/proposalDeskTheme'

const GREEN = desk.green
const AMBER = desk.amber
const RED = desk.red
const TEAL = '#2dd4bf'
const MUTED = desk.textDim

type LaneGates = {
  paper_atm?: {
    status?: string
    trade_id?: number
    entry_price?: number
    message?: string | null
  }
  path_b?: {
    status?: string
    agents_pending?: string[]
    message?: string | null
  }
}

export function GradeSplitPills({
  gradeSplit,
  size = 'sm',
}: {
  gradeSplit?: {
    screener?: { label?: string; grade?: string | null; score?: number | null }
    finviz?: { label?: string; grade?: string | null; score?: number | null; technical_grade?: string | null }
  } | null
  size?: 'sm' | 'md'
}) {
  if (!gradeSplit) return null
  const pad = size === 'md' ? '3px 8px' : '1px 6px'
  const fs = size === 'md' ? 9 : 8
  const pill = (label: string, grade: string | null | undefined, score: number | null | undefined, accent: string, tip: string) => {
    if (!grade) return null
    return (
      <span
        key={label}
        title={tip}
        style={{
          fontSize: fs, fontWeight: 800, padding: pad, borderRadius: 5,
          background: `${accent}18`, color: accent, border: `1px solid ${accent}44`, whiteSpace: 'nowrap',
        }}
      >
        {label} {grade}{score != null ? ` · ${Math.round(Number(score))}` : ''}
      </span>
    )
  }
  const sc = gradeSplit.screener
  const fv = gradeSplit.finviz
  const scColor = sc?.grade?.startsWith('A') ? GREEN : sc?.grade === 'B' ? TEAL : AMBER
  const fvScore = fv?.score != null ? Number(fv.score) : null
  const fvColor = fvScore != null && fvScore >= 60 ? TEAL : fvScore != null && fvScore >= 40 ? AMBER : RED
  return (
    <span style={{ display: 'inline-flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
      {pill(sc?.label || 'Screener', sc?.grade ?? null, sc?.score ?? null, scColor,
        'Grade at proposal birth (pullback screener / watchlist bridge)')}
      {pill(fv?.label || 'Finviz', fv?.grade ?? null, fv?.score ?? null, fvColor,
        `Live Finviz technicals${fv?.technical_grade ? ` (${fv.technical_grade})` : ''} — gates ATM + Path B display`)}
    </span>
  )
}

export default function ProposalLaneGateStrip({
  routingLane,
  laneGates,
}: {
  routingLane?: string | null
  laneGates?: LaneGates | null
}) {
  const lane = routingLane || ''
  const atm = laneGates?.paper_atm
  const pathB = laneGates?.path_b

  if (lane === 'paper_atm' && atm) {
    const filled = atm.status === 'filled'
    const color = filled ? GREEN : atm.status === 'pending' ? TEAL : MUTED
    return (
      <div style={{
        padding: '7px 12px', borderBottom: `1px solid ${desk.borderSubtle}`,
        background: filled ? 'rgba(34,197,94,.08)' : 'rgba(45,212,191,.06)',
        fontSize: 11, color: desk.text, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
      }}>
        <span style={{ fontWeight: 800, color }}>ATM paper</span>
        <span style={{ color: filled ? GREEN : TEAL, fontWeight: 700 }}>
          {filled ? '✓ Filled' : atm.status === 'pending' ? '○ Pending ATM' : atm.status}
        </span>
        {atm.message && <span style={{ color: MUTED, flex: 1, minWidth: 200 }}>{atm.message}</span>}
      </div>
    )
  }

  if (lane === 'live_2fa' && pathB) {
    const blocked = pathB.status === 'blocked'
    return (
      <div style={{
        padding: '7px 12px', borderBottom: `1px solid ${desk.borderSubtle}`,
        background: blocked ? 'rgba(239,68,68,.06)' : 'rgba(34,197,94,.05)',
        fontSize: 11, color: desk.text, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
      }}>
        <span style={{ fontWeight: 800, color: AMBER }}>Path B · 2FA</span>
        <span style={{ color: blocked ? RED : GREEN, fontWeight: 700 }}>
          {blocked ? '⛔ BLOCK' : '✓ Route-eligible'}
        </span>
        {pathB.message && <span style={{ color: MUTED, flex: 1, minWidth: 200 }}>{pathB.message}</span>}
      </div>
    )
  }

  return null
}