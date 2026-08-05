/**
 * Rockville Watch Card v2 — one canonical deterministic state + subordinate LLM panel.
 * Feature-flagged. Advisory only. No orders / 2FA / broker writes.
 * Design tokens: BB/TYPE only — no raw hex (design-guard).
 */
import { useMemo, useState } from 'react'
import { BB, TYPE } from '../../lib/watchTokens'

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
  priceSource?: string | null
  quoteId?: string | number | null
  sourceRecordId?: string | null
  marketSession?: string | null
  freshnessState?: string | null
  marketState?: string | null
  decision: RockvilleDecision
  review?: RockvilleReview | null
  held?: boolean
  onRefresh?: () => void
  onViewEvidence?: () => void
}

function stateColor(s: string): string {
  if (s === 'READY') return BB.green
  if (s === 'WAIT' || s === 'REVIEW_PENDING') return BB.amber
  if (s === 'MANAGING') return BB.text2
  if (s === 'STALE' || s === 'DATA_UNAVAILABLE') return BB.text3
  return BB.red
}

function stateLabel(s: string) {
  if (s === 'DETERMINISTIC_FAIL') return 'DETERMINISTIC FAIL — NO TRADE MECHANICS'
  return s.replace(/_/g, ' ')
}

function fmtPrice(last?: number | null) {
  if (last == null || !Number.isFinite(Number(last))) return '—'
  return `$${Number(last).toFixed(2)}`
}

function fmtChg(pct?: number | null) {
  if (pct == null || !Number.isFinite(Number(pct))) return null
  const n = Number(pct)
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function freshnessColor(fs?: string | null): string {
  if (!fs || fs === 'DATA_UNAVAILABLE') return BB.red
  if (fs === 'STALE') return BB.amber
  if (fs === 'CURRENT' || fs === 'AFTER_HOURS_CURRENT' || fs === 'PREMARKET_CURRENT') return BB.green
  return BB.text3
}

export default function WatchCardV2({
  symbol, company, sector, last, dayChangePct, marketTs, priceSource,
  quoteId, sourceRecordId, marketSession, freshnessState, marketState,
  decision, review, held, onRefresh, onViewEvidence,
}: Props) {
  const [histOpen, setHistOpen] = useState(false)
  const [provOpen, setProvOpen] = useState(false)
  const color = stateColor(decision.primary_state)
  const showMech = decision.current_mechanics_visible && decision.primary_state === 'READY'
  const chg = fmtChg(dayChangePct)
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
        background: BB.bgPanel,
        border: `1px solid ${BB.border}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 12,
        padding: 14,
        marginBottom: 12,
      }}
      data-rockville-card
      data-symbol={symbol}
      data-primary-state={decision.primary_state}
      data-mechanics-visible={String(!!showMech)}
      data-company={company || ''}
      data-quote-id={quoteId != null ? String(quoteId) : ''}
      data-source-record-id={sourceRecordId || ''}
      data-market-session={marketSession || ''}
      data-freshness-state={freshnessState || ''}
      data-market-state={marketState || ''}
      data-price-source={priceSource || ''}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>
            {symbol}
            {company ? <span style={{ fontWeight: 600, color: BB.text2, marginLeft: 8 }}>{company}</span> : null}
            {sector ? <span style={{ fontSize: TYPE.sm, color: BB.text3, marginLeft: 8 }}>{sector}</span> : null}
            {held ? <span style={{ marginLeft: 8, fontSize: TYPE.xs, fontWeight: 800, color: BB.green }}>HELD</span> : null}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>
            {fmtPrice(last)}
            {chg && (
              <span style={{
                marginLeft: 8,
                color: Number(dayChangePct) >= 0 ? BB.green : BB.red,
                fontSize: TYPE.base,
              }}>
                {chg}
              </span>
            )}
          </div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            {marketTs || '—'}
            {priceSource ? ` · ${priceSource}` : ''}
          </div>
          <div
            style={{ fontSize: TYPE.xs, color: freshnessColor(freshnessState), marginTop: 2, fontWeight: 700 }}
            data-provenance-line
          >
            {freshnessState || 'DATA_UNAVAILABLE'}
            {marketSession ? ` · ${marketSession}` : ''}
            {marketState ? ` · mkt ${marketState}` : ''}
          </div>
          <button
            type="button"
            onClick={() => setProvOpen(v => !v)}
            style={{
              fontSize: TYPE.xs,
              color: BB.text3,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
              marginTop: 2,
            }}
            data-provenance-toggle
          >
            {provOpen ? '▼' : '▶'} quote identity
          </button>
          {provOpen && (
            <div
              style={{
                marginTop: 4,
                textAlign: 'left',
                fontSize: TYPE.xs,
                color: BB.text2,
                background: BB.bgShift,
                border: `1px solid ${BB.border}`,
                borderRadius: 6,
                padding: 8,
              }}
              data-provenance-drawer
            >
              <div>quote_id: {quoteId != null ? String(quoteId) : '—'}</div>
              <div>source_record_id: {sourceRecordId || '—'}</div>
              <div>session: {marketSession || '—'}</div>
              <div>freshness: {freshnessState || '—'}</div>
              <div>market_state: {marketState || '—'}</div>
              <div>price_source: {priceSource || '—'}</div>
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          marginTop: 10,
          padding: '10px 12px',
          borderRadius: 8,
          background: BB.bgShift,
          border: `1px solid ${BB.border}`,
        }}
        data-decision-banner
      >
        <div style={{ fontSize: TYPE.base, fontWeight: 900, color, letterSpacing: 0.3 }}>{stateLabel(decision.primary_state)}</div>
        <div style={{ fontSize: TYPE.base, color: BB.text1, marginTop: 4 }}>{decision.operator_meaning}</div>
        <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 4 }}>
          Allowed now: <b style={{ color: BB.text0 }}>{decision.allowed_action_now}</b>
          {' · '}Proposal eligibility: <b>{decision.proposal_allowed ? 'YES' : 'NO'}</b>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
        <div style={{ background: BB.bgShift, borderRadius: 8, padding: 10, border: `1px solid ${BB.border}` }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, marginBottom: 6 }}>DEEPSEEK SYNTHESIS</div>
          {review?.failure_code ? (
            <div style={{ fontSize: TYPE.sm, color: BB.red }}>LLM failure: {review.failure_code}</div>
          ) : review?.decision_summary ? (
            <>
              <div style={{ fontSize: TYPE.base, color: BB.text1, lineHeight: 1.4 }}>{review.decision_summary}</div>
              {review.bull_case && <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 6 }}><b>Bull:</b> {review.bull_case}</div>}
              {review.counter_thesis && <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 4 }}><b>Counter:</b> {review.counter_thesis}</div>}
              {review.principal_risk && <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 4 }}><b>Risk:</b> {review.principal_risk}</div>}
              <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
                {review.provenance?.model || 'no validated synthesis'}
                {review.provenance?.thinking ? ' · Thinking' : ''}
                {review.actionable_ticket_exists === false ? ' · no actionable ticket' : ''}
              </div>
            </>
          ) : (
            <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
              No validated synthesis yet (paid Flash gated until flag enable).
            </div>
          )}
        </div>

        <div style={{ background: BB.bgShift, borderRadius: 8, padding: 10, border: `1px solid ${BB.border}` }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, marginBottom: 6 }}>
            {decision.primary_state === 'DETERMINISTIC_FAIL' || decision.primary_state === 'BLOCKED' ? 'WHY BLOCKED' : 'WHY NOW / WHY NOT'}
          </div>
          {(decision.blockers || []).slice(0, 4).map((b, i) => (
            <div key={i} style={{ fontSize: TYPE.sm, color: BB.text1, marginBottom: 4 }}>• {b.message}</div>
          ))}
          {!decision.blockers?.length && (decision.blocking_drivers || []).slice(0, 3).map((m, i) => (
            <div key={i} style={{ fontSize: TYPE.sm, color: BB.text1, marginBottom: 4 }}>• {m}</div>
          ))}
          {!decision.blockers?.length && !decision.blocking_drivers?.length && (
            <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>—</div>
          )}
        </div>
      </div>

      {decision.next_deterministic_review_condition && (
        <div style={{ marginTop: 10, fontSize: TYPE.sm, color: BB.text2 }}>
          <b style={{ color: BB.text0 }}>WHAT HAPPENS NEXT</b>
          <div style={{ marginTop: 4 }}>{decision.next_deterministic_review_condition}</div>
        </div>
      )}

      {showMech && decision.current_mechanics && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, border: `1px solid ${BB.border}`, background: BB.bgShift }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.green }}>VERIFIED MECHANICS</div>
          <pre style={{ fontSize: TYPE.xs, color: BB.text2, margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(decision.current_mechanics, null, 2)}
          </pre>
        </div>
      )}

      {decision.primary_state === 'WAIT' && decision.wait_contract && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, border: `1px solid ${BB.border}`, background: BB.bgShift }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.amber }}>WAIT CONTRACT (NON-EXECUTABLE)</div>
          <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 4 }}>{String(decision.wait_contract.what_must_happen || '')}</div>
        </div>
      )}

      {decision.history_mechanics_not_current && (
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            onClick={() => setHistOpen(v => !v)}
            style={{ fontSize: TYPE.xs, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            {histOpen ? '▼' : '▶'} HISTORY — NOT CURRENT
          </button>
          {histOpen && (
            <pre style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(decision.history_mechanics_not_current, null, 2)}
            </pre>
          )}
        </div>
      )}

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
              fontSize: TYPE.xs,
              fontWeight: 800,
              padding: '6px 10px',
              borderRadius: 6,
              border: `1px solid ${BB.border}`,
              background: BB.bgShift,
              color: BB.text1,
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
