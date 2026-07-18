import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import MarketMoversBoard from '../components/home/MarketMoversBoard'
import BookTreemap from '../components/home/BookTreemap'
import MajorNewsGrid from '../components/home/MajorNewsGrid'
import { plain, plainAlert, runLabel, thresholdSentence } from '../lib/homeLabels'
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

const PERF_PERIODS = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y'] as const

function acctPretty(a: string) {
  return a.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function HomeHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const { data: overview, loading: overviewLoading } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime, loading: regimeLoading } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  // Home only reads header scalars (vix, counts, run label) — the ~500B summary endpoint,
  // not the multi-MB full payload (server-busy 500 loop, 2026-07-17).
  const { data: tradeAi, loading: tradeAiLoading } = useApi<any>('/api/v2/trade-ai/summary', 60_000)
  const { data: risk, loading: riskLoading } = useApi<any>('/api/v2/risk', 60_000)
  const { data: metricsHist, loading: metricsLoading } = useApi<any>('/api/v2/system/metrics-history', 300_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: propHealth } = useApi<any>('/api/v2/health/proposals', 120_000)
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: hermesHealth } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: health } = useApi<any>('/api/v2/health', 120_000)
  const { data: deployData } = useApi<any>('/api/v2/deploy/events?status=open&days=14', 120_000)
  const { data: perfData, loading: perfLoading } = useApi<any>('/api/v2/portfolio/performance', 120_000)
  const { data: posture } = useApi<any>('/api/v2/defense/posture', 300_000)
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

      {/* Defense Desk WS-E: compact market-posture strip — full desk at /v3/defense */}
      {(() => {
        const rows: any[] = (posture as any)?.momentum?.rows || []
        if (!rows.length) return null
        const counts: Record<string, number> = {}
        rows.forEach((r: any) => { if (r.state) counts[r.state] = (counts[r.state] || 0) + 1 })
        const hot = rows.filter((r: any) => (r.state === 'LAGGING' || r.state === 'WEAKENING') && (r.book_pct ?? 0) >= 3)
        return (
          <a href="/v3/defense" style={{ textDecoration: 'none' }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: `3px solid ${hot.length ? '#f59e0b' : '#22c55e'}`, borderRadius: 2, padding: '7px 12px', marginBottom: 12, display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', fontSize: 11 }}>
              <span style={{ fontWeight: 800, fontSize: 10, letterSpacing: '.06em', color: 'var(--text2)' }}>MARKET POSTURE</span>
              {(['LEADING', 'WEAKENING', 'LAGGING', 'IMPROVING'] as const).map(st => counts[st] ? (
                <span key={st} style={{ color: st === 'LEADING' ? '#22c55e' : st === 'LAGGING' ? '#ef4444' : st === 'WEAKENING' ? '#f59e0b' : '#60a5fa', fontWeight: 700 }}>{counts[st]} {st.toLowerCase()}</span>
              ) : null)}
              {hot.map((r: any) => <span key={r.etf} style={{ color: 'var(--text2)' }}>{r.sector.toLowerCase()} <b style={{ color: r.state === 'LAGGING' ? '#ef4444' : '#f59e0b' }}>{r.state}</b> · you {r.book_pct}%</span>)}
              {(() => {
                const hs = (posture as any)?.hedge_state
                if (hs) {
                  const c = hs.state === 'entry_window_open' ? 'var(--green, var(--text0))' : hs.state === 'stand_down' ? 'var(--amber, var(--text2))' : 'var(--text2)'
                  return <span style={{ color: c, fontWeight: 700 }} title="the hedge playbook state machine — click through for the full In-Play rail">{hs.line}</span>
                }
                return null
              })()}
              {(() => {
                const rp = (posture as any)?.rotation_plan_counts
                if (!rp || (!rp.plans && !rp.rollback_open)) return null
                return (
                  <span style={{ color: 'var(--text2)', fontWeight: 700 }}>
                    rotation: {rp.plans} plan{rp.plans !== 1 ? 's' : ''}
                    {rp.tranches_fired ? ` · ${rp.tranches_fired} tranche FIRED` : rp.tranches_armed ? ` · ${rp.tranches_armed} armed` : ''}
                    {rp.rollback_open ? ` · ${rp.rollback_open} rollback OPEN` : ''}
                  </span>
                )
              })()}
              <span style={{ marginLeft: 'auto', color: '#60a5fa', fontWeight: 700 }}>Defense Desk →</span>
            </div>
          </a>
        )
      })()}

      {/* Home v2 Row 1 — market context: the movers board, YOUR book, major news */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 12, marginBottom: 16 }}>
        <MarketMoversBoard />
        <BookTreemap onDrillSymbol={(sym) => onDrill({ title: sym, subtitle: 'holding', endpoint: '/api/v2/portfolio/book-map', rows: [] })} />
        <MajorNewsGrid />
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
                { label: 'Last Run', value: tradeAi ? runLabel(tradeAi.run_label, tradeAi.run_date) : '—', color: 'var(--text2)', loading: tradeAiLoading },
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

          {/* Per-account P/L by period */}
          <div data-testid="home-account-pnl" style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14, overflowX: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8, gap: 10, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>P/L by account · period</div>
                <div
                  style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2, maxWidth: 720, lineHeight: 1.45 }}
                  title={
                    (perfData?.benchmarks?.methodology as string)
                    || 'α = All-accounts % − index ETF %. Book may be transfer-adjusted (≈). Index is ETF price return, not your holdings mix.'
                  }
                >
                  Aggregate $ (top) · % (bottom). YTD ≈ market (ex-transfers) when amber. Index rows: ETF return + α (hover cells).
                  Source: /api/v2/portfolio/performance
                </div>
              </div>
              <Link to="/portfolio?tab=Returns" style={{ fontSize: 11, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>
                Full Returns →
              </Link>
            </div>
            {perfLoading && !perfData ? (
              <SkelBlock h={120} />
            ) : !(perfData?.accounts || overview?.today_by_account) ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>Account performance not available yet.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, minWidth: 560 }}>
                <thead>
                  <tr style={{ color: 'var(--text3)', textAlign: 'right' }}>
                    <th style={{ textAlign: 'left', padding: '5px 8px', fontWeight: 700 }}>Account</th>
                    <th style={{ padding: '5px 8px', fontWeight: 700 }}>Value</th>
                    {PERF_PERIODS.map(p => (
                      <th
                        key={p}
                        style={{ padding: '5px 8px', fontWeight: 700, cursor: 'help' }}
                        title={
                          p === 'YTD'
                            ? 'Year-to-date. Book may show ≈ when transfers excluded from %. Index is ETF calendar YTD.'
                            : p === '1D'
                              ? 'Today. Book = market-day household P/L. Index = ETF session move (see cell tooltip).'
                              : `${p} return. Hover account or index cells for source and α definition.`
                        }
                      >
                        {p}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {/* Portfolio total row */}
                  <tr style={{ borderTop: '1px solid var(--border)' }}>
                    <td
                      style={{ padding: '7px 8px', fontWeight: 800, color: 'var(--text0)', textAlign: 'left', cursor: 'help' }}
                      title="All accounts combined. $ = dollar P/L for period. % is household return used for α (transfer-adjusted when ≈)."
                    >
                      All
                    </td>
                    <td style={{ padding: '7px 8px', fontFamily: 'monospace', fontWeight: 700 }}>{fmt$(perfData?.current_value ?? pv ?? 0, 0)}</td>
                    {PERF_PERIODS.map(p => {
                      const d = perfData?.periods?.[p]
                      // Prefer transfer-adjusted display (YTD) so Home matches Returns; raw NAV misleads on rollovers.
                      const preferDisp = Boolean(d?.nav_is_not_market_only || d?.display_change != null || d?.display_change_pct != null)
                      const ch = preferDisp && d?.display_change != null ? d.display_change : d?.change
                      const pct = preferDisp && d?.display_change_pct != null ? d.display_change_pct : d?.change_pct
                      const col = (ch ?? 0) >= 0 ? '#22c55e' : '#ef4444'
                      const warn = Boolean(d?.nav_is_not_market_only || d?.is_false_positive)
                      const tip = [
                        `All accounts · ${p}`,
                        ch != null ? `P/L ${ch >= 0 ? '+' : ''}${fmt$(ch, 0)}` : null,
                        pct != null ? `Return ${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : null,
                        preferDisp ? 'Using display/≈ market % (ex-transfers when flagged) — this is the % used for index α' : 'Using NAV change %',
                        d?.display_label,
                        d?.adjustment_note,
                        d?.source ? `Source: ${d.source}` : null,
                      ].filter(Boolean).join('\n')
                      return (
                        <td key={p} style={{ padding: '5px 8px', fontFamily: 'monospace', textAlign: 'right', cursor: 'help' }} title={tip}>
                          <div style={{ color: ch != null ? col : 'var(--text3)', fontWeight: 700 }}>
                            {ch != null ? `${ch >= 0 ? '+' : ''}${fmt$(ch, 0)}` : '—'}
                          </div>
                          <div style={{ fontSize: 9, color: warn ? '#f59e0b' : (pct != null ? col : 'var(--text3)') }}>
                            {/* D3 (Home v2): transfer-distorted %s beyond ±50% render n/a — the raw value
                                stays in the cell tooltip. +104.92% Roth-class numbers stop lying. */}
                            {pct != null && warn && Math.abs(Number(pct)) > 50
                              ? 'n/a · transfers'
                              : pct != null ? `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : ''}
                            {warn && !(pct != null && Math.abs(Number(pct)) > 50) ? ' ≈' : ''}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                  {Object.entries(perfData?.accounts || {}).map(([acct, row]: [string, any]) => (
                    <tr key={acct} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '7px 8px', textAlign: 'left', fontWeight: 700, color: 'var(--text1)' }}>{acctPretty(acct)}</td>
                      <td style={{ padding: '7px 8px', fontFamily: 'monospace', fontWeight: 700 }}>{fmt$(row?.current_value ?? 0, 0)}</td>
                      {PERF_PERIODS.map(p => {
                        const d = row?.periods?.[p]
                        // Prefer display_change (ex-transfers / linked Fidelity); 1D falls back to overview live day.
                        const preferDisp = Boolean(d?.nav_is_not_market_only || d?.display_change != null)
                        const ch = (preferDisp && d?.display_change != null ? d.display_change : d?.change)
                          ?? (p === '1D' ? overview?.today_by_account?.[acct]?.change : null)
                        let pct = (preferDisp && d?.display_change_pct != null ? d.display_change_pct : d?.change_pct)
                          ?? (p === '1D' ? overview?.today_by_account?.[acct]?.pct : null)
                        // Funding baseline: hide absurd % even if API lagged
                        if (d?.display_pct_suppressed || (d?.is_false_positive && pct != null && Math.abs(Number(pct)) > 80)) {
                          pct = null
                        }
                        const col = (ch ?? 0) >= 0 ? '#22c55e' : '#ef4444'
                        const warn = Boolean(d?.nav_is_not_market_only || d?.is_false_positive)
                        const tip = [d?.display_label, d?.display_pct_note, d?.adjustment_note].filter(Boolean).join(' · ')
                        return (
                          <td key={p} style={{ padding: '5px 8px', fontFamily: 'monospace', textAlign: 'right' }} title={tip}>
                            <div style={{ color: ch != null ? col : 'var(--text3)', fontWeight: 700 }}>
                              {ch != null ? `${ch >= 0 ? '+' : ''}${fmt$(ch, 0)}` : '—'}
                            </div>
                            <div style={{ fontSize: 9, color: warn ? '#f59e0b' : (pct != null ? col : 'var(--text3)') }}>
                              {/* D3: the Roth +101.92% class — transfer-distorted %s render n/a, raw in tooltip */}
                              {pct != null && warn && Math.abs(Number(pct)) > 50
                                ? 'n/a · transfers'
                                : pct != null ? `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : (ch != null && warn ? '≈ $' : '')}
                              {warn && pct != null && Math.abs(Number(pct)) <= 50 ? ' ≈' : ''}
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                  {/* If performance.accounts empty, fall back to today_by_account only */}
                  {!perfData?.accounts && overview?.today_by_account && Object.entries(overview.today_by_account).map(([acct, row]: [string, any]) => (
                    <tr key={acct} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '7px 8px', textAlign: 'left', fontWeight: 700 }}>{acctPretty(acct)}</td>
                      <td style={{ padding: '7px 8px', fontFamily: 'monospace' }}>{fmt$(row?.value ?? 0, 0)}</td>
                      {PERF_PERIODS.map(p => {
                        if (p !== '1D') return <td key={p} style={{ padding: '5px 8px', color: 'var(--text3)', textAlign: 'right' }}>—</td>
                        const ch = row?.change
                        const pct = row?.pct
                        const col = (ch ?? 0) >= 0 ? '#22c55e' : '#ef4444'
                        return (
                          <td key={p} style={{ padding: '5px 8px', fontFamily: 'monospace', textAlign: 'right' }}>
                            <div style={{ color: col, fontWeight: 700 }}>{ch != null ? `${ch >= 0 ? '+' : ''}${fmt$(ch, 0)}` : '—'}</div>
                            <div style={{ fontSize: 9, color: col }}>{pct != null ? `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : ''}</div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                  {/* Index benchmarks vs book */}
                  {((perfData?.benchmarks?.items as any[]) || []).map((b: any) => (
                    <tr key={b.symbol} style={{ borderTop: '1px solid var(--border)', background: 'rgba(148,163,184,.04)' }}>
                      <td
                        style={{ padding: '7px 8px', textAlign: 'left', cursor: 'help' }}
                        title={b.row_tooltip || `${b.symbol} · ${b.label}: ETF index proxy. α = All-accounts % − this index %.`}
                      >
                        <div style={{ fontFamily: 'monospace', fontWeight: 800, color: '#94a3b8' }}>
                          {b.display_name || `${b.symbol} · ${b.label || ''}`}
                        </div>
                        <div style={{ fontSize: 9, color: 'var(--text4)', marginTop: 1 }}>ETF index · hover cells</div>
                      </td>
                      <td
                        style={{ padding: '7px 8px', fontFamily: 'monospace', fontSize: 10, color: 'var(--text3)', cursor: 'help' }}
                        title="Not a portfolio account — pure index ETF return for comparison only."
                      >
                        index
                      </td>
                      {PERF_PERIODS.map(p => {
                        const bp = b.periods?.[p]
                        const pct = bp?.change_pct
                        const alpha = bp?.alpha_pct
                        const col = (pct ?? 0) >= 0 ? '#22c55e' : '#ef4444'
                        const acol = (alpha ?? 0) >= 0 ? '#22c55e' : '#ef4444'
                        const tip = bp?.tooltip || [
                          `${b.symbol} · ${b.label} · ${p}`,
                          pct != null ? `Index: ${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : 'Index: n/a',
                          alpha != null ? `α (book − index): ${alpha >= 0 ? '+' : ''}${Number(alpha).toFixed(2)}%` : 'α: n/a',
                          bp?.portfolio_pct != null ? `Book % used: ${Number(bp.portfolio_pct) >= 0 ? '+' : ''}${Number(bp.portfolio_pct).toFixed(2)}%` : null,
                          bp?.source ? `Source: ${bp.source}` : null,
                          bp?.method_note,
                          'Not risk-adjusted. Index ≠ your holdings mix.',
                        ].filter(Boolean).join('\n')
                        return (
                          <td key={p} style={{ padding: '5px 8px', fontFamily: 'monospace', textAlign: 'right', cursor: 'help' }} title={tip}>
                            <div style={{ color: pct != null ? col : 'var(--text3)', fontWeight: 700 }}>
                              {pct != null ? `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(2)}%` : '—'}
                            </div>
                            {alpha != null && (
                              <div style={{ fontSize: 9, color: acol, fontWeight: 700 }}>
                                α {alpha >= 0 ? '+' : ''}{Number(alpha).toFixed(2)}%
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
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
                <div onClick={() => onDrill({ title: 'Portfolio Heat', subtitle: thresholdSentence('Heat', heat, 5), endpoint: '/api/v2/risk', rows: [{ portfolio_heat_pct: heat, total_risk: risk?.total_risk_dollars }] })}
                  style={{ padding: '10px 12px', background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 8, cursor: 'pointer' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b' }}>Heat {heat}%</div>
                  <div style={{ fontSize: 10, color: '#fbbf24', marginTop: 2 }}>{thresholdSentence('Heat', heat, 5).split('— ')[1]}</div>
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
                    <div onClick={() => onDrill({ title: f.type, subtitle: f.category, endpoint: '/api/v2/health', rows: [f] })}
                         title={f.message}
                         style={{ cursor: 'pointer', fontSize: 11, color: f.severity === 'critical' ? '#ef4444' : '#f59e0b', lineHeight: 1.4 }}>
                      {(plainAlert(f.message) ?? `${f.message?.slice(0, 120)}${(f.message?.length ?? 0) > 120 ? '…' : ''}`)}
                      {!plainAlert(f.message) && <span style={{ fontSize: 8, fontWeight: 800, marginLeft: 5, padding: '0 4px', border: '1px solid currentColor', borderRadius: 2, opacity: .7 }}>raw</span>}
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
                  <a key={i} href={`/v3/risk?symbol=${s.symbol}`} title="open Risk focused on this symbol" style={{ textDecoration: 'none' }}>
                    <Line color="#ef4444"><span style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{s.symbol}</span><span>Stop {fmt$(s.stop_price ?? s.stop, 2)} · {s.account ?? ''}</span></Line>
                  </a>
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
            {(() => {
              // Prefer command day fields; fall back to overview.top_movers split so the card
              // still works if only the older API is warm.
              const dayG = (cmd.top_day_gainers?.length
                ? cmd.top_day_gainers
                : (overview?.top_movers ?? []).filter((m: any) => (m.day_change ?? 0) > 0)
              ) as any[]
              const dayL = (cmd.top_day_losers?.length
                ? cmd.top_day_losers
                : (overview?.top_movers ?? []).filter((m: any) => (m.day_change ?? 0) < 0)
              ) as any[]
              if (!dayG.length && !dayL.length) return null
              const fmtDay = (m: any) => {
                const d = Number(m.day_change ?? 0)
                const p = m.day_change_pct ?? m.change_pct
                const ds = `${d >= 0 ? '+' : ''}${fmt$(d, 0)}`
                const ps = p != null ? ` ${Number(p) >= 0 ? '+' : ''}${Number(p).toFixed(2)}%` : ''
                return `${ds}${ps}`
              }
              return (
                <SCard title="Today's Winners / Losers">
                  {dayG.slice(0, 3).map((g: any, i: number) => (
                    <a key={'dg' + i} href={`/v3/portfolio?symbol=${g.symbol}`} style={{ textDecoration: 'none' }}>
                      <Line color="#22c55e">
                        <span style={{ fontFamily: 'var(--mono)' }}>{g.symbol}</span>
                        <span>{fmtDay(g)}</span>
                      </Line>
                    </a>
                  ))}
                  {dayL.slice(0, 3).map((l: any, i: number) => (
                    <a key={'dl' + i} href={`/v3/portfolio?symbol=${l.symbol}`} style={{ textDecoration: 'none' }}>
                      <Line color="#ef4444">
                        <span style={{ fontFamily: 'var(--mono)' }}>{l.symbol}</span>
                        <span>{fmtDay(l)}</span>
                      </Line>
                    </a>
                  ))}
                  {(() => {
                    // Reconciliation footer: top-3 each way is a window, not the whole day —
                    // without this the visible rows don't sum to the header TODAY number and
                    // the card reads as "wrong" (operator report 2026-07-17, −7,131 vs −4,303).
                    const shownSum = [...dayG.slice(0, 3), ...dayL.slice(0, 3)]
                      .reduce((s: number, m: any) => s + Number(m.day_change ?? 0), 0)
                    const total = Number(todayChg)
                    if (!Number.isFinite(total)) return null
                    const rest = total - shownSum
                    return (
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5, paddingTop: 4, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}
                        title="Top 3 winners + top 3 losers shown; 'rest of portfolio' is every other position's day change so the card always sums to the header TODAY figure.">
                        <span>rest of portfolio {rest >= 0 ? '+' : ''}{fmt$(rest, 0)}</span>
                        <span>day total {total >= 0 ? '+' : ''}{fmt$(total, 0)}</span>
                      </div>
                    )
                  })()}
                </SCard>
              )
            })()}
            {((cmd.top_gainers?.length > 0) || (cmd.top_losers?.length > 0)) && (
              <SCard title="Weekly Movers">
                {(cmd.top_gainers ?? []).slice(0, 3).map((g: any, i: number) => (
                  <a key={'g' + i} href={`/v3/portfolio?symbol=${g.symbol}`} style={{ textDecoration: 'none' }}>
                    <Line color="#22c55e"><span style={{ fontFamily: 'var(--mono)' }}>{g.symbol}</span><span>+{Number(g.perf_week ?? g.change_pct ?? 0).toFixed(1)}% (1w)</span></Line>
                  </a>
                ))}
                {(cmd.top_losers ?? []).slice(0, 3).map((l: any, i: number) => (
                  <a key={'l' + i} href={`/v3/portfolio?symbol=${l.symbol}`} style={{ textDecoration: 'none' }}>
                    <Line color="#ef4444"><span style={{ fontFamily: 'var(--mono)' }}>{l.symbol}</span><span>{Number(l.perf_week ?? l.change_pct ?? 0).toFixed(1)}% (1w)</span></Line>
                  </a>
                ))}
              </SCard>
            )}
            {(cmd.cio_pending?.length > 0) && (
              <SCard title="CIO Decisions" count={cmd.cio_pending.length} accent="#a855f7">
                {cmd.cio_pending.slice(0, 6).map((c: any, i: number) => (
                  <div key={i} onClick={() => onDrill({ title: c.symbol, subtitle: c.decision ?? c.action ?? '', endpoint: '/api/v2/cio-decisions', rows: [c] })} style={{ cursor: 'pointer' }}>
                    <Line><span style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--text0)' }}>{c.symbol}</span><span title={String(c.decision ?? c.action ?? '')} style={{ fontSize: 8, color: '#f59e0b' }}>{plain(String(c.decision ?? c.action ?? '')) ?? (c.decision ?? c.action ?? 'review')}</span></Line>
                  </div>
                ))}
              </SCard>
            )}
            {(cmd.recovery_watch?.length > 0) && (
              <SCard title="Recovery Watch" count={cmd.recovery_watch.length} accent="#06b6d4">
                {cmd.recovery_watch.slice(0, 6).map((r: any, i: number) => (
                  <a key={i} href={`/v3/risk?symbol=${r.symbol}`} style={{ textDecoration: 'none' }}>
                    <Line><span style={{ fontFamily: 'var(--mono)' }}>{r.symbol}</span><span title={String(r.verdict ?? r.analyst_verdict ?? '')} style={{ color: 'var(--text3)' }}>{plain(String(r.verdict ?? r.analyst_verdict ?? '')) ?? (r.verdict ?? r.analyst_verdict ?? '')} {r.confidence != null ? `${Math.round((r.confidence <= 1 ? r.confidence * 100 : r.confidence))}%` : ''}</span></Line>
                  </a>
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
