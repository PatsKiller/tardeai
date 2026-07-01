/** Risk-tab card: live stop/risk monitoring for OPEN momentum_scalp paper trades.
 *  Advisory/read-only source: /api/v2/scalp/stop-monitor (scalp_stop_monitor.py).
 *  Layer-4 (MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §3/§4): regime-shift tighten, portfolio-heat tighten
 *  (>3.5%) + pause, and the "Tighten All Trails" one-click (POST /api/v2/scalp/tighten-all — PAPER only). */
import { useState } from 'react'
import { useApi } from '../hooks/useApi'

const LVL: Record<string, string> = { red: '#ef4444', amber: '#f59e0b', yellow: '#eab308' }

export default function ScalpStopMonitorCard() {
  const { data, refetch } = useApi<any>('/api/v2/scalp/stop-monitor', 30_000)
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const d = data?.data ?? data
  if (!d) return null
  const scalps: any[] = d.open_scalps ?? []
  const alerts: any[] = d.alerts ?? []
  const heat = d.portfolio_heat_pct
  const tightenPct = d.limits?.heat_tighten_pct ?? 3.5
  const killPct = d.limits?.heat_kill_pct ?? 4.5
  const heatCol = heat == null ? 'var(--text3)' : heat > killPct ? '#ef4444' : heat > tightenPct ? '#f59e0b' : '#22c55e'
  const cands: any[] = d.tighten_all_candidates ?? []

  async function tightenAll() {
    // Two-step: dry-run to show exactly what would change, confirm, then apply. PAPER-only, no broker order.
    setBusy(true); setFlash(null)
    try {
      const dry = await fetch('/api/v2/scalp/tighten-all', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apply: false, trigger: d.tighten_all_trigger }) }).then(r => r.json())
      const changes: any[] = (dry?.data ?? dry)?.changes ?? []
      if (!changes.length) { setFlash('Nothing to tighten right now.'); setBusy(false); return }
      const summary = changes.map(c => `${c.symbol} $${c.from}→$${c.to}`).join(', ')
      if (!window.confirm(`Tighten ${changes.length} paper trail(s) by ${d.limits?.regime_tighten_atr ?? 0.5}× ATR?\n\n${summary}\n\nPAPER only — no broker order is placed.`)) { setBusy(false); return }
      const res = await fetch('/api/v2/scalp/tighten-all', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apply: true, trigger: d.tighten_all_trigger, reason: 'operator Tighten-All (Risk tab)' }) }).then(r => r.json())
      const applied = (res?.data ?? res)?.applied ?? 0
      setFlash(`Applied — ${applied} paper trail(s) tightened.`)
      refetch?.()
    } catch (e: any) { setFlash(`Failed: ${String(e).slice(0, 80)}`) }
    setBusy(false)
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>🎯 Scalp Stop Monitor</span>
        <span style={{ fontSize: 11, color: 'var(--text2)' }}>{d.count ?? 0} open · open risk ${d.open_risk_usd ?? 0}</span>
        {d.current_regime && <span style={{ fontSize: 10.5, color: 'var(--text3)' }}>· regime {String(d.current_regime).replace(/_/g, ' ')}</span>}
        <span style={{ flex: 1 }} />
        {d.pause_new_entries && <span style={{ fontSize: 10.5, fontWeight: 800, color: '#ef4444', padding: '2px 7px', borderRadius: 5, background: '#ef44441a', border: '1px solid #ef444440' }}>⛔ entries paused</span>}
        <span style={{ fontSize: 12, fontWeight: 800, color: heatCol }}
          title={`portfolio heat = open risk / paper equity · tighten>${tightenPct}% · kill>${killPct}%`}>
          heat {heat == null ? '—' : `${heat}%`}
        </span>
      </div>

      {/* Layer-4 "Tighten All Trails" one-click — appears only when the snapshot flags candidates (regime-shift or heat) */}
      {d.tighten_all_available && (
        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '6px 8px', borderRadius: 6, background: '#f59e0b12', border: '1px solid #f59e0b40' }}>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: '#f59e0b' }}>
            L4 {d.tighten_all_trigger === 'portfolio_heat' ? `heat > ${tightenPct}%` : 'regime shift'} — {cands.length} trail(s) can tighten {d.limits?.regime_tighten_atr ?? 0.5}× ATR
          </span>
          <span style={{ flex: 1 }} />
          <button onClick={tightenAll} disabled={busy}
            style={{ fontSize: 10.5, fontWeight: 800, padding: '3px 10px', borderRadius: 5, cursor: busy ? 'wait' : 'pointer',
              border: '1px solid #f59e0b', background: '#f59e0b22', color: '#f59e0b' }}>
            {busy ? '…' : '🔧 Tighten All Trails'}
          </button>
        </div>
      )}
      {flash && <div style={{ marginTop: 6, fontSize: 10.5, color: 'var(--text2)' }}>{flash}</div>}

      {alerts.length > 0 && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {alerts.map((a, i) => (
            <div key={i} style={{ fontSize: 10.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5,
              color: LVL[a.level] ?? 'var(--text2)', background: `${LVL[a.level] ?? '#888'}1a`, border: `1px solid ${LVL[a.level] ?? '#888'}40` }}>
              ▲ {a.msg}
            </div>
          ))}
        </div>
      )}

      {scalps.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>No open scalps. Layer-3 trailing is config-OFF (backtest net-negative for momentum); Layer-4 dynamic tightens are advisory.</div>
      ) : (
        <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr auto auto auto auto auto auto', gap: '3px 10px', fontSize: 10.5 }}>
          <span style={{ color: 'var(--text3)', fontWeight: 700 }}>symbol</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>cur R</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>to stop</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>ATR dist</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>tightness</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>to BE</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>risk $</span>
          {scalps.map((s, i) => {
            const rCol = s.current_R == null ? 'var(--text3)' : s.current_R >= 0 ? '#22c55e' : '#ef4444'
            const nearStop = s.stop_distance_R != null && s.stop_distance_R < 0.3
            return [
              <span key={`s${i}`} style={{ fontWeight: 700, color: 'var(--text1)' }}>{s.symbol}
                {!s.breakeven_secured && <span style={{ color: '#f59e0b', fontSize: 8.5 }}> ·no BE</span>}
                {s.regime_shifted && <span title="entry Trending → now Ranging" style={{ color: '#ef4444', fontSize: 8.5 }}> ·regime↓</span>}</span>,
              <span key={`r${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: rCol, fontWeight: 700 }}>{s.current_R ?? '—'}</span>,
              <span key={`d${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: nearStop ? '#ef4444' : 'var(--text2)' }}>{s.stop_distance_R ?? '—'}R</span>,
              <span key={`a${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text2)' }}>{s.stop_distance_atr ?? '—'}</span>,
              <span key={`t${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text2)' }}>{s.trail_tightness_pct != null ? `${s.trail_tightness_pct}%` : '—'}</span>,
              <span key={`b${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text2)' }}>{s.dist_to_breakeven_R ?? '—'}R</span>,
              <span key={`u${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text3)' }}>{s.risk_usd ?? '—'}</span>,
            ]
          })}
        </div>
      )}
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 8 }}>{d.note}</div>
    </div>
  )
}
