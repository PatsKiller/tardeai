import { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import ImportModal from '../components/ImportModal'
import { useApi } from '../hooks/useApi'
import { useFetch } from '../hooks/useFetch'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface OverviewData { today_change: number; today_pct: number; trade_ai: { go_count: number; vix: number | null }; journal: { total_pnl: number; win_rate: number; trade_count: number }; pending_approvals: number; notification_count: number }
interface RiskData { portfolio_heat_pct: number; positions: { symbol: string; triggered: boolean; stop_price: number | null; current_price: number }[] }
interface DivData { ex_div_alerts: { symbol: string; ex_date: string; amount: string }[] }
interface WlData { count: number; items: { symbol: string; source: string; company: string }[] }
interface RetData { current_age: number; key_dates: Record<string, unknown>[] }
interface BehavDayDetail { day: string; count: number; win_rate: number; avg_pnl: number; total_pnl: number }
interface BehavData { has_data: boolean; best_day: string | BehavDayDetail; worst_day: string | BehavDayDetail; [key: string]: unknown }
interface StressScenario { name: string; impact_pct: number; impact_dollar: number; description?: string }
interface StressData { has_data: boolean; scenarios: StressScenario[] | Record<string, StressScenario>; worst_case_scenario: string; worst_case_loss: number }

export default function AlertsActions() {
  const { data: ov } = useApi<OverviewData>('/api/v2/overview')
  const { data: risk } = useApi<RiskData>('/api/v2/risk')
  const { data: divs } = useApi<DivData>('/api/v2/dividends')
  const { data: wl } = useApi<WlData>('/api/v2/watchlist')
  const { data: ret } = useApi<RetData>('/api/v2/retirement')
  const { data: behav } = useFetch<BehavData>('/data/portfolios/state/behavioral_analytics.json')
  const { data: stress } = useFetch<StressData>('/data/portfolios/state/stress_test.json')
  const [showImport, setShowImport] = useState(false)
  const [runStatus, setRunStatus] = useState<Record<string, string>>({})

  const triggerRun = useCallback(async (endpoint: string, label: string) => {
    setRunStatus(s => ({ ...s, [label]: 'running' }))
    try {
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const d = await r.json().catch(() => ({}))
      setRunStatus(s => ({ ...s, [label]: d.ok !== false ? 'done' : 'failed' }))
    } catch { setRunStatus(s => ({ ...s, [label]: 'failed' })) }
    setTimeout(() => setRunStatus(s => { const n = { ...s }; delete n[label]; return n }), 3000)
  }, [])

  // Build alerts from live data (same logic as v1)
  const alerts: { level: string; icon: string; title: string; sub: string }[] = []

  // Triggered stops
  const triggered = (risk?.positions || []).filter(p => p.triggered)
  triggered.forEach(s => alerts.push({ level: 'critical', icon: '🛑', title: `Stop triggered: ${s.symbol}`, sub: `Price ${fmt$(s.current_price, 2)} hit stop ${fmt$(s.stop_price || 0, 2)}` }))

  // GO tickers
  if (ov?.trade_ai?.go_count && ov.trade_ai.go_count > 0)
    alerts.push({ level: 'info', icon: '🟢', title: `${ov.trade_ai.go_count} GO ticker(s)`, sub: 'High conviction setups this run' })

  // Ex-div alerts
  const exDivs = (divs?.ex_div_alerts || []) as { symbol: string; ex_date: string; amount: string }[]
  exDivs.slice(0, 3).forEach(d => alerts.push({ level: 'info', icon: '💰', title: `Ex-div: ${d.symbol} on ${d.ex_date}`, sub: d.amount }))

  // Pending approvals
  if (ov?.pending_approvals && ov.pending_approvals > 0)
    alerts.push({ level: 'warning', icon: '📋', title: `${ov.pending_approvals} pending approval(s)`, sub: 'Action queue items awaiting review' })

  // System OK
  if (alerts.filter(a => a.level === 'critical').length === 0 && alerts.filter(a => a.level === 'warning').length === 0)
    alerts.push({ level: 'ok', icon: '✅', title: 'All systems nominal', sub: 'No critical alerts' })

  const levelColor: Record<string, string> = { critical: 'var(--red)', warning: 'var(--amber)', info: 'var(--accent)', ok: 'var(--green)' }
  const levelBg: Record<string, string> = { critical: 'var(--red-dim)', warning: 'var(--amber-dim)', info: 'var(--accent-dim)', ok: 'var(--green-dim)' }

  const ActionBtn = ({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) => (
    <button onClick={onClick} style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
      padding: '8px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
      background: 'var(--bg-card)', color: 'var(--text1)', cursor: 'pointer',
      fontFamily: 'var(--mono)', fontSize: 9, minWidth: 64, transition: 'all var(--transition)',
    }}
    onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)', e.currentTarget.style.background = 'var(--accent-dim)')}
    onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)', e.currentTarget.style.background = 'var(--bg-card)')}>
      <span style={{ fontSize: 16 }}>{icon}</span>
      <span>{label}</span>
    </button>
  )

  return (
    <>
      {showImport && <ImportModal onClose={() => setShowImport(false)} />}
      <PageHeader title="Alerts & Actions" subtitle={`${alerts.length} alerts · Red = action required · Green = opportunity · Data as of last reprice`} />

      {/* Quick Actions grid — matches v1 layout */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(64px, 1fr))', gap: 6, marginBottom: 14 }}>
        <ActionBtn icon="▶" label="Run Pipeline" onClick={() => triggerRun('/api/run-portfolio', 'pipeline')} />
        <ActionBtn icon="⚡" label="Trade AI" onClick={() => triggerRun('/api/run-pipeline', 'tradeai')} />
        <ActionBtn icon="⟳" label="Reprice" onClick={() => triggerRun('/api/run-reprice', 'reprice')} />
        <ActionBtn icon="📥" label="Import" onClick={() => setShowImport(true)} />
        <ActionBtn icon="📓" label="Journal" onClick={() => window.location.href = '/v2/journal'} />
        <ActionBtn icon="🛡" label="Risk" onClick={() => window.location.href = '/v2/risk'} />
        <ActionBtn icon="📈" label="Returns" onClick={() => window.location.href = '/v2/portfolio'} />
        <ActionBtn icon="📋" label="Queue" onClick={() => window.location.href = '/v2/approvals'} />
      </div>

      {/* Run status indicators */}
      {Object.entries(runStatus).length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          {Object.entries(runStatus).map(([label, status]) => (
            <span key={label} style={{
              fontSize: 9, padding: '2px 8px', borderRadius: 'var(--radius)',
              background: status === 'done' ? 'var(--green-dim)' : status === 'failed' ? 'var(--red-dim)' : 'var(--accent-dim)',
              color: status === 'done' ? 'var(--green)' : status === 'failed' ? 'var(--red)' : 'var(--accent)',
            }}>
              {label}: {status}
            </span>
          ))}
        </div>
      )}

      {/* Live Alerts feed */}
      <SectionHeader title="Live Alerts" count={alerts.length} />
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {alerts.map((a, i) => (
            <div key={i} style={{
              display: 'flex', gap: 8, padding: '6px 8px', borderRadius: 'var(--radius)',
              background: levelBg[a.level] || 'transparent',
              borderLeft: `3px solid ${levelColor[a.level] || 'var(--text3)'}`,
            }}>
              <span style={{ fontSize: 14, flexShrink: 0 }}>{a.icon}</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: levelColor[a.level] || 'var(--text1)' }}>{a.title}</div>
                {a.sub && <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 1 }}>{a.sub}</div>}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Journal Quick Stats */}
      {ov?.journal && ov.journal.trade_count > 0 && (
        <>
          <SectionHeader title="Journal Quick Stats" />
          <Card compact>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Net P&L</div><div style={{ fontSize: 14, fontWeight: 700, color: deltaColor(ov.journal.total_pnl) }}>{ov.journal.total_pnl >= 0 ? '+' : ''}{fmt$(ov.journal.total_pnl)}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>{ov.journal.trade_count} trades</div></div>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Win Rate</div><div style={{ fontSize: 14, fontWeight: 700, color: ov.journal.win_rate >= 50 ? 'var(--green)' : 'var(--amber)' }}>{ov.journal.win_rate}%</div></div>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Today</div><div style={{ fontSize: 14, fontWeight: 700, color: deltaColor(ov.today_change) }}>{ov.today_change >= 0 ? '+' : ''}{fmt$(ov.today_change)}</div></div>
            </div>
          </Card>
        </>
      )}

      {/* Risk Exposure */}
      {risk && (
        <>
          <SectionHeader title="Risk Exposure" />
          <Card compact>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Heat %</div><div style={{ fontSize: 14, fontWeight: 700, color: risk.portfolio_heat_pct > 5 ? 'var(--red)' : 'var(--amber)' }}>{risk.portfolio_heat_pct.toFixed(1)}%</div></div>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Protected</div><div style={{ fontSize: 14, fontWeight: 700, color: 'var(--green)' }}>{risk.positions.filter(p => p.stop_price != null).length}</div></div>
              <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Triggered</div><div style={{ fontSize: 14, fontWeight: 700, color: triggered.length > 0 ? 'var(--red)' : 'var(--green)' }}>{triggered.length}</div></div>
            </div>
          </Card>
        </>
      )}

      {/* Watchlist snapshot */}
      {wl && wl.count > 0 && (
        <>
          <SectionHeader title="Watchlist" count={wl.count} />
          <Card compact>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {wl.items.slice(0, 8).map(w => (
                <span key={w.symbol + w.source} style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text1)' }}>
                  {w.symbol}
                </span>
              ))}
              {wl.count > 8 && <span style={{ fontSize: 9, color: 'var(--text3)', alignSelf: 'center' }}>+{wl.count - 8} more</span>}
            </div>
          </Card>
        </>
      )}

      {/* Key Dates */}
      {ret && Array.isArray(ret.key_dates) && ret.key_dates.length > 0 && (
        <>
          <SectionHeader title="Key Dates" />
          <Card compact>
            {(ret.key_dates as Record<string, unknown>[]).slice(0, 5).map((d, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <span style={{ fontWeight: 600, color: 'var(--text1)' }}>{String(d.label || d.event || d.name || '')}</span>
                <span style={{ color: 'var(--accent)', marginLeft: 'auto' }}>{String(d.date || d.age || d.value || '')}</span>
              </div>
            ))}
          </Card>
        </>
      )}

      {/* Behavioral */}
      {behav?.has_data && (
        <>
          <SectionHeader title="Trading Behavior" />
          <Card compact>
            <div style={{ fontSize: 10, color: 'var(--text2)' }}>
              {(() => {
                const best = behav.best_day
                const worst = behav.worst_day
                const bestLabel = typeof best === 'string' ? best : (best as BehavDayDetail)?.day || '—'
                const worstLabel = typeof worst === 'string' ? worst : (worst as BehavDayDetail)?.day || '—'
                const bestPnl = typeof best === 'object' && best ? (best as BehavDayDetail).avg_pnl : null
                const worstPnl = typeof worst === 'object' && worst ? (worst as BehavDayDetail).avg_pnl : null
                return (
                  <>
                    Best day: <strong style={{ color: 'var(--green)' }}>{bestLabel}</strong>
                    {bestPnl != null && <span style={{ color: 'var(--text3)' }}> (avg {fmt$(bestPnl)})</span>}
                    {' | '}
                    Worst day: <strong style={{ color: 'var(--red)' }}>{worstLabel}</strong>
                    {worstPnl != null && <span style={{ color: 'var(--text3)' }}> (avg {fmt$(worstPnl)})</span>}
                  </>
                )
              })()}
            </div>
          </Card>
        </>
      )}

      {/* Stress Test */}
      {stress?.has_data && stress.scenarios && (() => {
        const scenarioList: StressScenario[] = Array.isArray(stress.scenarios)
          ? stress.scenarios
          : Object.values(stress.scenarios).filter((v): v is StressScenario => typeof v === 'object' && v !== null && 'name' in v)
        return scenarioList.length > 0 ? (
          <>
            <SectionHeader title="Stress Scenarios" />
            <Card compact>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {scenarioList.slice(0, 4).map((s, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                    <span style={{ flex: 1, color: 'var(--text2)' }}>{s.name}</span>
                    <span style={{ color: 'var(--red)', fontWeight: 600 }}>{s.impact_pct != null ? fmtPct(s.impact_pct) : '—'}</span>
                    <span style={{ color: 'var(--red)', width: 70, textAlign: 'right' }}>{s.impact_dollar != null ? fmt$(s.impact_dollar) : '—'}</span>
                  </div>
                ))}
              </div>
              {stress.worst_case_scenario && (
                <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
                  Worst case: {stress.worst_case_scenario} ({fmt$(stress.worst_case_loss || 0)})
                </div>
              )}
            </Card>
          </>
        ) : null
      })()}
    </>
  )
}
