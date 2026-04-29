import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import MetricTile from '../components/MetricTile'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import PeriodReturnBars from '../components/PeriodReturnBars'
import { useFetch } from '../hooks/useFetch'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtSigned$, fmtPct, deltaColor } from '../lib/format'
import type { Holdings, Notification, NewsData } from '../lib/types'

interface OverviewData {
  portfolio_value: number; total_cash: number; position_count: number; account_count: number; as_of: string
  periods: Record<string, { change_pct: number; change: number; estimated?: boolean }>
  today_change: number; today_pct: number; last_repriced: string
  sectors: { name: string; value: number }[]
  top_movers: { symbol: string; name: string; day_change: number; day_change_pct: number }[]
  trade_ai: { vix: number | null; breadth: string | null; go_count: number; wait_count: number; no_go_count: number; run_date: string; run_label: string }
  journal: { trade_count: number; total_pnl: number; win_rate: number }
  news_count: number; notification_count: number; pending_approvals: number
  pipeline_status: string; pipeline_completed: string
  // Sprint 4A
  total_cash: number; weighted_beta: number
  concentration_alerts: { symbol: string; pct: number }[]
  pending_pipeline: boolean; last_repriced: string
  index_tape: { spy: string | null; qqq: string | null; iwm: string | null }
  delta_events: number
}
interface NotifResp { ok: boolean; notifications: Notification[] }
interface HealthResp { ok: boolean; tables: { name: string; live_rows: number; size: string }[] }
interface OpsData { pipeline: { status: string }; database: { table_count: number; total_rows: number; tables: { name: string; live_rows: number; size: string }[] } }

export default function Overview() {
  const navigate = useNavigate()
  // Primary: normalized v2 overview endpoint (single request)
  const { data: ov } = useApi<OverviewData>('/api/v2/overview')
  // Supplemental: detail data for panels that need full lists
  const { data: h } = useFetch<Holdings>('/data/portfolios/state/holdings.json')
  const { data: notifs } = useFetch<NotifResp>('/api/notifications/recent')
  const { data: ops } = useApi<OpsData>('/api/v2/ops/summary')
  const { data: news } = useFetch<NewsData>('/data/portfolios/state/portfolio_news.json')

  const total = ov?.portfolio_value ?? h?.portfolio_totals?.total_value ?? 0
  const periods = ov?.periods ?? {}
  // Today's change = sum of per-holding day_change (matches v1)
  const dayChange = ov?.today_change ?? 0
  const dayPct = ov?.today_pct ?? 0
  const ytdPct = periods['YTD']?.change_pct ?? 0
  const ytdChange = periods['YTD']?.change ?? 0
  const tai = ov?.trade_ai
  const journal = ov?.journal
  const notifications = notifs?.notifications ?? []
  const catalysts = news?.catalysts ?? []
  const tables = ops?.database?.tables ?? []

  // Sector allocation from v2 overview
  const sectorList = (ov?.sectors ?? []).map(s => [s.name, s.value] as [string, number])
  const sectorTotal = sectorList.reduce((s, [, v]) => s + v, 0)

  // Period return bars
  const hasEstimated = ['1M', '3M', '6M', 'YTD', '1Y'].some(k => periods[k]?.estimated)

  // Top movers today (from v2 overview or fallback to holdings)
  const movers = ov?.top_movers ?? [...(h?.holdings ?? [])]
    .filter(p => !p.is_cash && p.market_value > 100)
    .sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change))
    .slice(0, 6)

  return (
    <>
      <PageHeader title="Overview" subtitle={ov?.as_of ? `Data as of ${ov.as_of} | Pipeline: ${ov.pipeline_status}` : 'Loading...'} />

      {/* BLOCK 1: Stale/Pending banners */}
      {ov?.pending_pipeline && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderRadius: 'var(--radius-md)', background: 'var(--amber-dim)', border: '1px solid var(--amber)', marginBottom: 10, fontSize: 11, color: 'var(--amber)' }}>
          <span>\u26a0</span>
          <span>Holdings imported — pipeline not yet run. Prices may be stale.</span>
        </div>
      )}
      {ov?.pipeline_status === 'stale' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderRadius: 'var(--radius-md)', background: 'var(--amber-dim)', border: '1px solid var(--amber)', marginBottom: 10, fontSize: 11, color: 'var(--amber)' }}>
          <span>\u2139</span>
          <span>Data may be stale — last pipeline: {ov.pipeline_completed?.slice(0, 16) || 'unknown'}</span>
        </div>
      )}

      {/* BLOCK 4: Concentration alerts */}
      {ov?.concentration_alerts && ov.concentration_alerts.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          {ov.concentration_alerts.map(a => (
            <div key={a.symbol} style={{ padding: '4px 10px', borderRadius: 'var(--radius)', background: 'var(--red-dim)', border: '1px solid var(--red)', fontSize: 10, color: 'var(--red)', fontWeight: 600 }}>
              \u26a0 {a.symbol} concentration {a.pct.toFixed(1)}%
            </div>
          ))}
        </div>
      )}

      {/* Top metrics row */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <MetricTile label="Portfolio Value" value={fmt$(total)} delta={`${fmtSigned$(dayChange)} today`} deltaColor={deltaColor(dayChange)} />
        {/* BLOCK 3: Cash + Beta */}
        <MetricTile label="Cash" value={fmt$(ov?.total_cash ?? 0)} delta={total > 0 ? `${((ov?.total_cash ?? 0) / total * 100).toFixed(1)}% of portfolio` : ''} />
        <MetricTile label="Beta" value={(ov?.weighted_beta ?? 0).toFixed(3)} delta="vs SPY 1.000" />
        <MetricTile label="YTD" value={ytdPct != null ? fmtPct(ytdPct) : '—'} delta={ytdChange != null ? fmtSigned$(ytdChange) : ''} deltaColor={deltaColor(ytdPct)} />
        {tai?.vix != null && <MetricTile label="VIX" value={tai.vix.toFixed(1)} deltaColor={tai.vix > 25 ? 'var(--red)' : tai.vix > 18 ? 'var(--amber)' : 'var(--green)'} />}
        {tai?.breadth && <MetricTile label="Regime" value={tai.breadth.includes('Bull') ? '\u{1f7e2} Bull' : tai.breadth.includes('Bear') ? '\u{1f534} Bear' : '\u{1f7e1} ' + tai.breadth} />}
        {tai && <MetricTile label="Setups" value={`${tai.go_count} GO | ${tai.wait_count} W`} delta={tai.run_label ? `${tai.run_label} ${tai.run_date}` : ''} />}
        {journal && journal.trade_count > 0 && <MetricTile label="Journal P&L" value={fmtSigned$(journal.total_pnl)} deltaColor={deltaColor(journal.total_pnl)} delta={`${journal.win_rate}% win rate`} />}
        <MetricTile label="Positions" value={String(ov?.position_count ?? 0)} />
      </div>

      {/* BLOCK 6: Index tape (SPY/QQQ/IWM) */}
      {ov?.index_tape && (ov.index_tape.spy || ov.index_tape.qqq || ov.index_tape.iwm) && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
          {[['SPY', ov.index_tape.spy], ['QQQ', ov.index_tape.qqq], ['IWM', ov.index_tape.iwm]].map(([label, val]) => (
            val ? <span key={label as string} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)' }}>{label} {val}</span> : null
          ))}
          {ov.delta_events > 0 && <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 'var(--radius)', background: 'var(--accent-dim)', color: 'var(--accent)' }}>{ov.delta_events} delta events</span>}
        </div>
      )}

      {/* Two-column main area */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>

        {/* Left: Performance + Sectors */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Period Returns">
            <PeriodReturnBars periods={periods} />
            {hasEstimated && (
              <div style={{ marginTop: 6, fontSize: 9, color: 'var(--amber)', padding: '4px 8px', background: 'var(--amber-dim)', borderRadius: 'var(--radius)' }}>
                * Estimated — repriced from current holdings. May shift after position changes.
              </div>
            )}
          </Card>

          <Card title="Sector Allocation" subtitle={`${sectorList.length} sectors`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {sectorList.map(([name, val]) => {
                const pct = (val / sectorTotal) * 100
                return (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 90, fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                    <div style={{ flex: 1, height: 10, background: 'var(--bg1)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)', opacity: 0.6, borderRadius: 3 }} />
                    </div>
                    <span style={{ width: 40, fontSize: 10, color: 'var(--text3)', textAlign: 'right' }}>{pct.toFixed(1)}%</span>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>

        {/* Right: Top Movers + Notifications */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Top Movers Today" subtitle={`${movers.length} largest moves`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {movers.map(m => (
                <div key={m.symbol + m.account} onClick={() => navigate('/portfolio')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,.02)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                  <span style={{ width: 50, fontWeight: 600, color: 'var(--text0)', fontSize: 11 }}>{m.symbol}</span>
                  <span style={{ flex: 1, fontSize: 10, color: 'var(--text3)' }}>{m.name?.slice(0, 25)}</span>
                  <span style={{ width: 60, textAlign: 'right', fontSize: 11, color: deltaColor(m.day_change), fontWeight: 600 }}>
                    {m.day_change >= 0 ? '+' : ''}{fmt$(m.day_change)}
                  </span>
                  <span style={{ width: 50, textAlign: 'right', fontSize: 10, color: deltaColor(m.day_change_pct) }}>
                    {fmtPct(m.day_change_pct)}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Recent Notifications" subtitle={`${notifications.length} total`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 140, overflowY: 'auto' }}>
              {notifications.slice(0, 8).map((n, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'baseline', padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{
                    fontSize: 9, fontWeight: 600, width: 55,
                    color: n.channel === 'telegram' ? 'var(--accent)' : n.channel === 'gmail' ? 'var(--amber)' : 'var(--text2)',
                  }}>
                    {n.channel}
                  </span>
                  <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)' }}>{n.subject}</span>
                  <span style={{ fontSize: 9, color: n.status === 'sent' ? 'var(--green)' : 'var(--red)' }}>{n.status}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Bottom: News + DB Health */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
        <div>
          <SectionHeader title="Latest News" count={catalysts.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 180, overflowY: 'auto' }}>
              {catalysts.slice(0, 10).map((c, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ width: 40, fontWeight: 600, fontSize: 10, color: 'var(--accent)' }}>{c.portfolio_symbol}</span>
                  <span style={{
                    fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 600,
                    background: c.llm_score >= 80 ? 'var(--green-dim)' : c.llm_score >= 60 ? 'var(--accent-dim)' : 'var(--bg3)',
                    color: c.llm_score >= 80 ? 'var(--green)' : c.llm_score >= 60 ? 'var(--accent)' : 'var(--text3)',
                  }}>
                    {c.llm_score}
                  </span>
                  <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.title}
                  </span>
                  <span style={{ fontSize: 9, color: 'var(--text3)', whiteSpace: 'nowrap' }}>{c.source}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div>
          <SectionHeader title="Database" count={tables.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1, maxHeight: 180, overflowY: 'auto' }}>
              {tables.slice(0, 12).map((t, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, padding: '2px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ flex: 1, fontSize: 10, color: 'var(--text2)' }}>{t.name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text1)', width: 50, textAlign: 'right' }}>{t.live_rows.toLocaleString()}</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)', width: 45, textAlign: 'right' }}>{t.size}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
