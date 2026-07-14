import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { fmt$, fmtPct } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import RiskGauge from '../components/risk/RiskGauge'
import OperatorInboxPanel from '../components/OperatorInboxPanel'
import { healthFindingCta } from '../lib/healthCta'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubPanel } from '../lib/terminalHubChrome'

interface Props { onDrill: (ctx: DrillContext) => void }

// Compact home section card
function SCard({ title, count, accent, children }: { title: string; count?: any; accent?: string; children: any }) {
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, borderTop: accent ? `2px solid ${accent}` : undefined }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{title}</span>
        {count != null && <span style={{ fontSize: 11, fontWeight: 700, color: accent ?? 'var(--text3)' }}>{count}</span>}
      </div>
      {children}
    </div>
  )
}
const Line = ({ children, color }: any) => <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, color: color ?? 'var(--text2)' }}>{children}</div>

// P2-1: loading skeletons — pulse placeholders so first-paint zeros/dashes ('—', '0 GO · 0 WAIT',
// empty equity curve) never render as if they were real data while useApi is still loading.
const skelAnim = 'ccHomeSkelPulse 1.3s ease-in-out infinite'
const Skel = ({ w = 64, h = 16 }: { w?: number | string; h?: number }) => (
  <span aria-hidden style={{ display: 'inline-block', width: w, height: h, background: '#1e293b', borderRadius: 4, animation: skelAnim, verticalAlign: 'middle' }} />
)
const SkelBlock = ({ h }: { h: number }) => (
  <div aria-hidden style={{ height: h, background: '#1e293b', borderRadius: 8, animation: skelAnim }} />
)

export default function HomeHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const { data: overview, loading: overviewLoading } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime, loading: regimeLoading } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi, loading: tradeAiLoading } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: risk, loading: riskLoading } = useApi<any>('/api/v2/risk', 60_000)
  const { data: metricsHist, loading: metricsLoading } = useApi<any>('/api/v2/system/metrics-history', 300_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: propHealth } = useApi<any>('/api/v2/health/proposals', 120_000)
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: hermesHealth } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: health } = useApi<any>('/api/v2/health', 120_000)
  const { data: deployData } = useApi<any>('/api/v2/deploy/events?status=open&days=14', 120_000)
  const cmd = command?.data ?? command ?? {}
  const healthFindings: any[] = (health?.findings ?? []).filter((f: any) => f.severity === 'critical' || f.severity === 'warning').slice(0, 3)

  const pv = overview?.portfolio_value
  const todayChg = overview?.today_change
  const journal = overview?.journal ?? {}
  const winRate = journal?.win_rate ?? readiness?.win_rate   // journal (all closed) — matches the headline strip
  const wrTrades = journal?.trade_count ?? readiness?.closed_usable
  const regimeLabel = regime?.regime_label ?? '—'
  const vix = tradeAi?.vix
  const goCount = tradeAi?.go_count ?? 0
  const waitCount = tradeAi?.wait_count ?? 0
  const avoidCount = tradeAi?.avoid_count ?? 0
  const journalPnl = journal?.total_pnl
  const positions = risk?.positions ?? []
  const triggered = positions.filter((p: any) => p.triggered)
  const heat = risk?.portfolio_heat_pct ?? 0
  const pendingCount = proposals?.pending_count ?? 0
  const pipelineStatus = overview?.pipeline_status
  const deployRecent = (deployData?.recent_14d_count ?? deployData?.events?.length ?? 0) as number
  const deployTop = (deployData?.events ?? [])[0] as { symbol?: string; proceeds_usd?: number; sold_at?: string } | undefined

  // Equity curve from daily metrics
  const dailyMetrics = metricsHist?.metrics ?? []
  const equityCurve = [...dailyMetrics]
    .sort((a: any, b: any) => (a.metric_date ?? '').localeCompare(b.metric_date ?? ''))
    .map((m: any) => ({ date: m.metric_date?.slice(5), value: m.portfolio_value }))

  // Data freshness hours
  const lastRepriced = overview?.last_repriced
  let dataAgeHours = 0
  if (lastRepriced) {
    try {
      const parts = lastRepriced.replace(' ET', '').trim()
      // Approximate — show pipeline_status instead of computing exact hours
    } catch { /* */ }
  }

  const tiles = [
    { label: 'PORTFOLIO', value: pv != null ? fmt$(pv, 0) : '—', sub: todayChg != null ? `${todayChg >= 0 ? '+' : ''}${fmt$(todayChg, 0)} today` : '', color: 'var(--text0)',
      drill: { title: 'Portfolio', subtitle: '/api/v2/overview', endpoint: '/api/v2/overview', rows: overview ? [{ portfolio_value: pv, today_change: todayChg, position_count: overview.position_count, as_of: overview.as_of }] : [] } },
    { label: 'PAPER WIN RATE', value: winRate != null ? `${winRate}%` : (journal?.win_rate != null ? `${journal.win_rate}%` : '—'), sub: `${wrTrades ?? 0} trades`, color: (winRate ?? 0) >= 50 ? '#22c55e' : '#f59e0b',
      drill: { title: 'Paper validation win rate', subtitle: '/api/v2/paper-trade-readiness', endpoint: '/api/v2/paper-trade-readiness', rows: readiness ? [{ win_rate: readiness.win_rate, profit_factor: readiness.profit_factor, closed_usable: readiness.closed_usable }] : [] } },
    { label: 'REGIME', value: regimeLabel.replace(/_/g, ' '), sub: vix != null ? `VIX ${vix}` : '', color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b',
      drill: { title: 'Market Regime', subtitle: '/api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest', rows: regime ? [regime] : [] } },
    { label: 'SETUPS', value: `${goCount}/${waitCount}/${avoidCount}`, sub: 'GO/WAIT/NO · latest run', color: goCount > 0 ? '#22c55e' : 'var(--text3)',
      drill: { title: 'Trade Setups', subtitle: 'Latest scanner run only — Trading → Trade AI shows the full scan universe', endpoint: '/api/v2/trade-ai', rows: tradeAi ? [{ scope: 'latest run only', go_count: goCount, wait_count: waitCount, avoid_count: avoidCount, vix, run_label: tradeAi.run_label }] : [] } },
    { label: 'JOURNAL P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—', sub: 'cumulative', color: (journalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444',
      drill: { title: 'Journal P&L', subtitle: '/api/v2/overview → journal', endpoint: '/api/v2/overview', rows: journal ? [journal] : [] } },
  ]

  return (
    <div>
      <style>{'@keyframes ccHomeSkelPulse { 0%, 100% { opacity: .35 } 50% { opacity: .85 } }'}</style>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Home</div>
          <div style={hubSubtitle(terminalUi)}>{overviewLoading ? <Skel w={180} h={12} /> : <>{fmt$(pv ?? 0, 0)} · {overview?.position_count ?? 0} positions · command router</>}</div>
        </div>
        <Link to="/reports" style={{
          padding: '6px 14px', fontSize: 11, fontWeight: 700, borderRadius: 6, textDecoration: 'none',
          background: 'rgba(96,165,250,.12)', color: '#60a5fa', border: '1px solid rgba(96,165,250,.35)',
        }}>Morning brief → Reports</Link>
      </div>

      <>
          {/* Command Center header — matches v2 layout */}
          <div className={terminalUi ? 'cc-panel' : undefined} style={{ ...(terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 20px' }), marginBottom: 16 }}>
            <div style={{ fontSize: terminalUi ? 11 : 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>Command Center</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
              {[
                { label: 'Portfolio', value: pv != null ? fmt$(pv, 0) : '—', color: 'var(--text0)', loading: overviewLoading },
                { label: 'Today', value: todayChg != null ? `${todayChg >= 0 ? '+' : ''}${fmt$(todayChg, 0)}` : '—', color: (todayChg ?? 0) >= 0 ? '#22c55e' : '#ef4444', loading: overviewLoading },
                { label: 'VIX', value: vix ?? '—', color: 'var(--text0)', loading: tradeAiLoading },
                { label: 'Regime', value: regimeLabel ? regimeLabel.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()) : '—', color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b', loading: regimeLoading },
              ].map(t => (
                <div key={t.label}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>{t.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>{t.loading ? <Skel w={72} h={18} /> : t.value}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16, marginTop: 12 }}>
              {[
                { label: 'Last Run', value: tradeAi ? `${tradeAi.run_label ?? '—'} ${tradeAi.run_date ?? ''}` : '—', color: 'var(--text2)', loading: tradeAiLoading },
                { label: 'Setup State', value: `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NO GO`, color: goCount > 0 ? '#22c55e' : 'var(--text2)', loading: tradeAiLoading },
                { label: 'Journal P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—', color: (journalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', loading: overviewLoading },
                { label: `Win Rate (${journal?.trade_count ?? 0} trades)`, value: journal?.win_rate != null ? `${journal.win_rate}%` : '—', color: (journal?.win_rate ?? 0) >= 55 ? '#22c55e' : '#f59e0b', loading: overviewLoading },
              ].map(t => (
                <div key={t.label}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>{t.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: t.color, fontFamily: 'monospace' }}>{t.loading ? <Skel w={110} h={14} /> : t.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              {riskLoading ? <SkelBlock h={100} /> : <RiskGauge value={heat} max={15} threshold={5} label="Portfolio heat" unit="%" height={100} />}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              {riskLoading ? <SkelBlock h={100} /> : <RiskGauge value={triggered.length} max={Math.max(triggered.length, 5)} threshold={1} label="Stops triggered" unit="" height={100} />}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              {riskLoading ? <SkelBlock h={100} /> : <RiskGauge value={positions.filter((p: any) => !p.has_stop).length} max={Math.max(positions.length, 8)} threshold={2} label="Unprotected" unit="" height={100} />}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 16, marginBottom: 16 }}>
            {/* Equity curve */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{metricsLoading ? 'loading…' : `${equityCurve.length} days`} · /system/metrics-history</span>
              </div>
              {metricsLoading ? (
                <SkelBlock h={200} />
              ) : equityCurve.length < 2 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 30, textAlign: 'center' }}>Insufficient daily history ({equityCurve.length} days)</div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={equityCurve}>
                    <defs><linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#60a5fa" stopOpacity={0.3} /><stop offset="95%" stopColor="#60a5fa" stopOpacity={0} /></linearGradient></defs>
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <YAxis domain={['auto', 'auto']} tick={{ fontSize: 9, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} formatter={(v: number) => [fmt$(v, 0), 'Value']} />
                    <Area type="monotone" dataKey="value" stroke="#60a5fa" fill="url(#eqGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Alert rail */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {deployRecent > 0 && (
                <div style={{ padding: '10px 12px', background: 'rgba(34,197,94,.12)', border: '1px solid rgba(34,197,94,.28)', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e' }}>
                    {deployRecent} post-sale redeploy{deployRecent === 1 ? '' : 's'} (&lt;14d)
                  </div>
                  <div style={{ fontSize: 10, color: '#86efac', marginTop: 2 }}>
                    {deployTop?.symbol ? `Latest: ${deployTop.symbol} · ${fmt$(deployTop.proceeds_usd ?? 0, 0)}` : 'Review redeploy targets — advisory only'}
                  </div>
                  <Link to="/portfolio?tab=Redeploy" style={{ display: 'inline-block', marginTop: 8, fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>
                    Portfolio → Redeploy →
                  </Link>
                </div>
              )}
              {triggered.length > 0 && (
                <div style={{ padding: '10px 12px', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(239,68,68,.25)', borderRadius: 8 }}>
                  <div onClick={() => onDrill({ title: `${triggered.length} Stops Triggered`, subtitle: 'Positions below stop', endpoint: '/api/v2/risk', rows: triggered })}
                    style={{ cursor: 'pointer' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>{triggered.length} stops triggered</div>
                    <div style={{ fontSize: 10, color: '#fca5a5', marginTop: 2 }}>{triggered.map((p: any) => p.symbol).join(' ')}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                    <Link to="/risk" style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Risk → Exposure</Link>
                    <Link to="/trading?tab=Open+Trades" style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Trading → Open Trades</Link>
                  </div>
                </div>
              )}
              {heat > 5 && (
                <div onClick={() => onDrill({ title: 'Portfolio Heat', subtitle: `${heat}% over 5% threshold`, endpoint: '/api/v2/risk', rows: [{ portfolio_heat_pct: heat, total_risk: risk?.total_risk_dollars }] })}
                  style={{ padding: '10px 12px', background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 8, cursor: 'pointer' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b' }}>Heat {heat}%</div>
                  <div style={{ fontSize: 10, color: '#fbbf24', marginTop: 2 }}>above 5% threshold</div>
                </div>
              )}
              <div onClick={() => onDrill({ title: 'Data Freshness', subtitle: pipelineStatus ?? '—', endpoint: '/api/v2/overview', rows: [{ pipeline_status: pipelineStatus, last_repriced: lastRepriced, as_of: overview?.as_of }] })}
                style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: pipelineStatus === 'fresh' ? 'var(--text2)' : '#f59e0b' }}>
                  Data: {pipelineStatus ?? '—'}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>last: {lastRepriced ?? '—'}</div>
              </div>
              {propHealth?.execution_readiness && (() => {
                const er = propHealth.execution_readiness
                const lowLink = (er.link_rate_pct ?? 100) < (er.target_link_rate_pct ?? 15)
                const unrouted = (er.broker_unrouted_48h ?? 0) > 0
                return (
                  <div style={{ padding: '10px 12px', background: lowLink || unrouted ? 'rgba(245,158,11,.1)' : 'var(--bg1)',
                    border: `1px solid ${lowLink || unrouted ? 'rgba(245,158,11,.3)' : 'var(--border)'}`, borderRadius: 8 }}>
                    <div onClick={() => onDrill({
                      title: 'Proposal Execution Readiness',
                      subtitle: `${er.link_rate_pct ?? '—'}% link rate · ${er.pending_now ?? 0} pending`,
                      endpoint: '/api/v2/health/proposals',
                      rows: [er],
                    })} style={{ cursor: 'pointer' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: lowLink || unrouted ? '#f59e0b' : 'var(--text2)' }}>
                        Proposals: {er.link_rate_pct ?? '—'}% linked
                      </div>
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                        {er.pending_now ?? 0} pending{unrouted ? ` · ${er.broker_unrouted_48h} unrouted >48h` : ''}
                      </div>
                    </div>
                    <Link to="/trading?tab=Proposals" style={{ display: 'inline-block', marginTop: 6, fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Trading → Proposals →</Link>
                  </div>
                )
              })()}
              {healthFindings.map((f: any, i: number) => {
                const cta = f.cta ?? healthFindingCta(f)
                return (
                  <div key={`${f.type}-${i}`} style={{ padding: '10px 12px', background: f.severity === 'critical' ? 'rgba(239,68,68,.1)' : 'rgba(245,158,11,.08)', border: `1px solid ${f.severity === 'critical' ? 'rgba(239,68,68,.3)' : 'rgba(245,158,11,.25)'}`, borderRadius: 8 }}>
                    <div onClick={() => onDrill({ title: f.type, subtitle: f.category, endpoint: '/api/v2/health', rows: [f] })} style={{ cursor: 'pointer', fontSize: 11, color: f.severity === 'critical' ? '#ef4444' : '#f59e0b', lineHeight: 1.4 }}>
                      {f.message?.slice(0, 120)}{(f.message?.length ?? 0) > 120 ? '…' : ''}
                    </div>
                    <Link to={cta.route.replace(/^\/v3/, '') || '/health'} style={{ display: 'inline-block', marginTop: 6, fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>{cta.label} →</Link>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Action inbox */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 14 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Action Inbox</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>drill to source · use CTAs to act</span>
            </div>
            {triggered.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 11, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 8, fontWeight: 800, color: '#ef4444' }}>P0</span>
                <span onClick={() => onDrill({ title: 'Triggered Stops', subtitle: 'Verify broker executed', endpoint: '/api/v2/risk', rows: triggered })}
                  style={{ flex: 1, cursor: 'pointer', color: '#ef4444', minWidth: 160 }}>
                  {triggered.length} triggered stops — verify broker executed
                </span>
                <Link to="/risk" style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Risk →</Link>
                <Link to="/reports?super=ops&category=advisories" style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', textDecoration: 'none' }}>Reports</Link>
              </div>
            )}
            {pendingCount > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 11, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 8, fontWeight: 800, color: '#ef4444' }}>P0</span>
                <span onClick={() => onDrill({ title: 'Pending Proposals', subtitle: `${pendingCount} awaiting review`, endpoint: '/api/v2/paper-proposals', rows: [{ pending_count: pendingCount }] })}
                  style={{ flex: 1, cursor: 'pointer', color: 'var(--text2)', minWidth: 160 }}>
                  {pendingCount} proposals awaiting review
                </span>
                <Link to="/trading?tab=Proposals" style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Proposals →</Link>
                <Link to="/reports?super=ops&category=paper" style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', textDecoration: 'none' }}>Reports</Link>
              </div>
            )}
            {triggered.length === 0 && pendingCount === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No pending stop/proposal actions</div>
            )}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/risk + /api/v2/paper-proposals</div>
          </div>

          <OperatorInboxPanel />

          {/* ===== Command Center sections (v2 parity, v3 themed) ===== */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(330px,1fr))', gap: 14, marginTop: 16 }}>
            {(cmd.triggered_detail?.length > 0) && (
              <SCard title="Stops Triggered — action required" count={cmd.triggered_detail.length} accent="#ef4444">
                {cmd.triggered_detail.slice(0, 6).map((s: any, i: number) => (
                  <div key={i} onClick={() => onDrill({ title: s.symbol, subtitle: 'stop triggered', endpoint: '/api/v2/command', rows: [s] })} style={{ cursor: 'pointer' }}>
                    <Line color="#ef4444"><span style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{s.symbol}</span><span>Stop {fmt$(s.stop_price ?? s.stop, 2)} · {s.account ?? ''}</span></Line>
                  </div>
                ))}
              </SCard>
            )}
            {(cmd.open_paper_trades?.length > 0) && (
              <SCard title="Paper Trades" count={cmd.open_paper_trades.length} accent="#60a5fa">
                {cmd.open_paper_trades.slice(0, 6).map((t: any, i: number) => {
                  const pl = t.pnl ?? t.unrealized_pnl ?? 0
                  return (
                    <div key={i} onClick={() => onDrill({ title: t.symbol, subtitle: t.strategy_id ?? '', endpoint: '/api/v2/open-trades', rows: [t] })} style={{ cursor: 'pointer' }}>
                      <Line><span><span style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--text0)' }}>{t.symbol}</span> <span style={{ fontSize: 8, color: 'var(--text3)' }}>{t.strategy_id}</span></span><span style={{ color: pl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(pl, 0)} · {t.r_multiple != null ? `${Number(t.r_multiple).toFixed(2)}R` : '—'}</span></Line>
                    </div>
                  )
                })}
              </SCard>
            )}
            {((cmd.top_gainers?.length > 0) || (cmd.top_losers?.length > 0)) && (
              <SCard title="Weekly Movers">
                {(cmd.top_gainers ?? []).slice(0, 3).map((g: any, i: number) => (
                  <Line key={'g' + i} color="#22c55e"><span style={{ fontFamily: 'var(--mono)' }}>{g.symbol}</span><span>+{Number(g.perf_week ?? g.change_pct ?? 0).toFixed(1)}% (1w)</span></Line>
                ))}
                {(cmd.top_losers ?? []).slice(0, 3).map((l: any, i: number) => (
                  <Line key={'l' + i} color="#ef4444"><span style={{ fontFamily: 'var(--mono)' }}>{l.symbol}</span><span>{Number(l.perf_week ?? l.change_pct ?? 0).toFixed(1)}% (1w)</span></Line>
                ))}
              </SCard>
            )}
            {(cmd.cio_pending?.length > 0) && (
              <SCard title="CIO Decisions" count={cmd.cio_pending.length} accent="#a855f7">
                {cmd.cio_pending.slice(0, 6).map((c: any, i: number) => (
                  <div key={i} onClick={() => onDrill({ title: c.symbol, subtitle: c.decision ?? c.action ?? '', endpoint: '/api/v2/cio-decisions', rows: [c] })} style={{ cursor: 'pointer' }}>
                    <Line><span style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--text0)' }}>{c.symbol}</span><span style={{ fontSize: 8, color: '#f59e0b' }}>{(c.decision ?? c.action ?? 'review').toUpperCase()}</span></Line>
                  </div>
                ))}
              </SCard>
            )}
            {(cmd.recovery_watch?.length > 0) && (
              <SCard title="Recovery Watch" count={cmd.recovery_watch.length} accent="#06b6d4">
                {cmd.recovery_watch.slice(0, 6).map((r: any, i: number) => (
                  <Line key={i}><span style={{ fontFamily: 'var(--mono)' }}>{r.symbol}</span><span style={{ color: 'var(--text3)' }}>{r.verdict ?? r.analyst_verdict ?? ''} {r.confidence != null ? `${Math.round((r.confidence <= 1 ? r.confidence * 100 : r.confidence))}%` : ''}</span></Line>
                ))}
              </SCard>
            )}
            {(cmd.top_news?.length > 0) && (
              <SCard title="Portfolio News" count={cmd.top_news.length}>
                {cmd.top_news.slice(0, 5).map((n: any, i: number) => (
                  <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                    <div style={{ fontSize: 9, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}><span style={{ fontFamily: 'var(--mono)', color: '#60a5fa' }}>{n.symbol}</span> {n.title ?? n.headline}</div>
                  </div>
                ))}
              </SCard>
            )}
            {(cmd.agent_health?.length > 0) && (
              <SCard title="Agent Health" count={cmd.agent_health.length} accent="#22c55e">
                {cmd.agent_health.slice(0, 8).map((a: any, i: number) => (
                  <Line key={i}>
                    <span style={{ fontFamily: 'var(--mono)' }}>{a.agent}</span>
                    {/* P0-5: counts here are watchlist_agent_results rows — NOT the same table as the
                        Agents-hub "Actions" column (each agent's home table). Label both windows. */}
                    <span style={{ color: 'var(--text3)' }} title={`Source: ${a.count_source ?? 'watchlist_agent_results'}${a.home_table ? ` — Agents hub counts ${a.home_table}: ${a.home_table_total} all-time` : ''}`}>
                      {a.total_30d ?? a.runs ?? a.actions_taken ?? a.total ?? 0} runs (30d) · {a.total ?? 0} all-time
                    </span>
                  </Line>
                ))}
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>watchlist runs only — Agents hub “Actions” counts each agent's home table (alex→cio_decisions, aegis→aegis_portfolio_briefs)</div>
              </SCard>
            )}
            {/* Hermes info */}
            {hermesHealth && (() => {
              const h = hermesHealth?.data ?? hermesHealth ?? {}
              const sc = h.staging_counts ?? {}
              return (
                <SCard title="Hermes" accent="#e879f9" count={h.kill_switch_active ? 'KILL' : 'live'}>
                  <Line><span>Research staged</span><span style={{ color: 'var(--text0)' }}>{sc.hermes_research_intelligence ?? 0}</span></Line>
                  <Line><span>Validation findings</span><span style={{ color: 'var(--text0)' }}>{sc.hermes_validation_findings ?? 0}</span></Line>
                  <Line><span>Autonomous loop</span><span style={{ color: h.autonomous_loop_active ? '#22c55e' : 'var(--text3)' }}>{h.autonomous_loop_active ? 'ON' : 'idle'}</span></Line>
                  <Line><span>Gateway</span><span style={{ color: h.gateway_status === 'ok' ? '#22c55e' : '#ef4444' }}>{h.gateway_status ?? '—'}</span></Line>
                </SCard>
              )
            })()}
          </div>

          {/* AI Intelligence Briefing (full width) */}
          {cmd.llm_intelligence && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>AI Intelligence Briefing</div>
              {[['Portfolio Risk', cmd.llm_intelligence.portfolio_risk], ['Morning Synthesis', cmd.llm_intelligence.morning_synthesis]].filter(([, v]) => v).map(([k, v]: any) => (
                <div key={k} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 9, color: '#60a5fa', textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>
                  {/* briefings are stored as JSON {"content": "..."} — render the prose, never raw JSON */}
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{(() => {
                    let x: any = v
                    if (typeof x === 'string') { try { x = JSON.parse(x) } catch { return x } }
                    return x?.content ?? x?.summary ?? x?.text ?? String(v)
                  })()}</div>
                </div>
              ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/command → llm_intelligence (gemma3:12b daily)</div>
            </div>
          )}
      </>
    </div>
  )
}
