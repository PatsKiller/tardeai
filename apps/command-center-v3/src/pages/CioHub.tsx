import { useEffect, useState, useMemo, useCallback } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill?: (ctx: any) => void }

const PRIORITY_COLOR: Record<string, string> = {
  P1: 'var(--red)', P2: 'var(--amber)', P3: 'var(--text3)',
}
const NOTIF_COLOR: Record<string, string> = {
  Critical: 'var(--red)',
  High: 'var(--orange)',
  Medium: 'var(--amber)',
  Low: 'var(--text3)',
  Info: 'var(--text3)',
}
const NOTIF_SORT: Record<string, number> = {
  Critical: 0, High: 1, Medium: 2, Low: 3, Info: 4,
}
const BIAS_EMOJI: Record<string, string> = {
  disposition_effect: '🧠',
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

type PlanOpt = { id?: string; label?: string; pros?: string; cons?: string }
type Plan = {
  plan_id?: string
  situation_type?: string
  symbols?: string[]
  status?: string
  title?: string
  summary?: string
  options?: PlanOpt[]
  recommendation?: string
  risks?: string[]
  evidence_refs?: any[]
  fire_reasons?: string[]
  thesis_version?: string
  narrative_source?: string
  llm_model?: string
  revisit_at?: string
  owner_agent?: string
  authority?: string
}

const card: React.CSSProperties = {
  background: 'var(--bg2)', borderRadius: 8, padding: 16,
  border: '1px solid var(--border)', marginBottom: 16,
}
const btnBase: React.CSSProperties = {
  padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', cursor: 'pointer', fontSize: 12, fontWeight: 600,
}

function PlanDetailPanel({
  planId,
  onDisposition,
}: {
  planId: string
  onDisposition?: () => void
}) {
  const [payload, setPayload] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setErr(null)
    fetch(`/api/v3/cio/plans/${encodeURIComponent(planId)}`, { cache: 'no-store' })
      .then(async r => {
        const j = await r.json()
        if (!r.ok || !j?.ok) throw new Error(j?.error || `HTTP ${r.status}`)
        setPayload(j)
      })
      .catch(e => setErr(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [planId])

  useEffect(() => { load() }, [load])

  const disposition = async (d: string) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await fetch(`/api/v3/cio/plans/${encodeURIComponent(planId)}/disposition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disposition: d }),
      })
      const j = await r.json()
      if (!r.ok || !j?.ok) throw new Error(j?.error || `HTTP ${r.status}`)
      setMsg(`${d} → status ${j.status} (READ_ONLY — no orders)`)
      setPayload((prev: any) => ({ ...prev, plan: j.plan }))
      onDisposition?.()
    } catch (e: any) {
      setMsg(`Failed: ${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div style={{ ...card, color: 'var(--text2)' }}>Loading plan {planId}…</div>
  if (err) return <div style={{ ...card, color: 'var(--red)' }}>Plan unavailable: {err}</div>

  const plan: Plan = payload?.plan || {}
  const thesis = payload?.thesis
  const opts = Array.isArray(plan.options) ? plan.options : []
  const risks = Array.isArray(plan.risks) ? plan.risks : []
  const refs = Array.isArray(plan.evidence_refs) ? plan.evidence_refs : []
  const fire = Array.isArray(plan.fire_reasons) ? plan.fire_reasons : []

  return (
    <div style={{ ...card, borderColor: 'var(--accent)' }} data-testid="cio-plan-detail">
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>📋 Plan</span>
        <code style={{ fontSize: 12, color: 'var(--accent)' }}>{plan.plan_id}</code>
        <StatusBadge status={plan.status === 'accepted' ? 'fresh' : 'warning'} label={String(plan.status || '—')} />
        {plan.narrative_source && (
          <span style={{ fontSize: 11, color: plan.narrative_source === 'llm' ? 'var(--accent)' : 'var(--text3)' }}>
            {plan.narrative_source === 'llm' ? '✨ Alex (LLM)' : '📋 template'}
          </span>
        )}
        {plan.thesis_version && (
          <span style={{ fontSize: 11, color: 'var(--text2)' }}>thesis {plan.thesis_version}</span>
        )}
      </div>

      <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 8 }}>
        {(plan.situation_type || '').replace(/_/g, ' ')}
        {plan.symbols?.length ? ` · ${plan.symbols.join(', ')}` : ''}
        {plan.owner_agent ? ` · owner ${plan.owner_agent}` : ''}
      </div>

      {thesis && (
        <div style={{
          background: 'var(--bg)', borderRadius: 6, padding: 10, marginBottom: 12,
          border: '1px solid var(--border)',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
            🎯 Desk thesis {thesis.thesis_version || plan.thesis_version}
            {thesis.stance ? ` · ${thesis.stance}` : ''}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>{thesis.summary}</div>
          {Array.isArray(thesis.bullets) && thesis.bullets.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 11, color: 'var(--text3)' }}>
              {thesis.bullets.slice(0, 4).map((b: string, i: number) => <li key={i}>{b}</li>)}
            </ul>
          )}
        </div>
      )}

      {fire.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 8 }}>
          Why: {fire.join(', ')}
        </div>
      )}

      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>What</div>
      <div style={{ fontSize: 13, color: 'var(--text)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>
        {plan.summary || plan.title || '—'}
      </div>

      {opts.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>Options</div>
          <div style={{ marginBottom: 12 }}>
            {opts.map((o, i) => (
              <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <div style={{ color: 'var(--text)', fontWeight: 600 }}>
                  {i + 1}. {o.label || o.id || 'Option'}
                </div>
                {o.pros && <div style={{ color: 'var(--green)', marginTop: 2 }}>+ {o.pros}</div>}
                {o.cons && <div style={{ color: 'var(--red)', marginTop: 2 }}>− {o.cons}</div>}
              </div>
            ))}
          </div>
        </>
      )}

      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Recommendation</div>
      <div style={{ fontSize: 13, color: 'var(--accent)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>
        {plan.recommendation || '—'}
      </div>

      {risks.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Risks</div>
          <ul style={{ margin: '0 0 12px', paddingLeft: 18, fontSize: 12, color: 'var(--text2)' }}>
            {risks.map((r, i) => <li key={i}>{String(r)}</li>)}
          </ul>
        </>
      )}

      {refs.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Evidence</div>
          <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--text3)' }}>
            {refs.slice(0, 8).map((r: any, i: number) => (
              <div key={i}>• {r?.domain || '?'} · {String(r?.as_of || '').slice(0, 10) || 'n/a'}</div>
            ))}
          </div>
        </>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
        <button style={{ ...btnBase, background: 'var(--accent)', color: 'var(--text0)' }} disabled={busy}
          onClick={() => disposition('ack')}>Ack</button>
        <button style={btnBase} disabled={busy} onClick={() => disposition('defer')}>Defer</button>
        <button style={btnBase} disabled={busy} onClick={() => disposition('done')}>Done</button>
        <button style={{ ...btnBase, color: 'var(--red)' }} disabled={busy}
          onClick={() => disposition('reject')}>Reject</button>
        <button style={btnBase} disabled={busy} onClick={load}>Refresh</button>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>
        Disposition updates plan status only · READ_ONLY_ADVISORY · no orders/stops
        {plan.revisit_at ? ` · revisit ${String(plan.revisit_at).slice(0, 10)}` : ''}
      </div>
      {msg && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 6 }}>{msg}</div>}
    </div>
  )
}

export default function CioHub({ onDrill }: Props) {
  const [tab, setTab] = useState<'overview' | 'plans' | 'actions' | 'delegation' | 'hermes'>('overview')
  const [sp, setSp] = useSearchParams()
  const planId = (sp.get('plan') || '').trim()
  const { data, loading, error, refetch } = useApi<any>('/api/v3/cio')

  // Auto-focus plans tab when deep-linked
  useEffect(() => {
    if (planId) setTab('plans')
  }, [planId])

  const snapshot = data?.snapshot
  const actions = useMemo(() => {
    const list = data?.actions ?? []
    return [...list].sort((a: any, b: any) => {
      const sa = NOTIF_SORT[a.notification_priority] ?? 4
      const sb = NOTIF_SORT[b.notification_priority] ?? 4
      if (sa !== sb) return sa - sb
      return (b.created_at || '').localeCompare(a.created_at || '')
    })
  }, [data?.actions])
  const plans: Plan[] = data?.plans ?? []
  const thesis = data?.thesis
  const thesisVersion = data?.thesis_version || thesis?.thesis_version
  const delegation = data?.delegation
  const domains = snapshot?.domains ?? {}
  const health = snapshot?.health ?? {}

  const openPlan = (id: string) => {
    const next = new URLSearchParams(sp)
    next.set('plan', id)
    setSp(next, { replace: false })
    setTab('plans')
  }

  if (loading && !data) return <div style={{ padding: 32, color: 'var(--text2)' }}>Loading CIO dashboard…</div>
  if (error && !data) return <div style={{ padding: 32, color: 'var(--red)' }}>CIO data unavailable: {String(error)}</div>

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200 }}>
      <div style={hubTitle()}>🏦 CIO Command Center</div>
      <div style={hubSubtitle()}>
        Alex · Chief Investment & Wealth Officer · READ_ONLY_ADVISORY
        {thesisVersion && <span style={{ color: 'var(--accent)', marginLeft: 12 }}>thesis {thesisVersion}</span>}
        {data?.as_of && <span style={{ color: 'var(--text3)', marginLeft: 16 }}>As of: {new Date(data.as_of).toLocaleString()}</span>}
      </div>

      {/* Deep-linked plan always on top */}
      {planId && (
        <PlanDetailPanel planId={planId} onDisposition={() => refetch?.()} />
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, marginTop: 12, flexWrap: 'wrap' }}>
        {(['overview', 'plans', 'actions', 'delegation', 'hermes'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px', borderRadius: 6, border: '1px solid var(--border)',
              background: tab === t ? 'var(--accent)' : 'var(--bg2)',
              color: tab === t ? 'var(--text0)' : 'var(--text2)', cursor: 'pointer',
              fontSize: 13, fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === 'overview' ? '📊 Overview'
              : t === 'plans' ? `📋 Plans (${plans.length})`
              : t === 'actions' ? `⚡ Actions (${actions.length})`
              : t === 'delegation' ? '🤝 Delegation' : '🔬 Hermes'}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div>
          {thesis && (
            <div style={card}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>
                🎯 Active desk thesis · {thesisVersion}
                {thesis.stance ? ` · ${thesis.stance}` : ''}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text2)' }}>{thesis.summary}</div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
            {[
              { label: 'Portfolio', value: fmtUSD(domains.portfolio?.total_value), sub: fmtPct(domains.portfolio?.day_change_pct), state: domains.portfolio?.state },
              { label: 'Portfolio Heat', value: domains.risk?.portfolio_heat_pct != null ? `${domains.risk.portfolio_heat_pct.toFixed(1)}%` : '—', sub: `${domains.risk?.stops_active ?? 0} stops`, state: domains.risk?.state },
              { label: 'Holdings', value: domains.portfolio?.holdings_count ?? '—', sub: 'positions', state: domains.portfolio?.state },
              { label: 'Open plans', value: plans.length, sub: 'advisory', state: 'AVAILABLE' },
            ].map((c, i) => (
              <div key={i} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '12px 16px', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>{c.label}</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>{c.value}</div>
                <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>{c.sub}</div>
                <div style={{ marginTop: 6 }}>
                  <StatusBadge status={c.state === 'AVAILABLE' ? 'fresh' : 'blocked'} label={String(c.state || 'unknown')} />
                </div>
              </div>
            ))}
          </div>

          <div style={card}>
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

          {plans.length > 0 && (
            <div style={card}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>Open advisory plans</div>
              {plans.slice(0, 6).map((p, i) => (
                <div
                  key={p.plan_id || i}
                  onClick={() => p.plan_id && openPlan(p.plan_id)}
                  style={{
                    padding: '8px 0', cursor: p.plan_id ? 'pointer' : 'default',
                    borderBottom: i < Math.min(plans.length, 6) - 1 ? '1px solid var(--border)' : 'none',
                  }}
                >
                  <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}>{p.plan_id}</span>
                  <span style={{ color: 'var(--text2)', fontSize: 12, marginLeft: 8 }}>
                    {(p.situation_type || '').replace(/_/g, ' ')}
                    {p.symbols?.length ? ` · ${p.symbols.join(',')}` : ''}
                  </span>
                  <div style={{ color: 'var(--text)', fontSize: 13, marginTop: 2 }}>
                    {(p.summary || p.recommendation || '').slice(0, 140)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'plans' && (
        <div>
          {!planId && (
            <div style={{ color: 'var(--text3)', fontSize: 12, marginBottom: 12 }}>
              Select a plan or open a Telegram deep link <code>/v3/cio?plan=&lt;id&gt;</code>
            </div>
          )}
          <div style={card}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'var(--text)' }}>
              Open plans · {plans.length}
            </div>
            {plans.length === 0 && (
              <div style={{ color: 'var(--text3)', padding: 12 }}>No open plans.</div>
            )}
            {plans.map((p, i) => (
              <div
                key={p.plan_id || i}
                onClick={() => p.plan_id && openPlan(p.plan_id)}
                style={{
                  padding: '10px 0', cursor: 'pointer',
                  borderBottom: '1px solid var(--border)',
                  background: p.plan_id === planId ? 'var(--bg)' : undefined,
                  borderRadius: 4,
                }}
              >
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <code style={{ fontSize: 12, color: 'var(--accent)' }}>{p.plan_id}</code>
                  <StatusBadge status={p.status === 'accepted' ? 'fresh' : 'warning'} label={String(p.status || '')} />
                  <span style={{ fontSize: 12, color: 'var(--text2)' }}>
                    {(p.situation_type || '').replace(/_/g, ' ')}
                    {p.symbols?.length ? ` · ${p.symbols.join(', ')}` : ''}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: 'var(--text)', marginTop: 4 }}>
                  {(p.summary || '').slice(0, 200)}
                </div>
                {p.recommendation && (
                  <div style={{ fontSize: 12, color: 'var(--accent)', marginTop: 2 }}>
                    → {(p.recommendation || '').slice(0, 160)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'actions' && (
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'var(--text)' }}>CIO Action Ledger · {actions.length} open</div>
          {actions.map((a: any, i: number) => (
            <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ color: NOTIF_COLOR[a.notification_priority] ?? NOTIF_COLOR[a.priority] ?? 'var(--text3)', fontWeight: 700, fontSize: 12 }}>
                  {a.notification_priority || a.priority}
                </span>
                <span style={{ color: 'var(--accent)', fontSize: 12 }}>{a.cio_action_id}</span>
                <span style={{ color: 'var(--text3)', fontSize: 11 }}>· {a.domain}</span>
                <StatusBadge status={a.status === 'OPEN' ? 'warning' : 'fresh'} label={String(a.status || '')} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: 'var(--text)', fontSize: 13 }}>{a.title || a.recommendation}</span>
                {a.bias_flag && (
                  <span style={{ color: 'var(--accent)', fontSize: 10 }} title={a.bias_flag}>
                    {BIAS_EMOJI[a.bias_flag] || '🧠'} {a.bias_flag.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
              {a.why_now && <div style={{ color: 'var(--text2)', fontSize: 12, marginTop: 2 }}>{a.why_now}</div>}
            </div>
          ))}
          {actions.length === 0 && <div style={{ color: 'var(--text3)', padding: 16 }}>No open actions — portfolio is stable.</div>}
        </div>
      )}

      {tab === 'delegation' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={card}>
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
          </div>
          <div style={card}>
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
          </div>
        </div>
      )}

      {tab === 'hermes' && (
        <div style={card}>
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

      <div style={{ marginTop: 24, padding: 12, background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)', fontSize: 11, color: 'var(--text3)' }}>
        READ_ONLY_ADVISORY · Model: {data?.model_provider ?? 'deepseek-v4-pro'} · No broker/order/risk/2FA authority
        {' · '}
        <Link to="/advisory" style={{ color: 'var(--accent)' }}>Advisory desk</Link>
      </div>
    </div>
  )
}
