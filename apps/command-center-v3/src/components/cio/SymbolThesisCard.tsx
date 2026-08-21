import { useCallback, useState, type CSSProperties, type ReactNode } from 'react'

/**
 * Living symbol-thesis card for CIO UNIVERSE & THESES.
 * Visual tokens match CioHub cards. Advisory only — no trade controls.
 * Phase C: journal stance, provenance, thesis history, web feedback intents.
 */

const card: CSSProperties = {
  background: 'var(--bg2)', borderRadius: 8, padding: 16,
  border: '1px solid var(--border)', marginBottom: 16,
}
const kLabel: CSSProperties = {
  fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase',
  letterSpacing: '.4px', fontWeight: 700,
}
const muted: CSSProperties = { fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }
const faint: CSSProperties = { fontSize: 12, color: 'var(--text3)', lineHeight: 1.45 }

const FEEDBACK_INTENTS = [
  { intent: 'AGREE', label: 'Agree' },
  { intent: 'DISAGREE', label: 'Disagree' },
  { intent: 'INTERESTED', label: 'Interested' },
  { intent: 'DEFER', label: 'Defer' },
  { intent: 'NEED_DATA', label: 'Need data' },
  { intent: 'DISMISS', label: 'Dismiss' },
] as const

const feedbackBtn: CSSProperties = {
  padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--bg0)', color: 'var(--text1)', cursor: 'pointer',
  fontSize: 11, fontWeight: 600,
}
const feedbackBtnActive: CSSProperties = {
  ...feedbackBtn, background: 'var(--accent-dim)', borderColor: 'var(--accent)', color: 'var(--accent)',
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div style={kLabel}>{label}</div>
      <div style={{ ...muted, color: 'var(--text1)', marginTop: 3 }}>{children || '—'}</div>
    </div>
  )
}

function listText(v: unknown): string {
  if (v == null) return '—'
  if (Array.isArray(v)) {
    const parts = v.map(x => {
      if (x == null) return ''
      if (typeof x === 'string') return x
      if (typeof x === 'object') {
        const o = x as Record<string, unknown>
        return String(o.summary || o.request_type || o.status || o.id || JSON.stringify(x))
      }
      return String(x)
    }).filter(Boolean)
    return parts.length ? parts.join(' · ') : '—'
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function formatHistoryRow(row: unknown): string {
  if (row == null) return ''
  if (typeof row === 'string') return row
  if (typeof row !== 'object') return String(row)
  const o = row as Record<string, unknown>
  const ver = o.thesis_version != null ? `v${o.thesis_version}` : null
  const when = o.published_at != null ? String(o.published_at).slice(0, 10) : null
  const reason = o.reason_for_change || o.summary || o.stance
  return [ver, when, reason != null ? String(reason) : null].filter(Boolean).join(' · ')
}

export type SymbolThesisCardPayload = {
  ok?: boolean
  error?: string
  detail?: string
  symbol?: string
  portfolio_role?: string
  thesis_state?: string
  symbol_thesis_id?: string
  symbol_thesis_version?: string | number
  why_owned_or_watched?: string
  core_thesis?: string
  counter_thesis?: unknown
  research_gaps?: unknown
  active_research?: unknown
  recent_completed_research?: unknown
  what_changed?: string | null
  cio_action?: { bucket?: string; action?: string; why?: string } | null
  next_review_at?: string | null
  notification?: {
    notification_class?: string | null
    suppression_reason?: string | null
  } | null
  suppression_reason?: string | null
  /** Last N thesis revisions (from symbol-thesis or intelligence merge). */
  thesis_history?: unknown[]
  operator_stance?: string
  latest_feedback?: {
    intent?: string
    ts?: string
    free_text?: string
  } | null
  provenance?: {
    decision_origin?: string
  } | null
  what_changed_detail?: string
  technical_summary?: string
  causality?: string
  /** Phase D — fail-soft queue summary when CIO intelligence provides it. */
  research_queue_open_count?: number | null
  research_queue_oldest_wait_human?: string | null
}

export function SymbolThesisCard({ card: c }: { card: SymbolThesisCardPayload | null }) {
  const [busy, setBusy] = useState(false)
  const [savedIntent, setSavedIntent] = useState<string | null>(null)
  const [localFeedback, setLocalFeedback] = useState<SymbolThesisCardPayload['latest_feedback']>(null)

  const postFeedback = useCallback(async (intent: string) => {
    const sym = (c?.symbol || '').trim()
    if (!sym || busy) return
    setBusy(true)
    try {
      const r = await fetch(`/api/v3/cio/intelligence/${encodeURIComponent(sym)}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent, channel: 'command_center' }),
      })
      if (!r.ok) return // fail soft
      let j: any = null
      try { j = await r.json() } catch { /* soft */ }
      if (j && j.ok === false) return
      setSavedIntent(intent)
      setLocalFeedback({
        intent,
        ts: new Date().toISOString(),
        free_text: undefined,
      })
    } catch {
      /* fail soft — advisory only */
    } finally {
      setBusy(false)
    }
  }, [busy, c?.symbol])

  if (!c) return <div style={faint}>Select a symbol to load its living thesis.</div>
  if (c.ok === false) {
    return (
      <div data-testid="symbol-thesis-card-error" style={{ ...card, color: 'var(--amber)' }}>
        Thesis card unavailable{c.symbol ? ` for ${c.symbol}` : ''}: {c.error || c.detail || 'unknown error'}
      </div>
    )
  }
  const ntf = c.notification
  const suppress = c.suppression_reason || ntf?.suppression_reason
  const action = c.cio_action
  const history = Array.isArray(c.thesis_history) ? c.thesis_history.slice(0, 3) : []
  const feedback = localFeedback || c.latest_feedback
  const hasStanceOrFeedback = Boolean(c.operator_stance || feedback?.intent)
  const hasProvenance = Boolean(c.provenance?.decision_origin)
  const hasTech = Boolean(c.technical_summary)
  const hasCausality = Boolean(c.causality)
  const hasDetail = Boolean(c.what_changed_detail)
  const rqOpen = c.research_queue_open_count
  const hasQueueSummary = rqOpen != null && Number.isFinite(Number(rqOpen))
  const queueLabel = hasQueueSummary
    ? (Number(rqOpen) > 0
      ? `RESEARCH QUEUE ${Math.floor(Number(rqOpen))} open${c.research_queue_oldest_wait_human ? ` · oldest ${c.research_queue_oldest_wait_human}` : ''}`
      : 'RESEARCH QUEUE idle')
    : null

  return (
    <div data-testid="symbol-thesis-card" style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>{c.symbol || '—'}</div>
          <div style={faint}>
            Role {c.portfolio_role || 'UNKNOWN'}
            {' · '}
            {c.symbol_thesis_id || 'no thesis id'}
            {c.symbol_thesis_version != null ? ` ${String(c.symbol_thesis_version)}` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignSelf: 'flex-start' }}>
          {queueLabel && (
            <div
              data-research-queue={Number(rqOpen) > 0 ? String(Math.floor(Number(rqOpen))) : 'idle'}
              style={{
                fontSize: 11, fontWeight: 800, letterSpacing: '.4px',
                padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)',
                color: Number(rqOpen) > 0 ? 'var(--amber)' : 'var(--text2)',
              }}
            >
              {queueLabel}
            </div>
          )}
          <div style={{
            fontSize: 11, fontWeight: 800, letterSpacing: '.4px',
            padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)',
            color: c.thesis_state === 'RESEARCH_REQUIRED' ? 'var(--amber)' : 'var(--text2)',
          }}>
            {c.thesis_state || 'RESEARCH_REQUIRED'}
          </div>
        </div>
      </div>
      <Field label="Why own / watch">{c.why_owned_or_watched || '—'}</Field>
      <Field label="Case">{c.core_thesis || '—'}</Field>
      <Field label="Counter">{listText(c.counter_thesis)}</Field>
      <Field label="Gaps">{listText(c.research_gaps)}</Field>
      <Field label="Active research">{listText(c.active_research)}</Field>
      <Field label="Completed research">{listText(c.recent_completed_research)}</Field>
      <Field label="What changed">{c.what_changed || '—'}</Field>
      {hasDetail && (
        <Field label="What changed (detail)">{c.what_changed_detail}</Field>
      )}
      {history.length > 0 && (
        <Field label="Thesis history">
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {history.map((row, i) => (
              <li key={i} style={{ marginBottom: 2 }}>{formatHistoryRow(row) || '—'}</li>
            ))}
          </ul>
        </Field>
      )}
      {hasStanceOrFeedback && (
        <Field label="Operator stance / last feedback">
          {c.operator_stance ? `${c.operator_stance}` : '—'}
          {feedback?.intent
            ? ` · ${feedback.intent}${feedback.ts ? ` @ ${String(feedback.ts).slice(0, 16)}` : ''}${feedback.free_text ? ` — ${feedback.free_text}` : ''}`
            : ''}
        </Field>
      )}
      {hasProvenance && (
        <Field label="Provenance">{c.provenance?.decision_origin}</Field>
      )}
      {hasTech && (
        <Field label="Technical summary">{c.technical_summary}</Field>
      )}
      {hasCausality && (
        <Field label="Causality">{c.causality}</Field>
      )}
      <Field label="CIO action">
        {action
          ? `${action.bucket || '—'}${action.action ? ` · ${action.action}` : ''}${action.why ? ` — ${action.why}` : ''}`
          : '—'}
      </Field>
      <Field label="Next review">{c.next_review_at || '—'}</Field>
      {(ntf || suppress) && (
        <Field label="Notification / suppression">
          {ntf?.notification_class || '—'}
          {suppress ? ` · ${suppress}` : ''}
        </Field>
      )}

      <div style={{ marginTop: 14 }} data-testid="symbol-thesis-feedback">
        <div style={kLabel}>Feedback (advisory)</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 6 }}>
          {FEEDBACK_INTENTS.map(({ intent, label }) => {
            const active = (savedIntent || feedback?.intent) === intent
            return (
              <button
                key={intent}
                type="button"
                disabled={busy || !c.symbol}
                onClick={() => void postFeedback(intent)}
                style={active ? feedbackBtnActive : feedbackBtn}
                aria-label={`${label} feedback for ${c.symbol || 'symbol'}`}
              >
                {label}
              </button>
            )
          })}
        </div>
        {savedIntent && (
          <div style={{ ...faint, marginTop: 6 }} data-testid="symbol-thesis-feedback-saved">
            Saved: {savedIntent}
          </div>
        )}
      </div>
    </div>
  )
}
