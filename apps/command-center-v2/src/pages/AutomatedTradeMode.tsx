import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'

const card: React.CSSProperties = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px' }
const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }
const btn = (active?: boolean): React.CSSProperties => ({
  padding: '7px 16px', borderRadius: 8, fontSize: 12, fontWeight: 500, cursor: 'pointer',
  background: active ? 'rgba(99,102,241,0.2)' : 'rgba(255,255,255,0.06)',
  border: active ? '1px solid rgba(99,102,241,0.5)' : '1px solid rgba(255,255,255,0.1)',
  color: active ? '#a5b4fc' : 'rgba(255,255,255,0.5)',
})

const MODE_COLORS: Record<string, string> = {
  disabled: '#6b7280', dry_run: '#f59e0b', active: '#22c55e', paused: '#ef4444',
}

const PREDICT_COLORS: Record<string, string> = {
  would_approve: '#4ade80', would_reject: '#f87171', would_defer: '#f59e0b', would_skip: '#9ca3af',
}

interface ATMStatus {
  mode: string; paused_until: string; pause_reason: string | null
  last_state_change_at: string; last_state_change_by: string
  last_evaluated_at: string; config_hash: string | null
  is_market_hours: boolean; next_expected_cycle: string
  accounts: any[]; decisions_today: Record<string, number>
}

export default function AutomatedTradeMode() {
  const { data: status, refetch } = useApi<ATMStatus>('/api/v2/atm/status', 15000)
  const { data: decisions } = useApi<any[]>('/api/v2/atm/decisions?limit=20', 30000)
  const { data: health } = useApi<any[]>('/api/v2/atm/strategy-health', 60000)
  const { data: queue } = useApi<any[]>('/api/v2/atm/queue-preview', 15000)
  const { data: configData } = useApi<any>('/api/v2/atm/config', 60000)
  const { data: enrichResp } = useApi<any>('/api/v2/atm/enrichment-status', 15000)
  const [showModal, setShowModal] = useState(false)
  const [confirmAction, setConfirmAction] = useState<string | null>(null)

  const mode = status?.mode || 'disabled'
  const modeColor = MODE_COLORS[mode] || '#6b7280'
  const isDryRun = mode === 'dry_run'
  const dt = status?.decisions_today || {}
  const approved = isDryRun
    ? (dt.dry_run_approved || 0)
    : (dt.approved || 0) + (dt.force_approved || 0)
  const rejected = isDryRun
    ? (dt.dry_run_rejected || 0)
    : (dt.rejected || 0) + (dt.force_rejected || 0)
  const deferred = dt.deferred || 0

  const lastEvalAge = (() => {
    if (!status?.last_evaluated_at) return null
    const d = new Date(status.last_evaluated_at)
    if (isNaN(d.getTime())) return null
    return Math.floor((Date.now() - d.getTime()) / 60000)
  })()

  const doMode = async (m: string) => {
    setConfirmAction(null)
    await fetch('/api/v2/atm/mode', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: m, changed_by: 'dashboard' }) })
    refetch()
  }

  // Staleness: only warn during market hours
  const isStale = lastEvalAge != null && lastEvalAge > 20 && status?.is_market_hours

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: 'rgba(255,255,255,0.9)' }}>Automated Trade Mode</h1>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', margin: '4px 0 0' }}>Auto-approve proposals without human /ptapprove. All existing safety gates remain active.</p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <a href="/atm-control-room" style={{ ...btn(), textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}>Control Room</a>
          <button onClick={() => refetch()} style={btn()}>Refresh</button>
          <button onClick={() => setShowModal(true)} style={btn()}>Settings</button>
        </div>
      </div>

      {/* Status banner */}
      <div style={{ padding: '14px 20px', borderRadius: 10, marginBottom: 16, background: `${modeColor}15`, border: `1px solid ${modeColor}40`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 12, height: 12, borderRadius: 6, background: modeColor }} />
          <span style={{ fontSize: 18, fontWeight: 700, color: modeColor, textTransform: 'uppercase' }}>{mode}</span>
          {status?.pause_reason && <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>({status.pause_reason})</span>}
        </div>
        <div style={{ textAlign: 'right', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
          <div>
            Last evaluated: {lastEvalAge != null ? `${lastEvalAge}m ago` : 'never'}
            {isStale && <span style={{ color: '#f59e0b', fontWeight: 600, marginLeft: 6 }}>STALE - check cron</span>}
            {lastEvalAge != null && lastEvalAge > 20 && !status?.is_market_hours && (
              <span style={{ color: 'rgba(255,255,255,0.3)', marginLeft: 6 }}>
                (market closed, next: {status?.next_expected_cycle || '?'})
              </span>
            )}
          </div>
          <div>Hash: {status?.config_hash || 'none'}</div>
        </div>
      </div>

      {/* Control bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {confirmAction ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 16px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8 }}>
            <span style={{ color: '#fca5a5', fontSize: 13 }}>Confirm: set ATM to <strong>{confirmAction}</strong>?</span>
            <button onClick={() => doMode(confirmAction)} style={{ ...btn(), background: 'rgba(34,197,94,0.2)', border: '1px solid rgba(34,197,94,0.5)', color: '#4ade80' }}>Yes</button>
            <button onClick={() => setConfirmAction(null)} style={btn()}>Cancel</button>
          </div>
        ) : (
          <>
            <button onClick={() => setConfirmAction('active')} style={btn(mode === 'active')}>Enable</button>
            <button onClick={() => doMode('disabled')} style={btn(mode === 'disabled')}>Disable</button>
            <button onClick={() => doMode('dry_run')} style={btn(mode === 'dry_run')}>Dry Run</button>
            <button onClick={() => doMode('paused')} style={btn(mode === 'paused')}>Pause</button>
            {mode === 'paused' && <button onClick={() => doMode('active')} style={{ ...btn(), color: '#4ade80', border: '1px solid rgba(34,197,94,0.4)' }}>Resume</button>}
          </>
        )}
      </div>

      {/* P0.5B: Classifier guardrail banner */}
      {(status as any)?.classifier_guardrail?.classifier_gate_disabled && (
        <div style={{ padding: '10px 16px', borderRadius: 8, marginBottom: 12, background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#f59e0b', fontWeight: 600, fontSize: 12 }}>Classifier Gate Disabled</span>
            <span style={{ fontSize: 11, color: 'rgba(245,158,11,0.7)' }}>
              min_classifier_health = {(status as any).classifier_guardrail.classifier_health_min} (production: {(status as any).classifier_guardrail.production_threshold})
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)', marginTop: 4 }}>
            Cold-start burn-in active. ATM may continue in paper observation but cannot graduate while threshold is 0.0.
          </div>
        </div>
      )}

      {/* Per-account strip */}
      {(status?.accounts || []).filter((a: any) => a.enabled).length > 0 && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 20, overflowX: 'auto' }}>
          {(status?.accounts || []).filter((a: any) => a.enabled).map((a: any) => {
            const manual = (a.new_today ?? 0) - (a.new_today_atm ?? 0)
            return (
              <div key={a.account_label} style={{ ...card, minWidth: 200, padding: '12px 16px' }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.85)', marginBottom: 8 }}>{a.account_label}</div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginBottom: 4 }}>{a.broker} / {a.mode}</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>Positions: {a.positions_open ?? 0}</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>
                  New today: {a.new_today ?? 0}
                  {(a.new_today ?? 0) > 0 && (
                    <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginLeft: 6 }}>
                      (ATM: {a.new_today_atm ?? 0} · manual: {manual >= 0 ? manual : 0})
                    </span>
                  )}
                </div>
              </div>
            )
          })}
          {/* Ghost cards for disabled accounts */}
          {(status?.accounts || []).filter((a: any) => !a.enabled).map((a: any) => (
            <div key={a.account_label} style={{ ...card, minWidth: 180, padding: '12px 16px', opacity: 0.35, borderStyle: 'dashed' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.5)', marginBottom: 8 }}>{a.account_label}</div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>Disabled</div>
            </div>
          ))}
        </div>
      )}

      {/* Activity + Capacity tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10, marginBottom: 20 }}>
        {[
          { label: 'Proposals seen', value: approved + rejected + deferred },
          { label: isDryRun ? 'Would approve' : 'Auto-approved', value: approved, color: '#4ade80' },
          { label: isDryRun ? 'Would reject' : 'Rejected', value: rejected, color: '#f87171' },
          { label: 'Deferred', value: deferred, color: '#f59e0b' },
          { label: 'Queue', value: (queue || []).length },
        ].map(k => (
          <div key={k.label} style={{ ...card, textAlign: 'center', padding: '14px 16px', borderColor: isDryRun ? 'rgba(245,158,11,0.15)' : undefined }}
               title={isDryRun ? 'DRY_RUN mode — these are decisions ATM would have made if ACTIVE' : undefined}>
            <div style={{ fontSize: 24, fontWeight: 600, color: k.color || 'rgba(255,255,255,0.9)' }}>{k.value}</div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>{k.label}</div>
            {isDryRun && <div style={{ fontSize: 8, color: 'rgba(245,158,11,0.5)', marginTop: 2 }}>dry run</div>}
          </div>
        ))}
      </div>

      {/* Queue preview */}
      {(queue || []).length > 0 && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={secTitle}>Next cycle queue ({(queue || []).length} proposals)</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['ID', 'Symbol', 'Strategy', 'Account', 'Override', 'Predicted', 'Entry', 'Stop'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Symbol' || h === 'Strategy' || h === 'Account' || h === 'Predicted' ? 'left' : 'right', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(queue || []).map((q: any) => {
                  const predColor = PREDICT_COLORS[q.predicted_decision] || '#9ca3af'
                  return (
                    <tr key={q.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.4)', textAlign: 'right' }}>#{q.id}</td>
                      <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{q.symbol}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{(q.strategy_id || '').replace(/_/g, ' ')}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{q.target_account}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11 }}>
                        {q.atm_action ? <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: q.atm_action === 'force_approve' ? 'rgba(245,158,11,0.2)' : 'rgba(156,163,175,0.2)', color: q.atm_action === 'force_approve' ? '#fbbf24' : '#9ca3af' }}>{q.atm_action.replace(/_/g, ' ')}</span> : '—'}
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 10 }}>
                        <span style={{ padding: '1px 6px', borderRadius: 4, fontWeight: 600, background: `${predColor}20`, color: predColor }}>
                          {(q.predicted_decision || '').replace(/_/g, ' ')}
                        </span>
                        {q.predicted_reason && (
                          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>{q.predicted_reason}</div>
                        )}
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)', textAlign: 'right' }}>${Number(q.proposed_entry || 0).toFixed(2)}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)', textAlign: 'right' }}>${Number(q.proposed_stop || 0).toFixed(2)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Enrichment status */}
      {enrichResp && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={secTitle}>
            Enrichment status
            <span style={{ fontSize: 10, fontWeight: 400, color: 'rgba(255,255,255,0.3)', marginLeft: 10 }}>
              Last run: {enrichResp.last_enrichment_at ? (() => {
                const d = new Date(enrichResp.last_enrichment_at)
                if (isNaN(d.getTime())) return '—'
                const m = Math.floor((Date.now() - d.getTime()) / 60000)
                return m < 1 ? 'just now' : `${m}m ago`
              })() : 'never'}
            </span>
          </div>
          {enrichResp.summary && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 12, fontSize: 12 }}>
              <span style={{ color: 'rgba(255,255,255,0.5)' }}>Total: <strong>{enrichResp.summary.total}</strong></span>
              <span style={{ color: '#4ade80' }}>Complete: <strong>{enrichResp.summary.complete}</strong></span>
              {enrichResp.summary.in_progress > 0 && <span style={{ color: '#f59e0b' }}>In progress: <strong>{enrichResp.summary.in_progress}</strong></span>}
              {enrichResp.summary.pending > 0 && <span style={{ color: 'rgba(255,255,255,0.4)' }}>Pending: <strong>{enrichResp.summary.pending}</strong></span>}
              {enrichResp.summary.failed > 0 && <span style={{ color: '#f87171' }}>Failed: <strong>{enrichResp.summary.failed}</strong></span>}
            </div>
          )}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['ID', 'Symbol', 'Status', 'Last Attempt', 'Retries', 'Steps'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Symbol' || h === 'Status' || h === 'Steps' ? 'left' : 'right', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {((enrichResp as any)?.data || []).map((e: any) => {
                  const sc = e.enrichment_status === 'COMPLETE' ? '#4ade80' : e.enrichment_status === 'FAILED' ? '#f87171' : e.enrichment_status === 'IN_PROGRESS' ? '#f59e0b' : 'rgba(255,255,255,0.4)'
                  const steps = e.steps || {}
                  const stepList = ['refresh_price', 'technical', 'ai_review', 'risk_gate', 'readiness']
                  return (
                    <tr key={e.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.4)', textAlign: 'right' }}>#{e.id}</td>
                      <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{e.symbol}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: `${sc}20`, color: sc }}>{e.enrichment_status || 'pending'}</span>
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)', textAlign: 'right' }}>
                        {e.enrichment_last_attempt_at ? (() => {
                          const d = new Date(e.enrichment_last_attempt_at)
                          if (isNaN(d.getTime())) return '—'
                          const m = Math.floor((Date.now() - d.getTime()) / 60000)
                          return m < 1 ? 'just now' : `${m}m ago`
                        })() : '—'}
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: e.enrichment_failures > 0 ? '#f87171' : 'rgba(255,255,255,0.4)', textAlign: 'right' }}>{e.enrichment_failures || 0}</td>
                      <td style={{ padding: '6px 8px', fontSize: 9 }}>
                        {stepList.map(s => {
                          const st = steps[s]
                          const c = !st ? 'rgba(255,255,255,0.15)' : st.success ? '#4ade80' : '#f87171'
                          return <span key={s} title={`${s}: ${st ? (st.success ? `ok (${st.duration_seconds}s)` : st.error_message || 'failed') : 'not run'}`} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: c, marginRight: 3 }} />
                        })}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Strategy health table */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={secTitle}>Strategy health</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              {['Strategy', 'Health', 'Trades (30d)', 'Eligible', 'B-1 Excluded', 'Same-Day Skip'].map(h => (
                <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'center', padding: '6px 10px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {(Array.isArray(health) ? health : []).map((s: any) => (
                <tr key={s.strategy_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '7px 10px', fontWeight: 500, color: 'rgba(255,255,255,0.8)' }}>{(s.strategy_id || '').replace(/_/g, ' ')}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'center' }}>
                    {s.has_baseline ? (
                      <span style={{ fontWeight: 600, color: s.classifier_health >= 0.5 ? '#4ade80' : s.classifier_health > 0 ? '#f59e0b' : 'rgba(255,255,255,0.5)' }}>
                        {s.classifier_health.toFixed(3)}
                      </span>
                    ) : (
                      <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>
                        0.00 <span style={{ fontSize: 9 }}>(no baseline)</span>
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '7px 10px', textAlign: 'center', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
                    {s.closed_trades ?? 0}{s.closed_trades > 0 ? ` (${s.wins}W)` : ''}
                  </td>
                  <td style={{ padding: '7px 10px', textAlign: 'center', color: s.eligible ? '#4ade80' : '#f87171' }}>{s.eligible ? 'Yes' : 'No'}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'center', color: s.bucket2_excluded ? '#f59e0b' : 'rgba(255,255,255,0.3)' }}>{s.bucket2_excluded ? 'Yes' : '—'}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'center', color: s.same_day_skip ? '#f59e0b' : 'rgba(255,255,255,0.3)' }}>{s.same_day_skip ? 'Yes' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(255,255,255,0.02)', fontSize: 10, color: 'rgba(255,255,255,0.3)', lineHeight: 1.5 }}>
          Strategies showing "0.00 (no baseline)" have no classifier baseline yet (need 3+ closed trades in 30 days).
          ATM will block them unless min_classifier_health is set to 0 in Settings.
        </div>
      </div>

      {/* Recent decisions table */}
      <div style={card}>
        <div style={secTitle}>Recent decisions (last 20)</div>
        {!(decisions || []).length ? (
          <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 12, padding: 16 }}>No ATM decisions yet. Set mode to DRY_RUN or ACTIVE to start evaluating proposals.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['Time', 'Symbol', 'Strategy', 'Account', 'Decision', 'Blocker', 'Trade ID'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(decisions || []).map((d: any) => {
                  const dc = d.decision?.includes('approved') ? '#4ade80' : d.decision?.includes('rejected') ? '#f87171' : '#f59e0b'
                  const firstBlocker = (() => {
                    try {
                      const reasons = typeof d.rejection_reasons === 'string' ? JSON.parse(d.rejection_reasons) : d.rejection_reasons
                      if (Array.isArray(reasons) && reasons.length > 0) return reasons[0]?.gate || '—'
                    } catch {}
                    return '—'
                  })()
                  return (
                    <tr key={d.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{String(d.decided_at || '').slice(0, 16)}</td>
                      <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{d.symbol}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{(d.strategy_id || '').replace(/_/g, ' ')}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{d.target_account}</td>
                      <td style={{ padding: '6px 8px' }}><span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: `${dc}20`, color: dc }}>{(d.decision || '').replace(/_/g, ' ')}</span></td>
                      <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{firstBlocker}</td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{d.trade_id ? `#${d.trade_id}` : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Settings modal */}
      {showModal && <SettingsModal config={configData?.config} hash={configData?.hash} onClose={() => { setShowModal(false); refetch() }} />}
    </div>
  )
}

function SettingsModal({ config, hash, onClose }: { config: any; hash: string; onClose: () => void }) {
  const [tab, setTab] = useState('defaults')
  const [saving, setSaving] = useState(false)
  const [cfg, setCfg] = useState<any>(config || {})

  const save = async () => {
    setSaving(true)
    try {
      const resp = await fetch('/api/v2/atm/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...cfg, _changed_by: 'dashboard_modal' }) })
      const r = await resp.json()
      if (r.ok) { alert(`Saved. Hash: ${r.hash}. Effective next cycle.`); onClose() }
      else alert(`Save failed: ${r.error}`)
    } catch (e) { alert(`Error: ${e}`) }
    setSaving(false)
  }

  const defaults = cfg?.defaults?.position_limits || {}
  const sf = cfg?.defaults?.strategy_filter || {}
  const b1 = cfg?.b1_tracking || {}

  const input = (label: string, value: any, onChange: (v: string) => void, type = 'text') => (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 3 }}>{label}</label>
      <input value={value ?? ''} onChange={e => onChange(e.target.value)} type={type}
        style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.8)', fontSize: 13 }} />
    </div>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{ background: '#1a1a2e', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 16, width: 600, maxHeight: '80vh', overflow: 'auto', padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: 'rgba(255,255,255,0.9)', margin: 0 }}>ATM Settings</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', fontSize: 18, cursor: 'pointer' }}>X</button>
        </div>

        <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          {['defaults', 'accounts', 'global', 'b1', 'same-day'].map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 12px', fontSize: 11, background: 'none', border: 'none', cursor: 'pointer', color: tab === t ? '#a5b4fc' : 'rgba(255,255,255,0.4)', borderBottom: tab === t ? '2px solid #818cf8' : '2px solid transparent', marginBottom: -1 }}>{t}</button>
          ))}
        </div>

        {tab === 'defaults' && (
          <div>
            {input('Max concurrent positions', defaults.max_concurrent, v => setCfg({...cfg, defaults: {...cfg.defaults, position_limits: {...defaults, max_concurrent: parseInt(v) || 10}}}), 'number')}
            {input('Max new per day', defaults.max_new_per_day, v => setCfg({...cfg, defaults: {...cfg.defaults, position_limits: {...defaults, max_new_per_day: parseInt(v) || 6}}}), 'number')}
            {input('Max % per trade', defaults.max_pct_per_trade, v => setCfg({...cfg, defaults: {...cfg.defaults, position_limits: {...defaults, max_pct_per_trade: parseFloat(v) || 1}}}), 'number')}
            {input('Min classifier health', sf.min_classifier_health, v => setCfg({...cfg, defaults: {...cfg.defaults, strategy_filter: {...sf, min_classifier_health: parseFloat(v) || 0.5}}}), 'number')}
            {input('Daily loss % hard pause', cfg?.defaults?.kill_switches?.daily_loss_pct_hard_pause, v => setCfg({...cfg, defaults: {...cfg.defaults, kill_switches: {...(cfg.defaults?.kill_switches||{}), daily_loss_pct_hard_pause: parseFloat(v) || 10}}}), 'number')}
          </div>
        )}

        {tab === 'b1' && (
          <div>
            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>B-1 tracking enabled</label>
              <div><input type="checkbox" checked={b1.enabled} onChange={e => setCfg({...cfg, b1_tracking: {...b1, enabled: e.target.checked}})} /> {b1.enabled ? 'Yes' : 'No'}</div>
            </div>
            {input('Observation end date', b1.observation_end, v => setCfg({...cfg, b1_tracking: {...b1, observation_end: v}}))}
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginTop: 8 }}>
              Bucket 2 strategies: {(b1.bucket2_strategies || []).join(', ')}
            </div>
          </div>
        )}

        {tab === 'same-day' && (
          <div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', marginBottom: 10 }}>
              Strategies the 15-min ATM cron is too slow for. These remain manually approvable.
            </div>
            {(cfg?.same_day_skip_strategies || []).map((s: string) => (
              <div key={s} style={{ padding: '4px 8px', fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>- {s.replace(/_/g, ' ')}</div>
            ))}
          </div>
        )}

        {tab === 'accounts' && (
          <div>
            {Object.entries(cfg?.accounts || {}).map(([label, acct]: [string, any]) => (
              <div key={label} style={{ marginBottom: 14, padding: 12, background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{label}</span>
                  <label style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
                    <input type="checkbox" checked={acct?.enabled ?? false}
                      onChange={e => setCfg({...cfg, accounts: {...cfg.accounts, [label]: {...acct, enabled: e.target.checked}}})} /> Enabled
                  </label>
                </div>
                {acct?.position_limits && Object.entries(acct.position_limits).map(([k, v]: [string, any]) => (
                  <div key={k} style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', padding: '2px 0' }}>{k}: {v}</div>
                ))}
              </div>
            ))}
          </div>
        )}

        {tab === 'global' && (
          <div>
            {input('Aggregate daily loss % hard pause', cfg?.global?.daily_loss_pct_hard_pause_aggregate, v => setCfg({...cfg, global: {...(cfg.global||{}), daily_loss_pct_hard_pause_aggregate: parseFloat(v) || 10}}), 'number')}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          <button onClick={onClose} style={{ padding: '8px 20px', borderRadius: 8, fontSize: 12, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.5)', cursor: 'pointer' }}>Cancel</button>
          <button onClick={save} disabled={saving} style={{ padding: '8px 20px', borderRadius: 8, fontSize: 12, background: 'rgba(99,102,241,0.2)', border: '1px solid rgba(99,102,241,0.5)', color: '#a5b4fc', cursor: 'pointer', fontWeight: 600 }}>{saving ? 'Saving...' : 'Save config'}</button>
        </div>

        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', marginTop: 8, textAlign: 'right' }}>Current hash: {hash || 'none'}</div>
      </div>
    </div>
  )
}
