import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { fmt$, fmtPct } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import RiskGauge from '../components/risk/RiskGauge'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Snapshot', 'Morning Command', 'Brief'] as const

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

export default function HomeHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Snapshot')
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: metricsHist } = useApi<any>('/api/v2/system/metrics-history', 300_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: briefData } = useApi<any>('/api/v2/morning-brief', 300_000)
  const { data: repExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=report', 300_000)
  // latest report synthesis across lanes (most recent first)
  const repIntel: any[] = Object.entries(repExt?.map ?? {})
    .flatMap(([key, arr]: any) => (arr as any[]).map((e: any) => ({ ...e, key })))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)))
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: hermesHealth } = useApi<any>('/api/v2/hermes/health', 120_000)
  const cmd = command?.data ?? command ?? {}

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
    { label: 'WIN RATE', value: winRate != null ? `${winRate}%` : (journal?.win_rate != null ? `${journal.win_rate}%` : '—'), sub: `${wrTrades ?? 0} trades`, color: (winRate ?? 0) >= 50 ? '#22c55e' : '#f59e0b',
      drill: { title: 'Win Rate', subtitle: '/api/v2/paper-trade-readiness', endpoint: '/api/v2/paper-trade-readiness', rows: readiness ? [{ win_rate: readiness.win_rate, profit_factor: readiness.profit_factor, closed_usable: readiness.closed_usable }] : [] } },
    { label: 'REGIME', value: regimeLabel.replace(/_/g, ' '), sub: vix != null ? `VIX ${vix}` : '', color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b',
      drill: { title: 'Market Regime', subtitle: '/api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest', rows: regime ? [regime] : [] } },
    { label: 'SETUPS', value: `${goCount}/${waitCount}/${avoidCount}`, sub: 'GO/WAIT/NO', color: goCount > 0 ? '#22c55e' : 'var(--text3)',
      drill: { title: 'Trade Setups', subtitle: '/api/v2/trade-ai', endpoint: '/api/v2/trade-ai', rows: tradeAi ? [{ go_count: goCount, wait_count: waitCount, avoid_count: avoidCount, vix, run_label: tradeAi.run_label }] : [] } },
    { label: 'JOURNAL P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—', sub: 'cumulative', color: (journalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444',
      drill: { title: 'Journal P&L', subtitle: '/api/v2/overview → journal', endpoint: '/api/v2/overview', rows: journal ? [journal] : [] } },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Home</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{fmt$(pv ?? 0, 0)} · {overview?.position_count ?? 0} positions</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Snapshot' && (
        <>
          {/* Command Center header — matches v2 layout */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 20px', marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>Command Center</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
              {[
                { label: 'Portfolio', value: pv != null ? fmt$(pv, 0) : '—', color: 'var(--text0)' },
                { label: 'Today', value: todayChg != null ? `${todayChg >= 0 ? '+' : ''}${fmt$(todayChg, 0)}` : '—', color: (todayChg ?? 0) >= 0 ? '#22c55e' : '#ef4444' },
                { label: 'VIX', value: vix ?? '—', color: 'var(--text0)' },
                { label: 'Regime', value: regimeLabel ? regimeLabel.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()) : '—', color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b' },
              ].map(t => (
                <div key={t.label}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>{t.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>{t.value}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16, marginTop: 12 }}>
              {[
                { label: 'Last Run', value: tradeAi ? `${tradeAi.run_label ?? '—'} ${tradeAi.run_date ?? ''}` : '—', color: 'var(--text2)' },
                { label: 'Setup State', value: `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NO GO`, color: goCount > 0 ? '#22c55e' : 'var(--text2)' },
                { label: 'Journal P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—', color: (journalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' },
                { label: `Win Rate (${journal?.trade_count ?? 0} trades)`, value: journal?.win_rate != null ? `${journal.win_rate}%` : '—', color: (journal?.win_rate ?? 0) >= 55 ? '#22c55e' : '#f59e0b' },
              ].map(t => (
                <div key={t.label}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>{t.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: t.color, fontFamily: 'monospace' }}>{t.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              <RiskGauge value={heat} max={15} threshold={5} label="Portfolio heat" unit="%" height={100} />
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              <RiskGauge value={triggered.length} max={Math.max(triggered.length, 5)} threshold={1} label="Stops triggered" unit="" height={100} />
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              <RiskGauge value={positions.filter((p: any) => !p.has_stop).length} max={Math.max(positions.length, 8)} threshold={2} label="Unprotected" unit="" height={100} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 16, marginBottom: 16 }}>
            {/* Equity curve */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{equityCurve.length} days · /system/metrics-history</span>
              </div>
              {equityCurve.length < 2 ? (
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
              {triggered.length > 0 && (
                <div onClick={() => onDrill({ title: `${triggered.length} Stops Triggered`, subtitle: 'Positions below stop', endpoint: '/api/v2/risk', rows: triggered })}
                  style={{ padding: '10px 12px', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(239,68,68,.25)', borderRadius: 8, cursor: 'pointer' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>{triggered.length} stops triggered</div>
                  <div style={{ fontSize: 10, color: '#fca5a5', marginTop: 2 }}>{triggered.map((p: any) => p.symbol).join(' ')}</div>
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
            </div>
          </div>

          {/* Action inbox */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Action Inbox</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>read-only — drill to source, no write controls</span>
            </div>
            {triggered.length > 0 && (
              <div onClick={() => onDrill({ title: 'Triggered Stops', subtitle: 'Verify broker executed', endpoint: '/api/v2/risk', rows: triggered })}
                style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: '#ef4444' }}>
                {triggered.length} triggered stops — verify broker executed
              </div>
            )}
            {pendingCount > 0 && (
              <div onClick={() => onDrill({ title: 'Pending Proposals', subtitle: `${pendingCount} awaiting review`, endpoint: '/api/v2/paper-proposals', rows: [{ pending_count: pendingCount }] })}
                style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
                {pendingCount} proposals awaiting review
              </div>
            )}
            {triggered.length === 0 && pendingCount === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No pending actions</div>
            )}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/risk + /api/v2/paper-proposals</div>
          </div>

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
                  <Line key={i}><span style={{ fontFamily: 'var(--mono)' }}>{a.agent}</span><span style={{ color: 'var(--text3)' }}>{a.last_run_human ?? a.last_run ?? ''} · {a.runs ?? a.actions_taken ?? a.total ?? 0} runs</span></Line>
                ))}
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
      )}

      {tab === 'Morning Command' && briefData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Morning Brief</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12 }}>Generated: {briefData.generated_at ?? '—'}</div>
          {repIntel.length > 0 && (
            <div style={{ marginBottom: 14, padding: '10px 12px', background: 'rgba(29,155,240,.06)', border: '1px solid rgba(29,155,240,.25)', borderRadius: 8 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>Hermes second read · free external LLM</div>
              {repIntel.slice(0, 2).map((e: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: 'Report — Hermes second read', subtitle: `${e.lane === 'grok' ? 'Grok' : 'ChatGPT'} · ${e.key?.replace('REPORT:', '')}`, endpoint: 'derived', rows: [e], subjectType: 'report', subjectKey: e.key })}
                  style={{ cursor: 'pointer', marginBottom: i === 0 && repIntel.length > 1 ? 8 : 0 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: e.lane === 'grok' ? '#1d9bf0' : '#10a37f' }}>✦ {e.lane === 'grok' ? 'Grok' : 'ChatGPT'}</span>
                  <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 6 }}>{e.at ? new Date(e.at).toLocaleDateString() : ''}</span>
                  <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginTop: 2 }}>{e.recommendation}</div>
                </div>
              ))}
            </div>
          )}
          {briefData.action_items && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#f59e0b', marginBottom: 6 }}>Action Items</div>
              {(Array.isArray(briefData.action_items) ? briefData.action_items : []).map((a: any, i: number) => {
                const label = typeof a === 'string' ? a : (a.message ?? a.title ?? a.action ?? a.code ?? '')
                const code = typeof a === 'object' ? (a.code ?? null) : null
                const sev = (typeof a === 'object' ? (a.severity ?? 'info') : 'info').toLowerCase()
                const sevColor = sev === 'critical' || sev === 'urgent' || sev === 'p1' ? '#ef4444'
                  : sev === 'warning' || sev === 'warn' || sev === 'p2' ? '#f59e0b' : 'var(--text3)'
                return (
                  <div key={i} onClick={() => onDrill({ title: `Action ${i+1}`, subtitle: code ?? '', endpoint: '/api/v2/morning-brief', rows: [typeof a === 'object' ? a : {item: a}] })}
                    style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                    <span style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.3, color: sevColor, minWidth: 44 }}>{sev}</span>
                    <span style={{ fontSize: 11, color: 'var(--text1)', flex: 1 }}>{label}{code ? <span style={{ color: 'var(--text3)', marginLeft: 6, fontSize: 9 }}>· {code}</span> : null}</span>
                  </div>
                )
              })}
            </div>
          )}
          {briefData.strategy_health && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Strategy Health</div>
              {(() => {
                const sh = briefData.strategy_health
                if (typeof sh === 'string') return <div style={{ fontSize: 10, color: 'var(--text2)' }}>{sh}</div>
                const stuck = Array.isArray(sh.stuck_strategies) ? sh.stuck_strategies.length : (sh.stuck_strategies ?? 0)
                const stuckNames = Array.isArray(sh.stuck_strategies) ? sh.stuck_strategies : []
                const Chip = ({ label, val, color }: any) => (
                  <div style={{ flex: 1, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, padding: '7px 4px', textAlign: 'center' }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: color ?? 'var(--text0)' }}>{val}</div>
                    <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
                  </div>
                )
                return (
                  <>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Chip label="Active" val={sh.total_active ?? 0} />
                      <Chip label="New" val={sh.newly_activated ?? 0} color={sh.newly_activated ? '#10b981' : undefined} />
                      <Chip label="Stuck" val={stuck} color={stuck > 0 ? '#ef4444' : undefined} />
                    </div>
                    {stuckNames.length > 0 && (
                      <div style={{ fontSize: 9, color: '#ef4444', marginTop: 6 }}>Stuck: {stuckNames.join(', ')}</div>
                    )}
                  </>
                )
              })()}
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/morning-brief</div>
        </div>
      )}
      {tab === 'Morning Command' && !briefData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading morning brief...</div>}

      {tab === 'Brief' && briefData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Overnight Activity</div>
          {briefData.overnight_activity ? (
            typeof briefData.overnight_activity === 'string'
              ? <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>{briefData.overnight_activity}</div>
              : (() => {
                  const oa = briefData.overnight_activity
                  const rows: [string, any][] = [
                    ['Proposals created', oa.proposals_created],
                    ['Proposals approved', oa.proposals_approved],
                    ['Trades opened', oa.trades_opened],
                    ['Trades closed', oa.trades_closed],
                  ]
                  const blocks = oa.risk_gate_blocks && Object.keys(oa.risk_gate_blocks).length
                  const allZero = rows.every(([, v]) => !v) && !blocks
                  return (
                    <div>
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Since {oa.since ? new Date(oa.since).toLocaleString() : '—'}</div>
                      {allZero ? (
                        <div style={{ fontSize: 11, color: 'var(--text2)' }}>Quiet overnight — no proposals, trades, or risk-gate blocks.</div>
                      ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                          {rows.map(([l, v]) => (
                            <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 8px', background: 'var(--bg2)', borderRadius: 6 }}>
                              <span style={{ fontSize: 10, color: 'var(--text2)' }}>{l}</span>
                              <span style={{ fontSize: 11, fontWeight: 700, color: v ? 'var(--text0)' : 'var(--text3)' }}>{v ?? 0}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {blocks ? (
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>Risk-gate blocks</div>
                          {Object.entries(oa.risk_gate_blocks).map(([k, v]: any) => (
                            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text2)', padding: '2px 0' }}>
                              <span>{k}</span><span style={{ fontWeight: 700 }}>{v}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  )
                })()
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>No overnight activity data</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/morning-brief → overnight_activity</div>
        </div>
      )}
      {tab === 'Brief' && !briefData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading brief...</div>}
    </div>
  )
}
