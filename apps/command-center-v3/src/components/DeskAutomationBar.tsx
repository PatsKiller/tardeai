import { desk } from '../lib/proposalDeskTheme'
import { fmtDeskAge, fmtDeskTimestamp } from '../lib/fmtTimestamp'

const MUTED = desk.textDim

type Job = {
  id: string
  label: string
  schedule: string
  manual?: string | null
  last_at?: string | null
  last_detail?: string | null
  automated?: boolean
}

type Props = {
  automation?: { jobs?: Job[]; grade_methodology?: string; generated_at?: string } | null
  queueGeneratedAt?: string | null
}

export default function DeskAutomationBar({ automation, queueGeneratedAt }: Props) {
  const jobs = automation?.jobs || []
  if (!jobs.length) return null

  return (
    <details style={{
      marginBottom: 12, padding: '10px 12px', borderRadius: desk.radiusLg,
      border: `1px solid ${desk.border}`, background: desk.bg,
    }}>
      <summary style={{
        fontSize: 10, fontWeight: 700, color: desk.textMuted, cursor: 'pointer',
        listStyle: 'none', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        <span>Automation · schedules · last run</span>
        {queueGeneratedAt && (
          <span style={{ fontSize: 9, color: MUTED, fontFamily: desk.mono }}>
            queue stats {fmtDeskTimestamp(queueGeneratedAt)}
          </span>
        )}
      </summary>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {automation?.grade_methodology && (
          <div style={{ fontSize: 9.5, color: desk.text, lineHeight: 1.5, padding: '8px 10px', borderRadius: 8, background: desk.bgInset, border: `1px solid ${desk.borderSubtle}` }}>
            <span style={{ fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.35px' }}>Technical grade · </span>
            {automation.grade_methodology}
          </div>
        )}
        {jobs.map(j => (
          <div key={j.id} style={{
            display: 'grid', gridTemplateColumns: 'minmax(120px, 1fr) minmax(0, 2fr) auto',
            gap: '4px 12px', fontSize: 9.5, alignItems: 'baseline', padding: '6px 0',
            borderBottom: `1px solid ${desk.borderSubtle}`,
          }}>
            <span style={{ fontWeight: 800, color: desk.text }}>{j.label}</span>
            <span style={{ color: MUTED, lineHeight: 1.4 }}>
              {j.schedule}
              {j.manual ? <span style={{ color: desk.textMuted }}> · manual: {j.manual}</span> : null}
            </span>
            <span style={{ fontFamily: desk.mono, color: j.last_at ? desk.text : MUTED, whiteSpace: 'nowrap', textAlign: 'right' }}>
              {j.last_at
                ? `${fmtDeskTimestamp(j.last_at)}${fmtDeskAge(j.last_at) ? ` (${fmtDeskAge(j.last_at)})` : ''}`
                : j.automated ? 'no run logged' : 'on demand'}
              {j.last_detail ? <span style={{ color: MUTED }}> · {j.last_detail}</span> : null}
            </span>
          </div>
        ))}
      </div>
    </details>
  )
}