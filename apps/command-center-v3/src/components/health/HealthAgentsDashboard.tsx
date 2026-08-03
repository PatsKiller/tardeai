import { useApi } from '../../hooks/useApi'

function scoreColor(s: number | null) {
  if (s == null) return 'var(--text3)'
  return s >= 85 ? 'var(--green)' : s >= 65 ? 'var(--amber)' : 'var(--red)'
}
function sevBadge(s: string) {
  const c = s === 'HIGH' ? 'var(--red-dim)' : s === 'MEDIUM' ? 'var(--amber-dim)' : 'var(--green-dim)'
  const tc = s === 'HIGH' ? 'var(--red)' : s === 'MEDIUM' ? 'var(--amber)' : 'var(--green)'
  return { background: c, color: tc, padding: '1px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700 }
}

function Gauge({ label, score, sub }: { label: string; score: number | null; sub?: string }) {
  const pct = score ?? 0
  const color = scoreColor(score)
  const a = 160 * (pct / 100)
  return (
    <div style={{ flex: 1, minWidth: 140, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
      <div style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>{label}</div>
      <svg width="130" height="75" viewBox="0 0 130 75">
        <path d="M 12 70 A 53 53 0 0 1 118 70" fill="none" stroke="var(--border)" strokeWidth="10" strokeLinecap="round" />
        <path d="M 12 70 A 53 53 0 0 1 118 70" fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${a} 999`} />
      </svg>
      <div style={{ fontSize: 28, fontWeight: 800, color, lineHeight: 1, marginTop: -10 }}>
        {score != null ? score : '—'}
      </div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: -4 }}>{sub}</div>}
    </div>
  )
}

function PipelineRow({ p, onFix }: { p: any; onFix?: (key: string) => void }) {
  const statusColor = p.status === 'OK' ? 'var(--green)' : p.status === 'MISSED' ? 'var(--red)' : 'var(--amber)'
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 90px 90px 60px 70px', gap: 8, alignItems: 'center', padding: '5px 10px', fontSize: 11, borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {p.display_name || p.pipeline_key}
      </span>
      <span style={{ color: 'var(--text3)' }}>{p.last_run_at ? timeAgo(p.last_run_at) : 'never'}</span>
      <span style={{ ...sevBadge(p.status === 'OK' ? 'LOW' : p.status === 'MISSED' ? 'HIGH' : 'MEDIUM'), width: 'fit-content' }}>
        {p.status}
      </span>
      <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)', fontSize: 10 }}>
        {p.data_rows >= 0 ? p.data_rows.toLocaleString() : '—'}
      </span>
      {(p.status === 'MISSED' || p.status === 'FAILED') && onFix && (
        <button onClick={() => onFix(p.pipeline_key)} style={{
          background: 'var(--blue)', color: 'var(--text0)', border: 'none', borderRadius: 4, padding: '2px 8px',
          fontSize: 10, cursor: 'pointer' }}>Retry</button>
      )}
      {p.status === 'OK' && <span />}
      {p.issues && p.issues.length > 0 && (
        <div style={{ gridColumn: '1/-1', fontSize: 10, color: 'var(--text3)', paddingLeft: 4 }}>
          {p.issues[0]}
        </div>
      )}
    </div>
  )
}

function timeAgo(iso: string) {
  const h = (Date.now() - Date.parse(iso)) / 3.6e6
  if (isNaN(h)) return '—'
  return h < 1 ? `${Math.round(h * 60)}m` : h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`
}

export default function HealthAgentsDashboard() {
  const { data, loading } = useApi<any>('/api/v2/health/agents/dashboard', 30_000)
  // Handle double-wrapping: data.data.data or data.data
  const dd = data?.data?.data ?? data?.data ?? {}
  const wl = dd.watchlist ?? {}
  const pl = dd.pipeline ?? {}
  const sys = dd.system ?? {}
  const cmp = dd.composite ?? {}
  const events = dd.events ?? []
  const approvals = dd.approvals ?? []
  const timeline = dd.timeline ?? []
  const pipelines = pl.pipelines ?? []

  const doFix = async (pk: string) => {
    try {
      await fetch('/api/v2/admin/cron-retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script_name: pk })
      })
    } catch {}
  }

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Loading health data...</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* ── Row 1: Gauges ── */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Gauge label="Watchlist" score={wl.score} sub={`${wl.degraded ?? 0} degraded`} />
        <Gauge label="Pipelines" score={pl.score} sub={`${pl.degraded ?? 0} stalled · ${pl.total ?? 0} total`} />
        <Gauge label="System" score={sys.score} />
        <Gauge label="Composite" score={cmp.score} sub={cmp.score != null ? (
          cmp.score >= 85 ? 'Healthy' : cmp.score >= 65 ? 'Warning' : 'Critical'
        ) : undefined} />
      </div>

      {/* ── Row 2: Pipeline Matrix ── */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
          Pipeline Execution Matrix ({pipelines.length} pipelines)
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 90px 90px 60px 70px', gap: 8, padding: '4px 10px', fontSize: 10, color: 'var(--text3)', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>
          <span>Pipeline</span><span>Last Run</span><span>Status</span><span>Rows</span><span />
        </div>
        <div style={{ maxHeight: 280, overflow: 'auto' }}>
          {pipelines.length === 0 && (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>
              No pipeline data yet
            </div>
          )}
          {pipelines.map((p: any, i: number) => (
            <PipelineRow key={p.pipeline_key || i} p={p} onFix={doFix} />
          ))}
        </div>
      </div>

      {/* ── Row 3: Events + Approvals ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Events */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
            Recent Events ({events.length})
          </div>
          <div style={{ maxHeight: 220, overflow: 'auto' }}>
            {events.length === 0 && (
              <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No events</div>
            )}
            {events.map((e: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 10, borderBottom: '1px solid var(--border-subtle)', alignItems: 'center' }}>
                <span style={sevBadge(e.severity || 'LOW')}>{e.severity || 'LOW'}</span>
                <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)', fontSize: 10, minWidth: 42 }}>
                  {e.created_at ? timeAgo(e.created_at) : ''}
                </span>
                {e.symbol && <span style={{ color: 'var(--blue)', fontWeight: 600 }}>{e.symbol}</span>}
                <span style={{ color: 'var(--text2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(e.message || '').replace(/^\[.*?\]\s*/, '')}
                </span>
                {e.success != null && (
                  <span style={{ color: e.success ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
                    {e.success ? 'OK' : 'FAIL'}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Approvals */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
            Pending Approvals ({approvals.length})
          </div>
          <div style={{ maxHeight: 220, overflow: 'auto' }}>
            {approvals.length === 0 && (
              <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No pending approvals</div>
            )}
            {approvals.map((a: any, i: number) => {
              const diag = a.diagnosis || {}
              return (
                <div key={i} style={{ padding: '6px 0', fontSize: 11, borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: 'var(--blue)', fontWeight: 600 }}>
                      {(a.source || 'wl') === 'wl' ? 'WATCHLIST' : 'PIPELINE'}: {a.target || a.symbol || '?'}
                    </span>
                    <span style={{ color: 'var(--text3)', fontSize: 10 }}>
                      {a.created_at ? timeAgo(a.created_at) : ''}
                    </span>
                  </div>
                  <div style={{ color: 'var(--text2)', fontSize: 10, marginTop: 2 }}>
                    {typeof diag === 'object' ? diag.summary || diag.severity : diag}
                  </div>
                  {(a.actions || []).map((act: any, j: number) => (
                    <div key={j} style={{ fontSize: 10, color: 'var(--text3)', marginTop: 1 }}>
                      - {act.label || act.id || act}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Row 4: 24h Timeline ── */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
          24h Health Timeline
        </div>
        {timeline.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No events in last 24h</div>
        ) : (
          <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 60, paddingBottom: 4 }}>
            {timeline.map((t: any, i: number) => {
              const maxH = Math.max(...timeline.map((x: any) => x.count))
              const h = maxH > 0 ? Math.max(4, (t.count / maxH) * 56) : 4
              const sev = t.max_severity === 3 ? 'var(--red)' : t.max_severity === 2 ? 'var(--amber)' : 'var(--green)'
              return (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <span style={{ fontSize: 10, color: 'var(--text3)' }}>{t.count || 0}</span>
                  <div style={{ width: '100%', height: h, background: sev, borderRadius: '2px 2px 0 0', opacity: .7 }} />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
