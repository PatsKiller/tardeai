import { useState } from 'react'
import { TOKENS, FONT, RADIUS } from '../lib/designTokens'

type Status = {
  status: string
  as_of: string
  routing_order: string[]
  credit: { credit_used_usd?: string; reserved_usd?: string; estimated_credit_remaining_usd?: string; daily_cap_usd?: string; today_used_usd?: string; days_to_expiry?: number }
  usage: Record<string, { calls: number; usd: number | null; error_rate: number | null }>
  models: Record<string, { calls: number; usd: number | null }>
  last_success_at?: string | null
  last_error?: { code: string; at: string } | null
  last_fallback_reason?: string | null
  fallback_count: number
  ledger_coverage: string
  note?: string
}

export default function AnthropicCreditPanel({ status }: { status?: Status }) {
  const [expanded, setExpanded] = useState(false)
  const c = status?.credit
  const value = (v?: string) => v === undefined ? '—' : `$${Number(v).toFixed(4)}`
  return <section aria-label="Anthropic promotional credit" className="cc-panel" style={{ padding: 16, marginBottom: 14, color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
      <strong>Anthropic · promotional API</strong>
      <span role="status" style={{ color: status?.status === 'OK' ? TOKENS.success : TOKENS.warning }}>{status?.status?.replace(/_/g, ' ') ?? 'NOT MEASURED'}</span>
    </div>
    <p style={{ color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{status?.routing_order.join(' → ') ?? 'Routing evidence unavailable'}</p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(135px,1fr))', gap: 12, fontFamily: FONT.mono }}>
      <div>Credit used<br /><strong>{value(c?.credit_used_usd)}</strong></div>
      <div>Remaining estimate<br /><strong>{value(c?.estimated_credit_remaining_usd)}</strong></div>
      <div>UTC pace / day<br /><strong>{value(c?.today_used_usd)} / {value(c?.daily_cap_usd)}</strong></div>
      <div>Days to expiry<br /><strong>{c?.days_to_expiry?.toFixed(1) ?? '—'}</strong></div>
    </div>
    <p style={{ color: TOKENS.text[2], fontSize: 12 }}>Pending authorization {value(c?.reserved_usd)} · last fallback: {status?.last_fallback_reason ?? 'none observed'}.</p>
    <button type="button" aria-expanded={expanded} aria-controls="anthropic-credit-details" onClick={() => setExpanded(v => !v)} style={{ minHeight: 44, padding: '8px 12px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], cursor: 'pointer' }}>
      {expanded ? 'Hide provider details' : 'Show provider details'}
    </button>
    {expanded && <div id="anthropic-credit-details" style={{ overflowWrap: 'anywhere', marginTop: 12, fontSize: 13 }}>
      {(['today', 'seven_days'] as const).map(period => <p key={period}>{period === 'today' ? 'Today (UTC)' : 'Trailing 7 days'}: {status?.usage[period]?.calls ?? '—'} observed calls · ${status?.usage[period]?.usd?.toFixed(4) ?? '—'} · error rate {status?.usage[period]?.error_rate == null ? 'not measured' : `${(status.usage[period].error_rate! * 100).toFixed(1)}%`}</p>)}
      <p>Last success: {status?.last_success_at ?? 'not observed'}<br />Last error: {status?.last_error ? `${status.last_error.code} · ${status.last_error.at}` : 'not observed'}</p>
      <p>Fallbacks: {status?.fallback_count ?? '—'} · ledger coverage: {status?.ledger_coverage ?? 'not measured'}</p>
      <p>Trailing 7-day model usage</p>
      {Object.entries(status?.models ?? {}).map(([model, usage]) => <p key={model}>{model}: {usage.calls} calls · ${usage.usd?.toFixed(4) ?? 'not measured'}</p>)}
      <p>{status?.note ?? 'Remaining credit is estimated from local accounting; organization-wide usage may differ.'}</p>
      <p>Observed at {status?.as_of ?? 'unknown'}. Promotional calls are exempt from off-peak deferral; paid fallback retains its existing rules.</p>
    </div>}
  </section>
}
