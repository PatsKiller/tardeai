import React, { useState } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)
const pnlColor = (v: number | null | undefined) => v == null ? 'var(--text2)' : v >= 0 ? 'var(--green)' : 'var(--red)'
const fmtDollar = (v: any) => v == null ? '--' : `$${Number(v).toFixed(2)}`
const fmtPct = (v: any) => v == null ? '--' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`
const fmtR = (v: any) => v == null ? '--' : `${Number(v).toFixed(2)}R`
const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }
const td: React.CSSProperties = { padding: '6px 10px' }

type Tab = 'trades' | 'regime' | 'rotation'

export default function PlanVsPerformance() {
  const { data, loading } = useApi<any>('/api/v2/plan-vs-performance', 30000)
  const [tab, setTab] = useState<Tab>('trades')
  const [filter, setFilter] = useState<'all' | 'open' | 'closed'>('all')

  const summary = data?.summary || {}
  const trades = data?.trades || []
  const regimeNow = data?.regime_now
  const regimeHistory = data?.regime_history || []
  const regimeAlerts = data?.regime_alerts || []
  const profiles = data?.strategy_profiles || []
  const rotation = data?.rotation_signals || []
  const snapshots = data?.strategy_snapshots || []

  const filteredTrades = filter === 'all' ? trades : trades.filter((t: any) => filter === 'open' ? t.status !== 'closed' : t.status === 'closed')

  const tabBtn = (id: Tab, label: string) => (
    <button key={id} onClick={() => setTab(id)} style={{
      padding: '6px 14px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer',
      color: tab === id ? '#fff' : 'var(--text2)',
      background: tab === id ? 'rgba(59,130,246,0.5)' : 'rgba(59,130,246,0.08)',
    }}>{label}</button>
  )

  const filterBtn = (id: typeof filter, label: string) => (
    <button key={id} onClick={() => setFilter(id)} style={{
      padding: '4px 10px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer',
      color: filter === id ? '#fff' : 'var(--text3)',
      background: filter === id ? 'rgba(59,130,246,0.35)' : 'transparent',
    }}>{label}</button>
  )

  return (
    <>
      <PageHeader title="Plan vs Performance" subtitle="Automated trade results vs plan targets, market regime impact" />
      <div style={{ padding: '0 24px 24px' }}>
        {loading && <div style={{ color: 'var(--text3)', fontSize: 12, marginBottom: 12 }}>Loading...</div>}

        {/* ── Regime Alerts Banner ── */}
        {regimeAlerts.length > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--red)', marginBottom: 6 }}>REGIME ALERTS — Market Conditions Changed</div>
            {regimeAlerts.map((a: any, i: number) => (
              <div key={i} style={{ fontSize: 10, color: 'var(--text1)', marginBottom: 4, ...mono }}>
                <span style={{ fontWeight: 700 }}>{a.symbol}</span> ({a.strategy_id}): Entry regime "{a.regime_at_entry}" → Now "{a.regime_now}" — {a.alert}
              </div>
            ))}
          </div>
        )}

        {/* ── Summary Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 12, marginBottom: 16, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {kv('Total Trades', summary.total_trades)}
          {kv('Open', summary.open_trades)}
          {kv('Closed', summary.closed_trades)}
          {kv('Total P&L', fmtDollar(summary.total_pnl), pnlColor(summary.total_pnl))}
          {kv('Win Rate', summary.win_rate != null ? `${summary.win_rate}%` : '--', summary.win_rate >= 50 ? 'var(--green)' : 'var(--red)')}
          {kv('Plan Adherence', summary.plan_adherence_rate != null ? `${summary.plan_adherence_rate}%` : '--', summary.plan_adherence_rate >= 70 ? 'var(--green)' : 'var(--amber)')}
          {kv('Avg R Planned', fmtR(summary.avg_r_planned))}
          {kv('Avg R Actual', fmtR(summary.avg_r_actual), pnlColor(summary.avg_r_actual))}
        </div>

        {/* ── Current Regime Strip ── */}
        {regimeNow && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 12, marginBottom: 16, padding: 12, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
            <div>
              <div style={lbl}>Current Regime</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{regimeNow.regime_label || '--'}</div>
            </div>
            {kv('Confidence', regimeNow.confidence != null ? `${Number(regimeNow.confidence).toFixed(0)}%` : '--')}
            {kv('Volatility', regimeNow.volatility_state)}
            {kv('Trend', regimeNow.trend_state)}
            {kv('Breadth', regimeNow.breadth_state)}
            {kv('Liquidity', regimeNow.liquidity_state)}
            {kv('Risk Appetite', regimeNow.risk_appetite_state)}
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
          {tabBtn('trades', 'Trade Plan vs Actual')}
          {tabBtn('regime', 'Regime Impact')}
          {tabBtn('rotation', 'Strategy Rotation')}
        </div>

        {/* ══════════ TAB: Trades ══════════ */}
        {tab === 'trades' && (
          <>
            <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
              {filterBtn('all', `All (${trades.length})`)}
              {filterBtn('open', `Open (${summary.open_trades || 0})`)}
              {filterBtn('closed', `Closed (${summary.closed_trades || 0})`)}
            </div>

            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Symbol', 'Strategy', 'Status', 'Plan Entry', 'Actual Entry', 'Plan Stop', 'Plan Target', 'Exit', 'Slip %', 'P&L', 'Plan R', 'Actual R', 'Plan?', 'MFE', 'MAE', 'Regime@Entry', 'Grade', 'Hold'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredTrades.length === 0 && (
                    <tr><td colSpan={18} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No trades yet. Trades appear after paper proposals are executed.</td></tr>
                  )}
                  {filteredTrades.map((t: any) => {
                    const planEntry = t.expected_entry || t.planned_entry
                    const planStop = t.expected_stop || t.planned_stop || t.stop_loss
                    const planTarget = t.expected_target || t.target_1
                    const planR = t.planned_r || t.expected_r
                    const actualR = t.realized_r || t.actual_r
                    const followed = t.followed_plan || t.thesis_followed
                    const pnl = t.pnl != null ? Number(t.pnl) : null
                    const entrySlip = planEntry && t.entry_price ? ((Number(t.entry_price) - Number(planEntry)) / Number(planEntry) * 100) : t.slippage_pct
                    const statusColor = t.status === 'closed' ? (pnl != null && pnl >= 0 ? 'green' : 'red') : 'blue'

                    return (
                      <tr key={t.trade_id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ ...td, fontWeight: 700 }}>{t.symbol}</td>
                        <td style={{ ...td, color: 'var(--text2)', fontSize: 9 }}>{t.strategy_id || '--'}</td>
                        <td style={td}><span style={pill(statusColor)}>{t.status}</span></td>
                        <td style={td}>{fmtDollar(planEntry)}</td>
                        <td style={{ ...td, color: entrySlip && Math.abs(Number(entrySlip)) > 0.5 ? 'var(--amber)' : 'var(--text0)' }}>{fmtDollar(t.entry_price || t.actual_entry)}</td>
                        <td style={td}>{fmtDollar(planStop)}</td>
                        <td style={td}>{fmtDollar(planTarget)}</td>
                        <td style={{ ...td, color: pnlColor(pnl) }}>{fmtDollar(t.exit_price || t.actual_exit)}</td>
                        <td style={{ ...td, color: entrySlip && Math.abs(Number(entrySlip)) > 0.3 ? 'var(--amber)' : 'var(--text2)' }}>
                          {entrySlip != null ? `${Number(entrySlip).toFixed(2)}%` : '--'}
                        </td>
                        <td style={{ ...td, fontWeight: 700, color: pnlColor(pnl) }}>{fmtDollar(pnl)}</td>
                        <td style={td}>{fmtR(planR)}</td>
                        <td style={{ ...td, color: pnlColor(actualR != null ? Number(actualR) : null) }}>{fmtR(actualR)}</td>
                        <td style={td}>
                          {followed != null ? (
                            <span style={pill(followed ? 'green' : 'red')}>{followed ? 'YES' : 'NO'}</span>
                          ) : '--'}
                        </td>
                        <td style={{ ...td, color: 'var(--green)', fontSize: 9 }}>{t.max_favorable_excursion != null ? `+${Number(t.max_favorable_excursion).toFixed(1)}%` : '--'}</td>
                        <td style={{ ...td, color: 'var(--red)', fontSize: 9 }}>{t.max_adverse_excursion != null ? `-${Number(t.max_adverse_excursion).toFixed(1)}%` : '--'}</td>
                        <td style={{ ...td, fontSize: 9, color: 'var(--text2)' }}>{t.regime_at_entry || '--'}</td>
                        <td style={td}>
                          {t.tca_grade ? <span style={pill(t.tca_grade === 'A' || t.tca_grade === 'B' ? 'green' : t.tca_grade === 'C' ? 'amber' : 'red')}>{t.tca_grade}</span> : (t.fill_quality ? <span style={pill(t.fill_quality === 'GOOD' ? 'green' : t.fill_quality === 'FAIR' ? 'amber' : 'red')}>{t.fill_quality}</span> : '--')}
                        </td>
                        <td style={{ ...td, fontSize: 9, color: 'var(--text3)' }}>
                          {t.hold_minutes != null ? (Number(t.hold_minutes) >= 1440 ? `${(Number(t.hold_minutes) / 1440).toFixed(1)}d` : Number(t.hold_minutes) >= 60 ? `${(Number(t.hold_minutes) / 60).toFixed(1)}h` : `${Number(t.hold_minutes).toFixed(0)}m`) : '--'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* ── Exit Reason Breakdown (closed trades only) ── */}
            {(() => {
              const closed = trades.filter((t: any) => t.status === 'closed' && t.exit_reason)
              if (closed.length === 0) return null
              const reasons: Record<string, { count: number; totalPnl: number }> = {}
              closed.forEach((t: any) => {
                const r = t.exit_reason || 'unknown'
                if (!reasons[r]) reasons[r] = { count: 0, totalPnl: 0 }
                reasons[r].count++
                reasons[r].totalPnl += Number(t.pnl || 0)
              })
              return (
                <>
                  <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Exit Reason Breakdown</h3>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
                    {Object.entries(reasons).map(([reason, stats]) => (
                      <div key={reason} style={{ padding: '8px 12px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border)', minWidth: 120 }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>{reason}</div>
                        <div style={{ fontSize: 9, color: 'var(--text3)' }}>{stats.count} trades</div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: pnlColor(stats.totalPnl), ...mono }}>{fmtDollar(stats.totalPnl)}</div>
                      </div>
                    ))}
                  </div>
                </>
              )
            })()}
          </>
        )}

        {/* ══════════ TAB: Regime Impact ══════════ */}
        {tab === 'regime' && (
          <>
            {/* Regime History */}
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Regime History (Recent)</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Regime', 'Confidence', 'Volatility', 'Trend', 'Date'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {regimeHistory.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No regime history yet.</td></tr>
                  )}
                  {regimeHistory.map((r: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: i === 0 ? 'rgba(59,130,246,0.05)' : undefined }}>
                      <td style={{ ...td, fontWeight: 700 }}>{r.regime_label}{i === 0 ? ' (CURRENT)' : ''}</td>
                      <td style={td}>{r.confidence != null ? `${Number(r.confidence).toFixed(0)}%` : '--'}</td>
                      <td style={td}>{r.volatility_state || '--'}</td>
                      <td style={td}>{r.trend_state || '--'}</td>
                      <td style={{ ...td, color: 'var(--text3)', fontSize: 9 }}>{r.generated_at ? new Date(r.generated_at).toLocaleString() : '--'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Trades by Entry Regime */}
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Performance by Entry Regime</h3>
            {(() => {
              const closed = trades.filter((t: any) => t.status === 'closed' && t.regime_at_entry)
              const byRegime: Record<string, { count: number; wins: number; totalPnl: number; totalR: number; rCount: number }> = {}
              closed.forEach((t: any) => {
                const r = t.regime_at_entry || 'unknown'
                if (!byRegime[r]) byRegime[r] = { count: 0, wins: 0, totalPnl: 0, totalR: 0, rCount: 0 }
                byRegime[r].count++
                if ((Number(t.pnl || 0)) > 0) byRegime[r].wins++
                byRegime[r].totalPnl += Number(t.pnl || 0)
                const ar = t.realized_r || t.actual_r
                if (ar != null) { byRegime[r].totalR += Number(ar); byRegime[r].rCount++ }
              })
              if (Object.keys(byRegime).length === 0) return <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 24 }}>No closed trades with regime data yet.</div>
              return (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
                  {Object.entries(byRegime).map(([regime, stats]) => (
                    <div key={regime} style={{ padding: 12, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', minWidth: 150 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>{regime}</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        {kv('Trades', stats.count)}
                        {kv('Win Rate', `${(stats.wins / stats.count * 100).toFixed(0)}%`, stats.wins / stats.count >= 0.5 ? 'var(--green)' : 'var(--red)')}
                        {kv('Total P&L', fmtDollar(stats.totalPnl), pnlColor(stats.totalPnl))}
                        {kv('Avg R', stats.rCount > 0 ? fmtR(stats.totalR / stats.rCount) : '--')}
                      </div>
                    </div>
                  ))}
                </div>
              )
            })()}

            {/* Strategy Regime Profiles */}
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Strategy Regime Fit</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Strategy', 'Favored Regimes', 'Disfavored', 'Vol Pref', 'Trend Pref', 'Horizon', 'Current Fit'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {profiles.length === 0 && (
                    <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No strategy profiles yet.</td></tr>
                  )}
                  {profiles.map((p: any) => {
                    const favored = Array.isArray(p.favored_regimes) ? p.favored_regimes : (typeof p.favored_regimes === 'string' ? (() => { try { return JSON.parse(p.favored_regimes) } catch { return [] } })() : [])
                    const disfavored = Array.isArray(p.disfavored_regimes) ? p.disfavored_regimes : (typeof p.disfavored_regimes === 'string' ? (() => { try { return JSON.parse(p.disfavored_regimes) } catch { return [] } })() : [])
                    const currentRegime = regimeNow?.regime_label
                    const fit = !currentRegime ? 'unknown' : favored.includes(currentRegime) ? 'FAVORED' : disfavored.includes(currentRegime) ? 'DISFAVORED' : 'NEUTRAL'
                    const fitColor = fit === 'FAVORED' ? 'green' : fit === 'DISFAVORED' ? 'red' : 'amber'
                    return (
                      <tr key={p.strategy_id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ ...td, fontWeight: 700 }}>{p.strategy_id}</td>
                        <td style={{ ...td, fontSize: 9, color: 'var(--green)' }}>{favored.join(', ') || '--'}</td>
                        <td style={{ ...td, fontSize: 9, color: 'var(--red)' }}>{disfavored.join(', ') || '--'}</td>
                        <td style={td}>{p.volatility_preference || '--'}</td>
                        <td style={td}>{p.trend_preference || '--'}</td>
                        <td style={td}>{p.time_horizon || '--'}</td>
                        <td style={td}><span style={pill(fitColor)}>{fit}</span></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ══════════ TAB: Strategy Rotation ══════════ */}
        {tab === 'rotation' && (
          <>
            {/* Rotation Signals */}
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Active Rotation Signals</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Strategy', 'Signal', 'Strength', 'Confidence', 'Action', 'Reason', 'Date'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rotation.length === 0 && (
                    <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No rotation signals yet.</td></tr>
                  )}
                  {rotation.map((r: any, i: number) => {
                    const sigColor = r.signal === 'INCREASE' ? 'green' : r.signal === 'DECREASE' ? 'red' : r.signal === 'HOLD' ? 'blue' : 'amber'
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ ...td, fontWeight: 700 }}>{r.strategy_id || r.strategy_name}</td>
                        <td style={td}><span style={pill(sigColor)}>{r.signal}</span></td>
                        <td style={td}>{r.signal_strength != null ? Number(r.signal_strength).toFixed(2) : '--'}</td>
                        <td style={td}>{r.confidence != null ? `${Number(r.confidence).toFixed(0)}%` : '--'}</td>
                        <td style={{ ...td, fontSize: 9 }}>{r.recommended_action || '--'}</td>
                        <td style={{ ...td, color: 'var(--text2)', fontSize: 9, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.reason || '--'}</td>
                        <td style={{ ...td, color: 'var(--text3)', fontSize: 9 }}>{r.created_at ? new Date(r.created_at).toLocaleString() : '--'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Strategy Performance Snapshots */}
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Strategy Performance Snapshots</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Strategy', 'Period', 'Closed', 'Wins', 'Losses', 'Win %', 'PF', 'Avg R', 'P&L', 'Assessment', 'Action'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {snapshots.length === 0 && (
                    <tr><td colSpan={11} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No performance snapshots yet. Generated weekly by strategy review.</td></tr>
                  )}
                  {snapshots.map((s: any, i: number) => {
                    const recColor = s.recommendation === 'maintain' ? 'green' : s.recommendation === 'review_rules' ? 'amber' : s.recommendation === 'review_risk_reward' ? 'red' : 'blue'
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ ...td, fontWeight: 700 }}>{s.strategy_id}</td>
                        <td style={{ ...td, fontSize: 9, color: 'var(--text3)' }}>{s.snapshot_date || '--'}</td>
                        <td style={td}>{s.trades_closed ?? '--'}</td>
                        <td style={{ ...td, color: 'var(--green)' }}>{s.wins ?? '--'}</td>
                        <td style={{ ...td, color: 'var(--red)' }}>{s.losses ?? '--'}</td>
                        <td style={td}>{s.win_rate != null ? `${Number(s.win_rate).toFixed(0)}%` : '--'}</td>
                        <td style={td}>{s.profit_factor != null ? Number(s.profit_factor).toFixed(2) : '--'}</td>
                        <td style={td}>{fmtR(s.avg_r)}</td>
                        <td style={{ ...td, color: pnlColor(s.total_pnl != null ? Number(s.total_pnl) : null) }}>{fmtDollar(s.total_pnl)}</td>
                        <td style={{ ...td, color: 'var(--text2)', fontSize: 9, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.assessment || '--'}</td>
                        <td style={td}><span style={pill(recColor)}>{s.recommendation || '--'}</span></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  )
}
