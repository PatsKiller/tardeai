import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { StateCard } from '../components/StateCard'
import { StatusBadge } from '../components/StatusBadge'
import CoderDispatchLedger from '../components/health/CoderDispatchLedger'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill?: (ctx: DrillContext) => void }

const SEV_COLOR: Record<string, string> = {
  critical: 'var(--red)', warning: 'var(--amber)', info: 'var(--text3)',
}
const STATUS_COLOR: Record<string, string> = {
  fixed: 'var(--green)', pr_opened: 'var(--green)', advisory_diff: 'var(--green)', verified: 'var(--green)',
  queued: 'var(--amber)', investigating: 'var(--accent)', attempted: 'var(--amber)',
  detected: 'var(--text3)', no_changes: 'var(--text3)',
  verify_failed: 'var(--red)', error: 'var(--red)', no_backend_available: 'var(--red)',
}
const STATUS_TO_BADGE: Record<string, string> = {
  healthy: 'fresh', degraded: 'warning', unhealthy: 'blocked', unknown: 'unknown',
}
const scoreColor = (s: number | null | undefined) =>
  s == null ? 'var(--text3)' : s >= 85 ? 'var(--green)' : s >= 65 ? 'var(--amber)' : 'var(--red)'

const CAT_LABEL: Record<string, string> = {
  data_quality: 'Data Quality', execution_health: 'Execution Health',
  intelligence_quality: 'Intelligence', risk_protection: 'Risk Protection',
  retirement_planning: 'Retirement',
}
const CAT_HELP: Record<string, string> = {
  data_quality: 'Freshness of holdings, risk, dividends, news, CIO decisions, agent jobs + open data gaps.',
  execution_health: 'Pipeline failures, stuck agent jobs, critical execution escalations, orphaned stops.',
  intelligence_quality: 'Local LLM reachability, ensemble failures, stale research backlog.',
  risk_protection: 'Unprotected open positions, stops in alert state, recent P0/P1 SIEM alerts.',
  retirement_planning: 'Golden Window present, dividend income consistency, dividend calendar freshness.',
}
const TAB_HELP: Record<string, string> = {
  overview: 'Overall 0–100 health score, per-category breakdown, degrading trends, and active findings.',
  coders: 'Dispatch queue, full ledger (problem → coder → outcome), PR/diff links, and backend routing.',
  history: 'Score trend over recent cron runs (every 30 min) with per-run context: what degraded, finding counts, deltas.',
}

function fmtWhen(s?: string) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

function deltaStr(d: number | null | undefined) {
  if (d == null || d === 0) return null
  const sign = d > 0 ? '+' : ''
  return `${sign}${d}`
}

export default function HealthHub({ onDrill }: Props) {
  const [tab, setTab] = useState<'overview' | 'coders' | 'history'>('overview')
  const { data: health, loading, error } = useApi<any>('/api/v2/health', 120_000)
  const { data: coders } = useApi<any>('/api/v2/health/coders', 120_000)
  const { data: dispatches, loading: dispLoading } = useApi<any>('/api/v2/health/dispatches', 60_000)
  const { data: hist } = useApi<any>('/api/v2/health/history', 300_000)
  const { data: activity, refetch: refetchActivity } = useApi<any>('/api/v2/health/activity', 60_000)
  const [acting, setActing] = useState<Record<string, string>>({})
  const [histExpanded, setHistExpanded] = useState<number | null>(null)

  async function remediate(f: any, e: any) {
    e.stopPropagation()
    const key = `${f.category}:${f.type}`
    setActing(s => ({ ...s, [key]: 'working' }))
    try {
      const r = await fetch('/api/v2/health/remediate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: f.type, category: f.category, action_type: f.action_type,
          kind: f.kind || 'single_file', message: f.message,
          operator: localStorage.getItem('admin_operator') || 'operator',
        }),
      })
      const j = await r.json()
      setActing(s => ({ ...s, [key]: j.ok ? (j.status || 'triggered') : `failed: ${j.error || ''}` }))
      setTimeout(refetchActivity, 2500)
    } catch (err: any) {
      setActing(s => ({ ...s, [key]: `failed: ${err?.message || 'error'}` }))
    }
  }

  const histSummary = hist?.summary || {}
  const histRows: any[] = hist?.history || []
  const catSeries: Record<string, { at?: string; score?: number }[]> = hist?.category_series || {}

  const chartMax = useMemo(() => Math.max(100, ...histRows.map(h => h.overall_score || 0)), [histRows])

  if (loading) return <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading health…</div>
  if (error) return <div style={{ color: 'var(--red)', fontSize: 11, padding: 20 }}>Error: {error}</div>

  const overall = health?.overall_score
  const status = health?.status || 'unknown'
  const cats = health?.category_scores || {}
  const findings: any[] = health?.findings || []
  const trends: any[] = health?.trends || []

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Health Agent</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            Centralized health score · proactive trends · multi-coder auto-fix
            {health?.mode && <> · <span style={{ color: 'var(--accent)' }}>{health.mode}</span> mode</>}
            {health?.scheduler && <> · via <span style={{ color: 'var(--text2)' }}>{health.scheduler}</span></>}
            {health?.captured_at && <> · last run {fmtWhen(health.captured_at)}</>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['overview', 'coders', 'history'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} title={TAB_HELP[t]} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
          ))}
        </div>
      </div>

      {tab === 'overview' && (
        <>
          {/* Score hero */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 16,
            padding: '16px 20px', background: 'var(--bg1)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', borderLeft: `4px solid ${scoreColor(overall)}` }}>
            <div style={{ fontSize: 48, fontWeight: 800, color: scoreColor(overall), lineHeight: 1 }}>
              {overall ?? '—'}<span style={{ fontSize: 18, color: 'var(--text3)' }}>/100</span>
            </div>
            <div>
              <StatusBadge status={STATUS_TO_BADGE[status] || 'unknown'} label={status} size="md" />
              <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6 }}>
                {health?.counts?.critical || 0} critical · {health?.counts?.warning || 0} warnings
                · {health?.counts?.actionable || 0} actionable
                {health?.enqueued ? ` · ${health.enqueued} queued for auto-fix` : ''}
              </div>
              {health?.summary && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{health.summary}</div>}
              {health?.note && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>{health.note}</div>}
            </div>
          </div>

          {/* Recent changes */}
          {(activity?.activity || []).length > 0 && (
            <div style={{ marginBottom: 16, padding: '8px 12px', background: 'var(--bg1)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6,
                textTransform: 'uppercase', letterSpacing: '.4px' }}>
                Recent Changes <span style={{ fontWeight: 400, color: 'var(--text3)', textTransform: 'none' }}>— remediation attempts (escalation handler + coders)</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 132, overflowY: 'auto' }}>
                {(activity.activity || []).map((a: any, i: number) => (
                  <div key={i} style={{ fontSize: 10.5, padding: '3px 0' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span style={{ color: 'var(--text3)', width: 116, flexShrink: 0 }}>{fmtWhen(a.at)}</span>
                      <span style={{ fontWeight: 800, textTransform: 'uppercase', fontSize: 8, color: STATUS_COLOR[a.action] || 'var(--text3)', width: 88, flexShrink: 0 }}>{a.action}</span>
                      <span style={{ color: 'var(--text1)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.component}</span>
                      <span style={{ color: 'var(--accent)', flexShrink: 0 }}>{a.actor}</span>
                      {a.pr_url?.startsWith('http') && <a href={a.pr_url} style={{ color: 'var(--accent)', fontSize: 10 }}>PR ↗</a>}
                      {a.artifact_url && !a.pr_url?.startsWith('http') && <a href={a.artifact_url} style={{ color: 'var(--accent)', fontSize: 10 }}>diff ↓</a>}
                    </div>
                    {(a.detail || a.resolution) && (
                      <div style={{ marginLeft: 124, marginTop: 2, color: 'var(--text3)', fontSize: 10, lineHeight: 1.4 }}>
                        {a.detail}{a.resolution ? ` · ${a.resolution}` : ''}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Category scores */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10, marginBottom: 18 }}>
            {Object.entries(cats).map(([k, v]: any) => (
              <div key={k} title={CAT_HELP[k] || ''} style={{ cursor: onDrill ? 'pointer' : 'help' }}>
                <StateCard title={CAT_LABEL[k] || k} value={v}
                  status={v >= 85 ? 'fresh' : v >= 65 ? 'warning' : 'blocked'}
                  description={`${v}/100`}
                  onClick={onDrill ? () => onDrill({
                    title: CAT_LABEL[k] || k, subtitle: `Score ${v}/100 — ${CAT_HELP[k] || ''}`, endpoint: '/api/v2/health',
                    rows: findings.filter(f => f.category === k),
                  }) : undefined}
                  actionLabel={onDrill ? 'View findings' : undefined} />
              </div>
            ))}
          </div>

          {/* Trends */}
          {trends.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--amber)', marginBottom: 6 }}>↘ Degrading Trends</div>
              {trends.map((t, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--text1)', padding: '4px 8px',
                  background: 'var(--amber-dim)', borderRadius: 4, marginBottom: 4 }}>{t.message}</div>
              ))}
            </div>
          )}

          {/* Findings */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)' }}>Findings</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>what · why · recommended action · status (who / when)</div>
          </div>
          {findings.length === 0 && <div style={{ fontSize: 11, color: 'var(--green)' }}>✓ No active findings</div>}
          {findings.map((f, i) => {
            const rem = f.remediation || {}
            const sc = STATUS_COLOR[rem.status] || 'var(--text3)'
            const when = rem.at ? fmtWhen(rem.at) : ''
            return (
              <div key={i} onClick={onDrill ? () => onDrill({
                title: f.message, subtitle: `${CAT_LABEL[f.category] || f.category} · ${f.severity}`,
                endpoint: '/api/v2/health',
                rows: [{
                  what: f.message, why: f.why, recommended_action: f.recommended_action,
                  action_type: f.action_type, detected_by: f.detected_by, detected_at: f.detected_at,
                  status: rem.status, handled_by: rem.by, handled_at: rem.at, detail: rem.detail,
                  pr_url: rem.pr_url, lane: rem.lane, evidence: f,
                }],
              }) : undefined}
                style={{ padding: '8px 10px', background: 'var(--bg1)', border: '1px solid var(--border)',
                  borderRadius: 4, marginBottom: 5, borderLeft: `3px solid ${SEV_COLOR[f.severity] || 'var(--border)'}`,
                  cursor: onDrill ? 'pointer' : 'default' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: SEV_COLOR[f.severity], width: 52, flexShrink: 0 }}>{f.severity}</span>
                  <span style={{ fontSize: 11, color: 'var(--text0)', flex: 1, fontWeight: 600 }}>{f.message}</span>
                  <span title={`${rem.by || '—'}${when ? ' @ ' + when : ''}${rem.detail ? '\n' + rem.detail : ''}`}
                    style={{ fontSize: 8, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.3px',
                      color: sc, background: 'var(--bg2)', padding: '1px 7px', borderRadius: 9, whiteSpace: 'nowrap' }}>
                    {rem.status || 'detected'}
                  </span>
                  <span style={{ fontSize: 9, color: 'var(--text3)', width: 92, flexShrink: 0, textAlign: 'right' }}>{CAT_LABEL[f.category] || f.category}</span>
                </div>
                {f.why && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3, marginLeft: 60 }}>{f.why}</div>}
                <div style={{ fontSize: 10, marginTop: 3, marginLeft: 60, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ color: 'var(--accent)' }}>▸ {f.recommended_action}</span>
                  <span style={{ color: 'var(--text3)' }}>
                    detected by {f.detected_by}
                    {rem.by && rem.by !== f.detected_by ? ` · ${rem.status} by ${rem.by}` : ''}
                    {when ? ` @ ${when}` : ''}
                  </span>
                  {rem.detail && <span style={{ color: 'var(--text3)', fontStyle: 'italic' }}>{rem.detail}</span>}
                  {rem.pr_url && rem.pr_url.startsWith('http') && <a href={rem.pr_url} onClick={e => e.stopPropagation()} style={{ color: 'var(--accent)' }}>PR ↗</a>}
                  {f.actionable && ['auto_retry', 'refresh', 'code_fix'].includes(f.action_type) && (() => {
                    const k = `${f.category}:${f.type}`; const st = acting[k]
                    const label = f.action_type === 'code_fix' ? 'Route to coder' : 'Fix now'
                    return (
                      <button onClick={e => remediate(f, e)} disabled={st === 'working'}
                        title={`Manually trigger: ${f.recommended_action}`}
                        style={{ marginLeft: 'auto', padding: '2px 10px', fontSize: 10, fontWeight: 700,
                          borderRadius: 5, border: '1px solid var(--accent)', cursor: st === 'working' ? 'default' : 'pointer',
                          background: st && st !== 'working' && !st.startsWith('failed') ? 'var(--green-dim)' : 'var(--accent-dim)',
                          color: st && st.startsWith('failed') ? 'var(--red)' : 'var(--accent)' }}>
                        {st === 'working' ? '…' : st ? st.replace('_', ' ') : label}
                      </button>
                    )
                  })()}
                </div>
              </div>
            )
          })}
        </>
      )}

      {tab === 'coders' && (
        <>
          <CoderDispatchLedger data={dispatches} loading={dispLoading} />

          <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 14, marginTop: 4,
            padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', borderLeft: '3px solid var(--accent)' }}>
            <b style={{ color: 'var(--text0)' }}>How it works.</b> The Health Agent detects a code-level problem →
            queues it → the dispatcher's router picks the <b>one</b> best-fit coder below → it fixes the code in an
            isolated git <b>worktree</b>, runs a <b>verify</b> gate, then —
            in <b>advisory</b> mode (default) saves a review diff, or in <b>PR</b> mode opens a pull request.
            <div style={{ marginTop: 6, color: 'var(--text3)' }}>
              Apply model: <b>{coders?.mode_apply || 'worktree → test → PR'}</b> · Dispatch mode: <b style={{ color: coders?.dispatch_mode === 'pr' ? 'var(--green)' : 'var(--amber)' }}>{coders?.dispatch_mode || 'advisory'}</b> ·
              Strategy: <b>{coders?.strategy}</b> · {coders?.available_count ?? '—'}/{coders?.backends?.length ?? '—'} backends available
              {coders?.dispatch_mode === 'pr' && <> · verified fixes open <b>GitHub PRs</b> via <code>gh</code></>}
            </div>
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>What fits what</div>
          <div style={{ marginBottom: 18 }}>
            {Object.entries(coders?.routing || {}).map(([kind, r]: any) => (
              <div key={kind} title={`Preference: ${(r.preference || []).join(' → ')}`}
                style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, padding: '5px 10px',
                  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, marginBottom: 3 }}>
                <span style={{ width: 110, flexShrink: 0, color: 'var(--text2)', fontWeight: 700 }}>{kind.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--text3)' }}>→</span>
                <span style={{ color: r.active ? 'var(--green)' : 'var(--red)', fontWeight: 700, width: 150, flexShrink: 0 }}>
                  {r.active || 'none available'}
                </span>
                <span style={{ color: 'var(--text3)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(r.preference || []).join(' → ')}
                </span>
              </div>
            ))}
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Coder backends</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10, marginBottom: 18 }}>
            {(coders?.backends || []).map((b: any) => (
              <div key={b.name} title={[b.notes, `Best for: ${(b.best_for || []).join(', ')}`, b.target].filter(Boolean).join('\n')}>
                <StateCard title={b.display} value={b.available ? 'UP' : 'dormant'}
                  status={b.available ? 'fresh' : 'unknown'}
                  description={(b.best_for || []).join(', ') || b.kind} compact />
              </div>
            ))}
          </div>

        </>
      )}

      {tab === 'history' && (
        <>
          {/* Context banner */}
          <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.55, marginBottom: 14,
            padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', borderLeft: '3px solid #60a5fa' }}>
            <b style={{ color: 'var(--text0)' }}>Run history.</b> {histSummary.schedule || 'health_agent.py every 30 min'}.
            Retains {histSummary.retention_days ?? 90}d · API shows up to {histSummary.api_limit ?? 500} runs.
            Each bar is one snapshot: score, status, finding counts, and which categories degraded.
            {histSummary.first_at && histSummary.last_at && (
              <span style={{ color: 'var(--text3)' }}> Window: {fmtWhen(histSummary.first_at)} → {fmtWhen(histSummary.last_at)}.</span>
            )}
          </div>

          {/* Summary stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8, marginBottom: 14 }}>
            {[
              { label: 'Current', value: histSummary.current ?? '—', color: scoreColor(histSummary.current) },
              { label: 'Peak', value: histSummary.peak ?? '—', color: 'var(--green)' },
              { label: 'Low', value: histSummary.low ?? '—', color: 'var(--red)' },
              { label: 'Δ window', value: deltaStr(histSummary.delta_window) ?? '—',
                color: (histSummary.delta_window ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' },
              { label: 'Runs', value: hist?.count ?? 0, color: 'var(--text0)' },
            ].map(s => (
              <div key={s.label} style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: s.color }}>{s.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginTop: 2 }}>{s.label}</div>
              </div>
            ))}
          </div>

          {/* Overall score chart */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Overall score</div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100, padding: '8px 10px 4px',
              background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              {histRows.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No history yet — wait for cron runs.</div>}
              {histRows.map((h: any, i: number) => (
                <div key={i} title={`${h.overall_score}/100 ${h.status}${h.delta != null ? ` (${deltaStr(h.delta)})` : ''}\n${fmtWhen(h.captured_at)}`}
                  onClick={() => setHistExpanded(histExpanded === i ? null : i)}
                  style={{
                    flex: 1, minWidth: 4, height: `${Math.round(((h.overall_score || 0) / chartMax) * 100)}%`,
                    background: scoreColor(h.overall_score), borderRadius: '2px 2px 0 0', alignSelf: 'flex-end',
                    cursor: 'pointer', outline: histExpanded === i ? '2px solid #60a5fa' : 'none',
                  }} />
              ))}
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Click a bar for run context · green ≥85 · amber ≥65 · red &lt;65</div>
          </div>

          {/* Category mini-trends */}
          {Object.keys(catSeries).length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>Category scores over window</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
                {Object.entries(catSeries).map(([cat, series]) => {
                  const last = series[series.length - 1]?.score
                  return (
                    <div key={cat} style={{ padding: '8px 10px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 4 }}>
                        <span style={{ color: 'var(--text2)', fontWeight: 700 }}>{CAT_LABEL[cat] || cat}</span>
                        <span style={{ color: scoreColor(last), fontWeight: 800 }}>{last ?? '—'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 28 }}>
                        {series.map((pt, j) => (
                          <div key={j} title={`${pt.score} @ ${fmtWhen(pt.at)}`}
                            style={{ flex: 1, minWidth: 2, height: `${pt.score ?? 0}%`, background: scoreColor(pt.score), borderRadius: '1px 1px 0 0', opacity: 0.85 }} />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Timeline table */}
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>
            Run timeline <span style={{ fontWeight: 400, color: 'var(--text3)', textTransform: 'none' }}>— newest first</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {[...histRows].reverse().map((h: any, i: number) => {
              const idx = histRows.length - 1 - i
              const open = histExpanded === idx
              return (
                <div key={idx} style={{ background: 'var(--bg1)', border: `1px solid ${open ? '#60a5fa55' : 'var(--border)'}`, borderRadius: 6, overflow: 'hidden' }}>
                  <button type="button" onClick={() => setHistExpanded(open ? null : idx)}
                    style={{ display: 'flex', width: '100%', gap: 10, alignItems: 'center', padding: '8px 12px',
                      border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left' }}>
                    <span style={{ fontSize: 10, color: 'var(--text3)', width: 130, flexShrink: 0 }}>{fmtWhen(h.captured_at)}</span>
                    <span style={{ fontSize: 14, fontWeight: 800, color: scoreColor(h.overall_score), width: 36 }}>{h.overall_score}</span>
                    <StatusBadge status={STATUS_TO_BADGE[h.status] || 'unknown'} label={h.status} size="sm" />
                    {h.delta != null && h.delta !== 0 && (
                      <span style={{ fontSize: 10, fontWeight: 700, color: h.delta > 0 ? 'var(--green)' : 'var(--red)' }}>{deltaStr(h.delta)}</span>
                    )}
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                      {h.findings_critical || 0} crit · {h.findings_warning || 0} warn · {h.findings_total || 0} total
                    </span>
                    {(h.degraded_categories || []).length > 0 && (
                      <span style={{ fontSize: 9, color: 'var(--amber)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        ↓ {(h.degraded_categories || []).map((c: string) => CAT_LABEL[c] || c).join(', ')}
                      </span>
                    )}
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
                  </button>
                  {open && (
                    <div style={{ padding: '0 12px 10px 12px', borderTop: '1px solid var(--border-subtle)' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6, margin: '8px 0' }}>
                        {Object.entries(h.category_scores || {}).map(([k, v]: any) => (
                          <div key={k} style={{ fontSize: 10 }}>
                            <span style={{ color: 'var(--text3)' }}>{CAT_LABEL[k] || k}: </span>
                            <span style={{ fontWeight: 700, color: scoreColor(v) }}>{v}</span>
                          </div>
                        ))}
                      </div>
                      {(h.top_findings || []).length > 0 ? (
                        <div style={{ fontSize: 10, color: 'var(--text2)' }}>
                          <span style={{ fontWeight: 700, color: 'var(--text3)' }}>Top findings: </span>
                          {(h.top_findings || []).map((m: string, j: number) => (
                            <div key={j} style={{ marginTop: 3, paddingLeft: 8, borderLeft: '2px solid var(--border)' }}>{m}</div>
                          ))}
                        </div>
                      ) : (
                        <div style={{ fontSize: 10, color: 'var(--green)' }}>No critical/warning findings in this run.</div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}