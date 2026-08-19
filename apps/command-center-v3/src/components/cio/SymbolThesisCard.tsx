import { type CSSProperties, type ReactNode } from 'react'

/**
 * Living symbol-thesis card for CIO UNIVERSE & THESES.
 * Visual tokens match CioHub cards. Advisory only — no trade controls.
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
}

export function SymbolThesisCard({ card: c }: { card: SymbolThesisCardPayload | null }) {
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
        <div style={{
          alignSelf: 'flex-start', fontSize: 11, fontWeight: 800, letterSpacing: '.4px',
          padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)',
          color: c.thesis_state === 'RESEARCH_REQUIRED' ? 'var(--amber)' : 'var(--text2)',
        }}>
          {c.thesis_state || 'RESEARCH_REQUIRED'}
        </div>
      </div>
      <Field label="Why own / watch">{c.why_owned_or_watched || '—'}</Field>
      <Field label="Case">{c.core_thesis || '—'}</Field>
      <Field label="Counter">{listText(c.counter_thesis)}</Field>
      <Field label="Gaps">{listText(c.research_gaps)}</Field>
      <Field label="Active research">{listText(c.active_research)}</Field>
      <Field label="Completed research">{listText(c.recent_completed_research)}</Field>
      <Field label="What changed">{c.what_changed || '—'}</Field>
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
    </div>
  )
}
