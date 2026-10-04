import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { CioProjectionGroup } from './CioProjectionBlock'

const SLOW_POLL_MS = 300_000

type Candidate = {
  procedure_id?: string
  statement?: string
  independent_outcomes?: number
  consistency?: number
  mean_move_pct?: number
  latest_decision_date?: string
}

type Retire = { procedure_id?: string; statement?: string; reason?: string }

/** Weekly lesson digest (GET /api/v3/cio/lessons/digest): only lessons backed by
 * enough independent, quality-checked outcomes reach the operator, plus lessons a
 * later outcome contradicts. Promotion and retirement stay operator decisions. */
export default function CioLessonDigestPanel() {
  const [open, setOpen] = useState(false)
  const { data, loading, error } = useApi<any>('/api/v3/cio/lessons/digest', SLOW_POLL_MS, { enabled: open })
  const d = data || null
  const candidates: Candidate[] = Array.isArray(d?.candidates) ? d.candidates : []
  const retire: Retire[] = Array.isArray(d?.retire_proposed) ? d.retire_proposed : []
  const counts = d?.status_counts && typeof d.status_counts === 'object' ? Object.entries(d.status_counts as Record<string, number>) : []
  return (
    <CioProjectionGroup
      title="Lesson digest — outcome-backed lessons for your review"
      testId="cio-lesson-digest"
      open={open}
      onToggle={setOpen}
      note={loading ? 'Loading lesson digest…' : error ? `Lesson digest unavailable: ${String(error)}` : d?.ok === false
        ? `Lesson digest unavailable: ${d?.error || 'error'}`
        : `${d?.rule || 'rule not reported'} · price checks ${d?.price_checks || 'not reported'} · generated ${d?.generated_at || 'not reported'}`}
    >
      {d && d.ok !== false && (
        <div style={{ display: 'grid', gap: 8, fontSize: 12, color: 'var(--text1)' }}>
          {counts.length > 0 && (
            <div data-testid="cio-lesson-digest-counts" style={{ color: 'var(--text2)', fontSize: 11 }}>
              Queue: {counts.map(([status, n]) => `${status} ${n}`).join(' · ')}
            </div>
          )}
          {candidates.length === 0 ? (
            <div data-testid="cio-lesson-digest-empty" style={{ color: 'var(--text2)' }}>
              No lesson qualifies yet: none has {d?.rule ? 'met the rule above' : 'enough quality-checked outcomes'}.
            </div>
          ) : candidates.map((c, i) => (
            <div key={c.procedure_id || i} data-testid="cio-lesson-digest-candidate" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
              <div style={{ fontWeight: 700 }}>{c.statement || c.procedure_id || 'Unnamed lesson'}</div>
              <div style={{ color: 'var(--text2)', fontSize: 11 }}>
                {c.independent_outcomes ?? '?'} independent outcomes · consistency {c.consistency ?? '?'} · mean move {c.mean_move_pct ?? '?'}% · latest {c.latest_decision_date || 'unknown'}
              </div>
            </div>
          ))}
          {retire.length > 0 && (
            <div data-testid="cio-lesson-digest-retire" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
              <div style={{ fontWeight: 700 }}>Proposed for retirement (your decision)</div>
              {retire.map((r, i) => (
                <div key={r.procedure_id || i} style={{ color: 'var(--text2)', fontSize: 11 }}>{r.statement || r.procedure_id}: {r.reason || 'contradicted by a later outcome'}</div>
              ))}
            </div>
          )}
          <div style={{ color: 'var(--text3)', fontSize: 10 }}>{d?.promotion || 'Promotion is operator-only.'}</div>
        </div>
      )}
    </CioProjectionGroup>
  )
}
