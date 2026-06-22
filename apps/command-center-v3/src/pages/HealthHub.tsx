import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { StateCard } from '../components/StateCard'
import { StatusBadge } from '../components/StatusBadge'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill?: (ctx: DrillContext) => void }

const SEV_COLOR: Record<string, string> = {
  critical: 'var(--red)', warning: 'var(--amber)', info: 'var(--text3)',
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
  coders: 'Multi-coder auto-fix: which AI coder is wired, what each fits, and recent fix dispatches.',
  history: 'Overall health score across recent runs (cron every 30 min).',
}

export default function HealthHub({ onDrill }: Props) {
  const [tab, setTab] = useState<'overview' | 'coders' | 'history'>('overview')
  const { data: health, loading, error } = useApi<any>('/api/v2/health', 120_000)
  const { data: coders } = useApi<any>('/api/v2/health/coders', 120_000)
  const { data: hist } = useApi<any>('/api/v2/health/history', 300_000)

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
                {health?.captured_at ? ` · ${new Date(health.captured_at).toLocaleString()}` : ''}
              </div>
              {health?.note && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>{health.note}</div>}
            </div>
          </div>

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
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Findings</div>
          {findings.length === 0 && <div style={{ fontSize: 11, color: 'var(--green)' }}>✓ No active findings</div>}
          {findings.map((f, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 10px',
              background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, marginBottom: 4,
              borderLeft: `3px solid ${SEV_COLOR[f.severity] || 'var(--border)'}` }}>
              <span style={{ fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: SEV_COLOR[f.severity],
                width: 56, flexShrink: 0 }}>{f.severity}</span>
              <span style={{ fontSize: 11, color: 'var(--text1)', flex: 1 }}>{f.message}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{CAT_LABEL[f.category] || f.category}</span>
            </div>
          ))}
        </>
      )}

      {tab === 'coders' && (
        <>
          {/* How-to-use help banner */}
          <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 14,
            padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', borderLeft: '3px solid var(--accent)' }}>
            <b style={{ color: 'var(--text0)' }}>How it works.</b> The Health Agent detects a code-level problem →
            queues it → the dispatcher's router picks the <b>one</b> best-fit coder below → it fixes the code in an
            isolated git <b>worktree</b>, runs a <b>verify</b> gate (py_compile + optional tests), then —
            in <b>advisory</b> mode (default) saves a review diff, or in <b>PR</b> mode opens a pull request.
            Nothing ever touches your working tree or <code>main</code> directly.
            <div style={{ marginTop: 6, color: 'var(--text3)' }}>
              Apply model: <b>{coders?.mode_apply || 'worktree → test → PR'}</b> · Strategy: <b>{coders?.strategy}</b> ·
              {' '}{coders?.available_count ?? '—'}/{coders?.backends?.length ?? '—'} backends available ·
              Enable PRs: <code title="Set this env var for the coder_dispatch cron / service">CODER_DISPATCH_MODE=pr</code> ·
              Manual run: <code title="Plan only (no edits). Add --apply to run the coder.">scripts/coder_dispatch.py --from-queue</code>
            </div>
          </div>

          {/* What coder fits what problem (routing) */}
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>
            What fits what <span style={{ fontWeight: 400, color: 'var(--text3)' }}>— router resolves each problem kind to the first available coder</span>
          </div>
          <div style={{ marginBottom: 18 }}>
            {Object.entries(coders?.routing || {}).map(([kind, r]: any) => (
              <div key={kind} title={`Preference order: ${(r.preference || []).join(' → ')}\n(router picks the first one that is installed/online)`}
                style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, padding: '5px 10px',
                  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, marginBottom: 3, cursor: 'help' }}>
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

          {/* Backend cards with rich tooltips */}
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>
            Coder backends <span style={{ fontWeight: 400, color: 'var(--text3)' }}>— hover for details / install hints</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10, marginBottom: 18 }}>
            {(coders?.backends || []).map((b: any) => {
              const tip = [
                b.notes,
                `Best for: ${(b.best_for || []).join(', ') || '—'}`,
                `Type: ${b.kind} · priority ${b.priority} · timeout ${b.timeout_sec || '—'}s`,
                b.target,
                !b.available && b.install ? `Install: ${b.install}` : '',
              ].filter(Boolean).join('\n')
              return (
                <div key={b.name} title={tip} style={{ cursor: 'help' }}>
                  <StateCard title={b.display} value={b.available ? 'UP' : 'dormant'}
                    status={b.available ? 'fresh' : 'unknown'}
                    description={(b.best_for || []).join(', ') || b.kind} compact />
                  {!b.available && b.install && (
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2, paddingLeft: 2 }}
                      title={b.install}>install: <code>{b.install.split('  ')[0]}</code></div>
                  )}
                </div>
              )
            })}
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Recent Auto-Fix Dispatches</div>
          {(coders?.recent_dispatches || []).length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No dispatches yet — they appear here once the dispatcher routes a code-fix.</div>}
          {(coders?.recent_dispatches || []).map((d: any, i: number) => (
            <div key={i} title={`${d.component}\noutcome: ${d.outcome}\nkind: ${d.kind || '—'}`}
              style={{ display: 'flex', gap: 8, fontSize: 11, padding: '5px 10px',
              background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4, marginBottom: 3 }}>
              <span style={{ color: 'var(--text3)', width: 120, flexShrink: 0 }}>{d.created_at ? new Date(d.created_at).toLocaleString() : ''}</span>
              <span style={{ color: 'var(--accent)', width: 90, flexShrink: 0 }}>{d.backend}</span>
              <span style={{ color: 'var(--text1)', flex: 1 }}>{d.component} · {d.outcome}</span>
              {d.pr_url && <a href={d.pr_url} style={{ color: 'var(--accent)' }}>link</a>}
            </div>
          ))}
        </>
      )}

      {tab === 'history' && (
        <>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 10 }}>Overall score over the last {hist?.count ?? 0} runs</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 120, padding: '0 4px',
            background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            {(hist?.history || []).map((h: any, i: number) => (
              <div key={i} title={`${h.overall_score}/100 — ${h.captured_at ? new Date(h.captured_at).toLocaleString() : ''}`}
                style={{ flex: 1, minWidth: 3, height: `${h.overall_score}%`, background: scoreColor(h.overall_score),
                  borderRadius: '2px 2px 0 0', alignSelf: 'flex-end' }} />
            ))}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Bars colored by score band: green ≥85 · amber ≥65 · red &lt;65</div>
        </>
      )}
    </div>
  )
}
