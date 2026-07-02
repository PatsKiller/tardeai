import { desk } from '../lib/proposalDeskTheme'
import { fmtDeskAge, fmtDeskTimestamp } from '../lib/fmtTimestamp'

const MUTED = desk.textDim
const GRADE_METHOD =
  'Score 0–100: RSI · MA trend · ATR% · RVOL · ADX (Finviz). ≥80 STRONG · ≥60 OK · ≥40 MIXED · ≥20 WEAK. Cron every 2h :15 + ↻ Refresh.'

type Props = {
  gate?: string | null
  oversight?: string | null
  techGrade?: string | null
  techScore?: number | null
  techGradedAt?: string | null
  techVerdict?: string | null
  techAction?: string | null
  routeBlocked?: boolean
  routeBlockReason?: string | null
}

function tone(status: string | null | undefined): string {
  const s = String(status || '').toUpperCase()
  if (s === 'BLOCK' || s.includes('WEAK') || s.includes('INCOMPLETE')) return desk.red
  if (s === 'WARN' || s.includes('MIXED')) return desk.amber
  if (s === 'PASS' || s.includes('STRONG') || s.includes('OK')) return desk.green
  return desk.textMuted
}

function cell(label: string, value: string, color: string, sub?: string) {
  return (
    <div style={{ flex: '1 1 140px', minWidth: 120, padding: '8px 12px' }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.45px' }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 800, color, marginTop: 2, fontFamily: desk.mono }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: MUTED, marginTop: 3, lineHeight: 1.35 }}>{sub}</div>}
    </div>
  )
}

export default function ProposalDeskStrip({
  gate, oversight, techGrade, techScore, techGradedAt, techVerdict, techAction, routeBlocked, routeBlockReason,
}: Props) {
  const techLabel = techGrade ? String(techGrade).replace('TECH_', '') : '—'
  const techValue = techScore != null ? `${techLabel} · ${techScore}/100` : techLabel
  const gradedLine = techGradedAt
    ? `Graded ${fmtDeskTimestamp(techGradedAt)}${fmtDeskAge(techGradedAt) ? ` (${fmtDeskAge(techGradedAt)})` : ''}`
    : 'Not graded yet — wait for 2h cron or ↻ Refresh'
  const primaryAction = routeBlocked && routeBlockReason
    ? routeBlockReason.slice(0, 100)
    : (techAction || (oversight === 'BLOCK' ? 'Resolve oversight blockers before route' : 'Review gates then Validate'))

  return (
    <div style={{
      margin: '0 14px 10px',
      borderRadius: 10,
      border: `1px solid ${desk.border}`,
      background: desk.bgInset,
      overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', borderBottom: `1px solid ${desk.borderSubtle}` }}>
        {cell('Gate', gate || '—', tone(gate))}
        {cell('Oversight', oversight || '—', tone(oversight))}
        {cell('Technicals', techValue, tone(techGrade), techVerdict?.slice(0, 72) || gradedLine)}
        {cell('Next step', routeBlocked ? 'Blocked' : 'Review', routeBlocked ? desk.red : desk.teal, primaryAction)}
      </div>
      <div style={{
        padding: '6px 12px', fontSize: 9, color: MUTED, lineHeight: 1.45,
        borderTop: `1px solid ${desk.borderSubtle}`, background: desk.bg,
      }} title={GRADE_METHOD}>
        <span style={{ fontWeight: 800, color: desk.textMuted }}>Grade calc · </span>
        {GRADE_METHOD}
        {techGradedAt && (
          <span style={{ fontFamily: desk.mono, marginLeft: 8, color: desk.text }}>
            · last {fmtDeskTimestamp(techGradedAt)}
          </span>
        )}
      </div>
    </div>
  )
}