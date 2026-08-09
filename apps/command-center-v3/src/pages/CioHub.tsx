import { useEffect, useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill?: (ctx: any) => void }

const PRIORITY_COLOR: Record<string, string> = {
  P1: 'var(--red)', P2: 'var(--amber)', P3: 'var(--text3)',
}
const STATE_COLOR: Record<string, string> = {
  AVAILABLE: 'var(--green)', DATA_UNAVAILABLE: 'var(--red)', STALE: 'var(--amber)',
}

function fmtUSD(n: number | null | undefined) {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
}

export default function CioHub({ onDrill }: Props) {
  const [tab, setTab] = useState<'overview' | 'actions' | 'delegation' | 'hermes'>('overview')
  const { data, loading, error } = useApi<any>('/api/v3/cio')

  const snapshot = data?.snapshot
  const actions = data?.actions ?? []
  const delegation = data?.delegation
  const domains = snapshot?.domains ?? {}
  const health = snapshot?.health ?? {}

  if (loading) return <div style={{ padding: 32, color: 'var(--text2)' }}>Loading CIO dashboard…</div>
  if (error) return <div style={{ padding: 32, color: 'var(--red)' }}>CIO data unavailable: {String(error)}</div>

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200 }}>
      <div style={hubTitle}>🏦 CIO Command Center</div>
      <div style={hubSubtitle}>
        Alex · Chief Investment & Wealth Officer · DeepSeek V4 Pro · Advisory Only
        {data?.as_of && <span style={{ color: 'var(--text3)', marginLeft: 16 }}>As of: {new Date(data.as_of).toLocaleString()}</span>}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, marginTop: 12 }}>
        {(['overview', 'actions', 'delegation', 'hermes'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px', borderRadius: 6, border: '1px solid var(--border)',
              background: tab === t ? 'var(--accent)' : 'var(--bg2)',
              color: tab === t ? '#fff' : 'var(--text2)', cursor: 'pointer',
              fontSize: 13, fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === 'overview' ? '📊 Overview' : t === 'actions' ? `📋 Actions (${actions.length})` : t === 'delegation' ? '🤝 Delegation' : '🔬 Hermes'}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div>
          {/* Portfolio strip */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
            {[
              { label: 'Portfolio', value: fmtUSD(domains.portfolio?.total_value), sub: fmtPct(domains.portfolio?.day_change_pct), state: domains.portfolio?.state },
              { label: 'Portfolio Heat', value: domains.risk?.portfolio_heat_pct != null ? `${domains.risk.portfolio_heat_pct.toFixed(1)}%` : '—', sub: `${domains.risk?.stops_active ?? 0} stops`, state: domains.risk?.state },
              { label: 'Holdings', value: domains.portfolio?.holdings_count ?? '—', sub: 'positions', state: domains.portfolio?.state },
              { label: 'Annual Dividend Est', value: fmtUSD(domains.income?.annual_dividend_est), sub: 'estimated', state: domains.income?.state },
            ].map((card, i) => (
              <div key={i} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '12px 16px', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>{card.label}</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>{card.value}</div>
                <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>{card.sub}</div>
                <div style={{ marginTop: 6 }}>
                  <StatusBadge status={card.state === 'AVAILABLE' ? 'fresh' : 'blocked'}>{card.state}</StatusBadge>
                </div>
              </div>
            ))}
          </div>

          {/* Domain health */}
          <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)', marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: 'var(--text)' }}>
              Domain Health · {health.domains_available}/{health.domains_total} available
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {Object.entries(domains).map(([domain, d]: [string, any]) => (
                <span key={domain} style={{
                  padding: '4px 10px', borderRadius: 4, fontSize: 12,
                  background: d.state === 'AVAILABLE' ? 'var(--green-ghost)' : d.state === 'STALE' ? 'var(--amber-ghost)' : 'var(--red-ghost)',
                  color: STATE_COLOR[d.state] ?? 'var(--text3)',
                }}>
                  {domain} · {d.state}
                </span>
              ))}
            </div>
          </div>

          {/* Top actions */}
          {actions.length > 0 && (
            <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>Top Actions</div>
              {actions.slice(0, 5).map((a: any, i: number) => (
                <div key={i} style={{ padding: '6px 0', borderBottom: i < Math.min(actions.length, 5) - 1 ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ color: PRIORITY_COLOR[a.priority] ?? 'var(--text3)', fontWeight: 600, marginRight: 8 }}>
                    {a.priority}
                  </span>
                  <span style={{ color: 'var(--text2)', fontSize: 13 }}>{(a.title || a.recommendation || '')}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 11, marginLeft: 8 }}>· {a.domain}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'actions' && (
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'var(--text)' }}>CIO Action Ledger · {actions.length} open</div>
          {actions.map((a: any, i: number) => (
            <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ color: PRIORITY_COLOR[a.priority] ?? 'var(--text3)', fontWeight: 700, fontSize: 12 }}>
                  {a.priority}
                </span>
                <span style={{ color: 'var(--accent)', fontSize: 12 }}>{a.cio_action_id}</span>
                <span style={{ color: 'var(--text3)', fontSize: 11 }}>· {a.domain}</span>
                <StatusBadge status={a.status === 'OPEN' ? 'warning' : 'fresh'}>{a.status}</StatusBadge>
              </div>
              <div style={{ color: 'var(--text)', fontSize: 13 }}>{a.title || a.recommendation}</div>
              {a.why_now && <div style={{ color: 'var(--text2)', fontSize: 12, marginTop: 2 }}>{a.why_now}</div>}
            </div>
          ))}
          {actions.length === 0 && <div style={{ color: 'var(--text3)', padding: 16 }}>No open actions — portfolio is stable.</div>}
        </div>
      )}

      {tab === 'delegation' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>🤝 Specialist Handoffs</div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 12 }}>
              Total: {delegation?.handoffs?.total ?? 0} · Latest: {delegation?.handoffs?.latest?.event_type ?? '—'}
            </div>
            {delegation?.handoffs?.statuses && Object.entries(delegation.handoffs.statuses).map(([status, count]: [string, any]) => (
              <div key={status} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                <span style={{ color: 'var(--text2)', fontSize: 13 }}>{status}</span>
                <span style={{ color: 'var(--text)', fontWeight: 600 }}>{count}</span>
              </div>
            ))}
            <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text3)' }}>
              Maria: AVAILABLE · Steph: NOT_READY · Guardian: NOT_READY · Ledger: NOT_READY
            </div>
          </div>

          <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>🔬 Hermes Challenges</div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 12 }}>
              Total: {delegation?.challenges?.total ?? 0} · Latest: {delegation?.challenges?.latest?.event_type ?? '—'}
            </div>
            {delegation?.challenges?.statuses && Object.entries(delegation.challenges.statuses).map(([status, count]: [string, any]) => (
              <div key={status} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                <span style={{ color: 'var(--text2)', fontSize: 13 }}>{status}</span>
                <span style={{ color: 'var(--text)', fontWeight: 600 }}>{count}</span>
              </div>
            ))}
            {delegation?.challenges?.latest?.challenge_type && (
              <div style={{ marginTop: 12, fontSize: 12, color: 'var(--accent)' }}>
                Latest type: {delegation.challenges.latest.challenge_type}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'hermes' && (
        <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 16, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'var(--text)' }}>🔬 Hermes Research Intelligence</div>
          {(() => {
            const h = domains.hermes_research ?? {}
            return (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
                  {[
                    { label: 'Promoted', value: h.promoted_research_count ?? 0 },
                    { label: 'Staged', value: h.staged_research_count ?? 0 },
                    { label: 'Model', value: h.model_provider ?? 'deepseek-v4-flash' },
                  ].map((m, i) => (
                    <div key={i} style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent)' }}>{m.value}</div>
                      <div style={{ fontSize: 11, color: 'var(--text3)' }}>{m.label}</div>
                    </div>
                  ))}
                </div>
                {h.latest_topics?.length > 0 && (
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>Latest Research Topics</div>
                    {h.latest_topics.map((t: string, i: number) => (
                      <div key={i} style={{ padding: '3px 0', fontSize: 12, color: 'var(--text2)' }}>· {t}</div>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      {/* Authority footer */}
      <div style={{ marginTop: 24, padding: 12, background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)', fontSize: 11, color: 'var(--text3)' }}>
        READ_ONLY_ADVISORY · Model: {data?.model_provider ?? 'deepseek-v4-pro'} · Fallback: {data?.fallback ?? 'deepseek-v4-flash → free-oauth'} · No broker/order/risk/2FA authority
      </div>
    </div>
  )
}
