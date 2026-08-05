/**
 * Rockville Watch Card v2 — one canonical deterministic state + subordinate LLM panel.
 * Feature-flagged. Advisory only. No orders / 2FA / broker writes.
 */
import { useMemo, useState } from 'react'

export type RockvilleDecision = {
  primary_state: string
  operator_meaning: string
  allowed_action_now: string
  proposal_allowed: boolean
  current_mechanics_visible: boolean
  blockers?: { code: string; message: string }[]
  blocking_drivers?: string[]
  supporting_drivers?: string[]
  conflicting_drivers?: string[]
  current_mechanics?: Record<string, unknown> | null
  wait_contract?: Record<string, unknown> | null
  history_mechanics_not_current?: Record<string, unknown> | null
  next_deterministic_review_condition?: string | null
  visibility?: Record<string, boolean>
}

export type RockvilleReview = {
  decision_summary?: string
  bull_case?: string
  counter_thesis?: string
  principal_risk?: string
  what_would_change_view?: string
  confidence?: number
  evidence_gaps?: string[]
  actionable_ticket_exists?: boolean
  provenance?: {
    model?: string
    policy?: string
    thinking?: boolean
    generated_at?: string
  }
  status?: string
  failure_code?: string | null
}

type Props = {
  symbol: string
  company?: string
  sector?: string
  last?: number | null
  dayChangePct?: number | null
  marketTs?: string | null
  decision: RockvilleDecision
  review?: RockvilleReview | null
  held?: boolean
  onRefresh?: () => void
  onViewEvidence?: () => void
}

const STATE_COLOR: Record<string, string> = {
  READY: '#22c55e',
  WAIT: '#f59e0b',
  REVIEW_PENDING: '#f59e0b',
  STALE: '#a3a3a3',
  AVOID: '#ef4444',
  BLOCKED: '#ef4444',
  DETERMINISTIC_FAIL: '#ef4444',
  DATA_UNAVAILABLE: '#a3a3a3',
  MANAGING: '#60a5fa',
}

function stateLabel(s: string) {
  if (s === 'DETERMINISTIC_FAIL') return 'DETERMINISTIC FAIL — NO TRADE MECHANICS'
  return s.replace(/_/g, ' ')
}

export default function WatchCardV2({
  symbol, company, sector, last, dayChangePct, marketTs, decision, review, held, onRefresh, onViewEvidence,
}: Props) {
  const [histOpen, setHistOpen] = useState(false)
  const color = STATE_COLOR[decision.primary_state] || 'var(--text2)'
  const showMech = decision.current_mechanics_visible && decision.primary_state === 'READY'
  const ctas = useMemo(() => {
    switch (decision.primary_state) {
      case 'READY':
        return ['REVIEW PROPOSAL', 'SET ALERT', 'VIEW EVIDENCE']
      case 'WAIT':
        return ['SET CONDITION ALERT', 'REFRESH', 'VIEW EVIDENCE']
      case 'REVIEW_PENDING':
        return ['VIEW REVIEW STATUS', 'REFRESH EVIDENCE']
      case 'STALE':
      case 'DATA_UNAVAILABLE':
        return ['REFRESH INPUTS', 'VIEW SOURCE HEALTH']
      case 'BLOCKED':
      case 'DETERMINISTIC_FAIL':
      case 'AVOID':
        return ['VIEW BLOCKERS', 'REQUEST DATA REVIEW', 'VIEW HISTORY']
      case 'MANAGING':
        return ['VIEW POSITION PLAN', 'REVIEW PROTECTION', 'VIEW JOURNAL']
      default:
        return ['VIEW EVIDENCE']
    }
  }, [decision.primary_state])

  return (
    <div
      style={{
        background: 'var(--bg1)',
        border: `1px solid ${color}55`,
        borderRadius: 12,
        padding: 14,
        marginBottom: 12,
      }}
      data-rockville-card
      data-symbol={symbol}
      data-primary-state={decision.primary_state}
      data-mechanics-visible={String(!!showMech)}
    >
      {/* A. Identity strip */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)' }}>
            {symbol}
            {company ? <span style={{ fontWeight: 600, color: 'var(--text2)', marginLeft: 8 }}>{company}</span> : null}
            {sector ? <span style={{ fontSize: 11, color: 'var(--text3)', marginLeft: 8 }}>{sector}</span> : null}
            {held ? <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 800, color: '#60a5fa' }}>HELD</span> : null}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)' }}>
            {last != null ? `$${Number(last).toFixed(2)}` : '—'}
            {dayChangePct != null && (
              <span style={{ marginLeft: 8, color: dayChangePct >= 0 ? '#22c55e' : '#ef4444', fontSize: 12 }}>
                {dayChangePct >= 0 ? '+' : ''}{dayChangePct.toFixed(2)}%
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>{marketTs || '—'}</div>
        </div>
      </div>

      {/* B. Canonical decision banner */}
      <div
        style={{
          marginTop: 10,
          padding: '10px 12px',
          borderRadius: 8,
          background: `${color}18`,
          border: `1px solid ${color}66`,
        }}
        data-decision-banner
      >
        <div style={{ fontSize: 13, fontWeight: 900, color, letterSpacing: 0.3 }}>{stateLabel(decision.primary_state)}</div>
        <div style={{ fontSize: 12, color: 'var(--text1)', marginTop: 4 }}>{decision.operator_meaning}</div>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
          Allowed now: <b style={{ color: 'var(--text0)' }}>{decision.allowed_action_now}</b>
          {' · '}Proposal eligibility: <b>{decision.proposal_allowed ? 'YES' : 'NO'}</b>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
        {/* C. LLM synthesis */}
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>DEEPSEEK SYNTHESIS</div>
          {review?.failure_code ? (
            <div style={{ fontSize: 11, color: '#ef4444' }}>LLM failure: {review.failure_code}</div>
          ) : review?.decision_summary ? (
            <>
              <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.4 }}>{review.decision_summary}</div>
              {review.bull_case && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6 }}><b>Bull:</b> {review.bull_case}</div>}
              {review.counter_thesis && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}><b>Counter:</b> {review.counter_thesis}</div>}
              {review.principal_risk && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}><b>Risk:</b> {review.principal_risk}</div>}
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>
                {review.provenance?.model || 'deepseek-v4-flash'}
                {review.provenance?.thinking ? ' · Thinking' : ''}
                {review.actionable_ticket_exists === false ? ' · no actionable ticket' : ''}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>
              No validated synthesis yet (paid Flash gated until flag enable).
            </div>
          )}
        </div>

        {/* Why blocked / drivers */}
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>
            {decision.primary_state === 'DETERMINISTIC_FAIL' || decision.primary_state === 'BLOCKED' ? 'WHY BLOCKED' : 'WHY NOW / WHY NOT'}
          </div>
          {(decision.blockers || []).slice(0, 4).map((b, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 4 }}>• {b.message}</div>
          ))}
          {!decision.blockers?.length && (decision.blocking_drivers || []).slice(0, 3).map((m, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 4 }}>• {m}</div>
          ))}
          {!decision.blockers?.length && !decision.blocking_drivers?.length && (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>—</div>
          )}
        </div>
      </div>

      {/* What happens next */}
      {decision.next_deterministic_review_condition && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text2)' }}>
          <b style={{ color: 'var(--text0)' }}>WHAT HAPPENS NEXT</b>
          <div style={{ marginTop: 4 }}>{decision.next_deterministic_review_condition}</div>
        </div>
      )}

      {/* D. Actionability — READY only */}
      {showMech && decision.current_mechanics && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, border: '1px solid #22c55e44', background: '#22c55e0d' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: '#22c55e' }}>VERIFIED MECHANICS</div>
          <pre style={{ fontSize: 10, color: 'var(--text2)', margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(decision.current_mechanics, null, 2)}
          </pre>
        </div>
      )}

      {decision.primary_state === 'WAIT' && decision.wait_contract && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, border: '1px solid #f59e0b44', background: '#f59e0b0d' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: '#f59e0b' }}>WAIT CONTRACT (NON-EXECUTABLE)</div>
          <div style={{ fontSize: 11, color: 'var(--text1)', marginTop: 4 }}>{String(decision.wait_contract.what_must_happen || '')}</div>
        </div>
      )}

      {/* History collapsed for invalid states */}
      {decision.history_mechanics_not_current && (
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            onClick={() => setHistOpen(v => !v)}
            style={{ fontSize: 10, color: 'var(--text3)', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            {histOpen ? '▼' : '▶'} HISTORY — NOT CURRENT
          </button>
          {histOpen && (
            <pre style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(decision.history_mechanics_not_current, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* G. CTAs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
        {ctas.map(c => (
          <button
            key={c}
            type="button"
            onClick={() => {
              if (c.includes('REFRESH') && onRefresh) onRefresh()
              if (c.includes('EVIDENCE') && onViewEvidence) onViewEvidence()
            }}
            style={{
              fontSize: 10,
              fontWeight: 800,
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: c.includes('PROPOSAL') && decision.proposal_allowed ? '#22c55e22' : 'var(--bg2)',
              color: 'var(--text1)',
              cursor: decision.proposal_allowed || !c.includes('PROPOSAL') ? 'pointer' : 'not-allowed',
              opacity: !decision.proposal_allowed && c.includes('PROPOSAL') ? 0.4 : 1,
            }}
            disabled={c.includes('PROPOSAL') && !decision.proposal_allowed}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  )
}
