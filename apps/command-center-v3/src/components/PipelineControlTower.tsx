import { useApi } from '../hooks/useApi'

// Phase 199H — v3 runtime Control Plane view (pipeline ownership over the 199B inventory / 199C model).
// Read-only: consumes /api/v2/system/pipeline-summary, /runtime-inventory, /atm/gate-status.
// No cron enable/disable from UI. v3-only (no v2 UI touched).

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12, marginBottom: 12 }
const badge = (bg: string, fg: string) => ({ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 5, background: bg, color: fg })

export default function PipelineControlTower() {
  const { data: ps } = useApi<any>('/api/v2/system/pipeline-summary', 60_000)
  const { data: inv } = useApi<any>('/api/v2/system/runtime-inventory', 60_000)
  const { data: gateResp } = useApi<any>('/api/v2/atm/gate-status', 60_000)
  const { data: execState } = useApi<any>('/api/v2/execution/current-state', 120_000)
  const { data: gov } = useApi<any>('/api/v2/system/governance-pipeline-status', 60_000)
  const pipelines: any[] = ps?.pipelines ?? []
  const summary = inv?.summary ?? {}
  const dups: Record<string, number> = summary?.duplicate_scripts ?? {}
  const gate = gateResp?.gate
  const operatorLive = !!execState?.operator_live_via_2fa_allowed

  return (
    <div>
      {/* SAFETY BADGES */}
      <div style={{ ...card, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={badge('rgba(34,197,94,.15)', '#22c55e')}>ALPACA PAPER</span>
        {operatorLive
          ? <span style={badge('rgba(34,197,94,.15)', '#22c55e')}>✓ LIVE VIA 2FA</span>
          : <span style={badge('rgba(245,158,11,.15)', '#f59e0b')}>🔒 OPERATOR LIVE LOCKED</span>}
        <span style={badge('rgba(239,68,68,.15)', '#ef4444')}>LEVEL 7 / AUTO OFF</span>
        <span style={badge('rgba(96,165,250,.12)', '#60a5fa')}>
          gate {gate?.passed ? 'PASSED' : 'BLOCKED'} · trades {gate?.checks?.closed_trades?.have ?? '—'}/{gate?.checks?.closed_trades?.need ?? '—'}
        </span>
        <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
          v3 canonical · /api/v2 = shared backend namespace (not v2 UI)
        </span>
      </div>

      {/* INVENTORY TOTALS */}
      <div style={{ ...card, display: 'flex', gap: 18, fontSize: 11, color: 'var(--text2)', flexWrap: 'wrap' }}>
        <span>Cron lines: <b style={{ color: 'var(--text0)' }}>{summary.total_cron_lines ?? '—'}</b></span>
        <span>Services: <b style={{ color: 'var(--text0)' }}>{summary.total_systemd_services ?? '—'}</b></span>
        <span>Timers: <b style={{ color: 'var(--text0)' }}>{summary.total_systemd_timers ?? '—'}</b></span>
        <span>Unique scripts: <b style={{ color: 'var(--text0)' }}>{summary.unique_scripts ?? '—'}</b></span>
        <span>Multi-scheduled: <b style={{ color: '#f59e0b' }}>{Object.keys(dups).length}</b></span>
        <span>Unknown to triage: <b style={{ color: '#f59e0b' }}>{ps?.unknown_triage_count ?? '—'}</b></span>
        {!inv?.available && <span style={{ color: '#ef4444' }}>inventory not generated — run inventory_runtime_jobs.py</span>}
      </div>

      {/* GOVERNANCE PIPELINE — Phase 200 migrated (controller status) */}
      {gov && (
        <div style={{ ...card, borderColor: gov.last_run?.overall === 'ok' ? '#22c55e' : '#f59e0b' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>
            Governance Pipeline — migrated to controller (Phase 200)
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11, color: 'var(--text2)' }}>
            <span>controller: <b style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{gov.controller}</b></span>
            <span>last run: <b style={{ color: gov.last_run?.overall === 'ok' ? '#22c55e' : '#f59e0b' }}>{gov.last_run?.overall ?? '—'}</b> {gov.last_run?.dry_run ? '(dry-run)' : ''}</span>
            <span>failures: <b style={{ color: (gov.failures?.length ? '#ef4444' : '#22c55e') }}>{gov.failures?.length ?? 0}</b></span>
            <span>retired legacy cron: <b style={{ color: '#60a5fa' }}>{gov.retired_legacy_cron}</b></span>
            <span>retired legacy timers: <b style={{ color: '#60a5fa' }}>{gov.retired_legacy_timers ?? 0}/{gov.retired_legacy_timers_total ?? 4}</b></span>
            <span>active legacy gov cron: <b style={{ color: 'var(--text0)' }}>{gov.active_legacy_governance_cron}</b></span>
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
            safety net: freshness monitor + watchdog <b style={{ color: '#22c55e' }}>untouched</b> ·
            portfolio-maintenance: <b style={{ color: '#f59e0b' }}>{gov.portfolio_maintenance?.status ?? 'not_migrated'}</b>
            {' '}({gov.portfolio_maintenance?.candidate_count ?? 0} candidates, design-only)
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
            steps: {(gov.last_run?.steps ?? []).map((s: any) => `${s.name}:${s.status}`).join(' · ')} · Source: /api/v2/system/governance-pipeline-status
          </div>
        </div>
      )}

      {/* PIPELINE OWNERSHIP CARDS */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(330px,1fr))', gap: 10 }}>
        {pipelines.map(p => (
          <div key={p.pipeline} style={card}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#60a5fa', marginBottom: 6 }}>{p.pipeline}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>{(p.categories ?? []).join(' · ')}</div>
            <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--text2)' }}>
              <span>cron <b style={{ color: 'var(--text0)' }}>{p.cron_jobs}</b></span>
              <span>services <b style={{ color: 'var(--text0)' }}>{p.systemd_units}</b></span>
              <span>compress <b style={{ color: (p.compression_candidates?.length ? '#f59e0b' : 'var(--text3)') }}>{p.compression_candidates?.length ?? 0}</b></span>
            </div>
            {p.compression_candidates?.length > 0 && (
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
                candidates: {p.compression_candidates.map((s: string) => s.replace('scripts/', '')).join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* DUPLICATE-CRON RISK PANEL */}
      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
          Duplicate-cron risk (multi-scheduled scripts — compression candidates)
        </div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
          Mostly intentional multi-cadence (same script, different times). Compression = ownership
          consolidation under a pipeline controller, NOT deletion. No disabling from this UI.
        </div>
        {Object.entries(dups).sort((a, b) => b[1] - a[1]).slice(0, 20).map(([s, n]) => (
          <div key={s} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{s.replace('scripts/', '')}</span>
            <span style={{ color: '#f59e0b' }}>{n}× scheduled</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
        Source: /api/v2/system/pipeline-summary + /runtime-inventory + /atm/gate-status (read-only) ·
        last inventory in data/runtime/runtime_job_inventory_latest.json
      </div>
    </div>
  )
}
