import { desk } from '../lib/proposalDeskTheme'
import { fmtDeskAge, fmtDeskTimestamp } from '../lib/fmtTimestamp'

const MUTED = desk.textDim
const TEXT = desk.text

type Tech = {
  rsi?: number | null
  technical_grade?: string
  technical_score?: number
  verdict?: string
  narrative?: string
  action?: string
  summary?: string
  concerns?: string[]
  methodology?: string
  refresh_cadence?: string
  graded_at?: string
  data_sources?: string[]
}

function accentForGrade(grade: string): string {
  const g = grade.toUpperCase()
  if (g.includes('STRONG')) return desk.green
  if (g.includes('_OK')) return desk.teal
  if (g.includes('MIXED')) return desk.amber
  if (g.includes('WEAK') || g.includes('INCOMPLETE')) return desk.red
  return desk.border
}

export default function TechnicalAssessmentCard({
  tech,
  compact = false,
  gradeInStrip = true,
}: {
  tech: Tech
  compact?: boolean
  /** When true, grade/score/timestamp live in ProposalDeskStrip — this block is narrative + action only. */
  gradeInStrip?: boolean
}) {
  const grade = String(tech.technical_grade || 'TECH_INCOMPLETE')
  const accent = accentForGrade(grade)
  const hasBody = Boolean(tech.narrative || tech.summary || tech.action)
  const gradedLabel = tech.graded_at
    ? `${fmtDeskTimestamp(tech.graded_at)}${fmtDeskAge(tech.graded_at) ? ` (${fmtDeskAge(tech.graded_at)})` : ''}`
    : null

  if (!hasBody && tech.rsi == null && !tech.summary) {
    return (
      <div style={{
        margin: '0 14px 8px',
        padding: '10px 12px',
        borderRadius: 10,
        background: desk.bg,
        border: `1px solid ${desk.border}`,
      }}>
        <div style={{ fontSize: 10, color: MUTED, lineHeight: 1.5 }}>
          No technical snapshot — auto every 2h at :15 (cron) or ↻ Refresh on this card.
        </div>
      </div>
    )
  }

  return (
    <div style={{
      margin: compact ? '0 14px 8px' : '0 14px 10px',
      padding: compact ? '8px 12px' : '10px 12px',
      borderRadius: 10,
      background: desk.bg,
      border: `1px solid ${desk.border}`,
      borderLeft: gradeInStrip ? `3px solid ${accent}` : `3px solid ${accent}`,
    }}>
      {!gradeInStrip && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.5px' }}>
              Technical assessment
            </div>
            <div style={{ fontSize: 15, fontWeight: 800, color: TEXT, marginTop: 4 }}>
              {tech.verdict || grade.replace('TECH_', '').replace('_', ' ')}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{
              fontSize: 11, fontWeight: 900, fontFamily: desk.mono,
              color: accent, padding: '3px 8px', borderRadius: 6,
              border: `1px solid ${accent}44`, background: `${accent}11`,
            }}>
              {grade.replace('TECH_', '')}
              {tech.technical_score != null ? ` · ${tech.technical_score}/100` : ''}
            </div>
            {gradedLabel && (
              <div style={{ fontSize: 9.5, color: MUTED, marginTop: 4, fontFamily: desk.mono }}>Graded {gradedLabel}</div>
            )}
          </div>
        </div>
      )}

      {gradeInStrip && (tech.narrative || tech.verdict) && (
        <div style={{ fontSize: 11.5, fontWeight: 700, color: TEXT, lineHeight: 1.45, marginBottom: tech.action ? 6 : 0 }}>
          {tech.narrative || tech.verdict}
        </div>
      )}

      {!gradeInStrip && tech.narrative && (
        <div style={{ fontSize: 11.5, color: TEXT, lineHeight: 1.55 }}>
          {tech.narrative}
        </div>
      )}

      {tech.action && (
        <div style={{
          fontSize: 11, fontWeight: 700, color: TEXT,
          padding: '6px 8px', borderRadius: 8,
          background: desk.bgInset, border: `1px solid ${desk.borderSubtle}`,
        }}>
          <span style={{ color: MUTED, fontWeight: 800, marginRight: 6 }}>ACTION</span>
          {tech.action}
        </div>
      )}

      {!compact && tech.summary && (
        <div style={{ fontSize: 10, color: MUTED, fontFamily: desk.mono, marginTop: 6 }}>
          {tech.summary}
        </div>
      )}
    </div>
  )
}