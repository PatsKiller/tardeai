import type { CSSProperties } from 'react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import SectionHeader from '../components/SectionHeader'
import PeriodReturnBars from '../components/PeriodReturnBars'
import { DoughnutChart, BarChartJS } from '../components/charts'
import ProgressBar from '../components/ProgressBar'
import { useApi } from '../hooks/useApi'
import { useFetch } from '../hooks/useFetch'
import { fmt$, fmtSigned$, deltaColor, timeAgo } from '../lib/format'
import type { Notification, NewsData } from '../lib/types'

interface OverviewData {
  portfolio_value: number
  total_cash: number
  position_count: number
  account_count: number
  as_of: string
  periods: Record<string, { change_pct: number; change: number; estimated?: boolean }>
  today_change: number
  weighted_beta: number
  top_movers: { symbol: string; name: string; day_change: number; day_change_pct: number }[]
  sectors: { name: string; value: number }[]
  trade_ai: { vix: number | null; breadth: string | null; go_count: number; wait_count: number; no_go_count: number; run_date: string; run_label: string }
  journal: { trade_count: number; total_pnl: number; win_rate: number }
  pipeline_status: string
  pipeline_completed: string
  concentration_alerts: { symbol: string; pct: number }[]
  delta_events: number
  pending_approvals: number
  notification_count: number
}
interface WatchlistItem { symbol: string; source: string; company?: string; rsi?: number | null; perf_week_pct?: number | null }
interface WatchlistResp { count: number; items: WatchlistItem[] }
interface RetirementData { key_dates?: Record<string, string | number> }
interface NotifResp { count: number; notifications: Notification[] }
interface OpsData { database?: { tables?: { name: string; live_rows: number }[] } }
interface DividendResp { total_annual: number }
interface TaxData { agi: number; roth_conversions_ytd: number; current_bracket: number; bracket_room_22pct: number; max_additional_conversion: number; extra_from_loss: number }
interface IntelEvent { symbol: string; event_type: string; severity: string; created_at: string }
interface IntelResp { events: IntelEvent[] }

export default function Overview() {
  const navigate = useNavigate()
  const { data: ov } = useApi<OverviewData>('/api/v2/overview')
  const { data: watch } = useApi<WatchlistResp>('/api/v2/watchlist')
  const { data: ret } = useApi<RetirementData>('/api/v2/retirement')
  const { data: ops } = useApi<OpsData>('/api/v2/ops/summary')
  const { data: divs } = useApi<DividendResp>('/api/v2/dividends')
  const { data: notifs } = useApi<NotifResp>('/api/v2/notifications/recent')
  const { data: news } = useFetch<NewsData>('/data/portfolios/state/portfolio_news.json')
  const { data: tax } = useApi<TaxData>('/api/v2/tax-situation')
  const { data: intel } = useApi<IntelResp>('/api/v2/intelligence-events')

  const sectors = ov?.sectors ?? []
  const totalSector = sectors.reduce((s, row) => s + row.value, 0)
  const notifications = notifs?.notifications ?? []
  const topArticles = (news?.catalysts ?? []).slice(0, 8)
  const watchItems = (watch?.items ?? []).slice(0, 6)
  const keyDates = Object.entries(ret?.key_dates ?? {}).slice(0, 5)
  const dbTables = (ops?.database?.tables ?? []).slice(0, 8)
  const incomeTarget = 55000
  const currentIncome = divs?.total_annual ?? 0
  const incomeGap = incomeTarget - currentIncome
  const recentAlerts = (intel?.events ?? []).slice(0, 5)

  const eventCards = useMemo(() => {
    const cards: { tone: 'red' | 'amber' | 'green' | 'blue'; title: string; body: string; cta: string; to: string }[] = []
    for (const c of ov?.concentration_alerts ?? []) {
      cards.push({ tone: 'red', title: `${c.symbol} concentration`, body: `${c.symbol} is ${c.pct.toFixed(1)}% of portfolio. Review trim / rotate options and validate account concentration.`, cta: 'Open Rebalance', to: `/rebalance?symbol=${c.symbol}` })
    }
    if ((ov?.trade_ai?.go_count ?? 0) > 0) {
      cards.push({ tone: 'green', title: `${ov?.trade_ai?.go_count} GO setups`, body: `${ov?.trade_ai?.run_label || 'Latest'} run found fresh setups worth review. Click through to inspect the live setup table.`, cta: 'Open Trade AI', to: '/trade-ai' })
    }
    if ((ov?.journal?.trade_count ?? 0) > 0) {
      cards.push({ tone: 'blue', title: 'Journal review', body: `${ov?.journal?.trade_count} closed trades with ${ov?.journal?.win_rate}% win rate. Review recent executions and holding times.`, cta: 'Open Journal', to: '/journal' })
    }
    if (!cards.length) {
      cards.push({ tone: 'blue', title: 'No acute portfolio events', body: 'Use Holdings, Risk, and Rebalance to review structural positioning and account concentration.', cta: 'Open Holdings', to: '/portfolio' })
    }
    return cards.slice(0, 4)
  }, [ov])

  return (
    <>
      <PageHeader title="Overview" subtitle={ov?.as_of ? `Data as of ${ov.as_of} · pipeline ${ov.pipeline_status}` : 'Loading latest portfolio context…'} />

      {(ov?.pipeline_status === 'stale' || (ov?.concentration_alerts?.length ?? 0) > 0 || (ov?.pending_approvals ?? 0) > 0) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {ov?.pipeline_status === 'stale' && <Banner tone="amber" text={`Data may be stale — last completed ${ov.pipeline_completed ? timeAgo(ov.pipeline_completed) : 'unknown'}`} />}
          {(ov?.concentration_alerts ?? []).map(alert => <button key={alert.symbol} onClick={() => navigate(`/rebalance?symbol=${alert.symbol}`)} style={{ ...bannerBtn(alert.symbol), background: 'var(--red-dim)', color: 'var(--red)' }}>{alert.symbol} concentration {alert.pct.toFixed(1)}%</button>)}
          {(ov?.pending_approvals ?? 0) > 0 && <button onClick={() => navigate('/approvals')} style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, border: '1px solid var(--amber)', borderRadius: 'var(--radius)', background: 'var(--amber-dim)', color: 'var(--amber)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{ov!.pending_approvals} pending approval{ov!.pending_approvals !== 1 ? 's' : ''} — review now</button>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1.05fr 1.45fr 0.95fr', gap: 14, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Sector Pulse">
            {sectors.length > 0 && (
              <div style={{ position: 'relative', height: 140, marginBottom: 12 }}>
                <DoughnutChart
                  labels={sectors.slice(0, 8).map(s => s.name)}
                  data={sectors.slice(0, 8).map(s => s.value)}
                  height={140}
                />
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {sectors.slice(0, 8).map(s => {
                const pct = totalSector ? (s.value / totalSector) * 100 : 0
                const pos = pct >= 10
                return (
                  <button key={s.name} onClick={() => navigate(`/portfolio?sector=${encodeURIComponent(s.name)}`)} style={tileButton(pos ? 'var(--green-dim)' : 'var(--red-dim)')}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: pos ? 'var(--green)' : 'var(--red)' }}>{pos ? '+' : ''}{pct.toFixed(1)}%</div>
                    <div style={{ marginTop: 2, color: 'var(--text1)', fontSize: 11 }}>{s.name}</div>
                  </button>
                )
              })}
            </div>
          </Card>

          <Card title="Setups" subtitle="latest Trade AI scan">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 10 }}>
              <MetricTile label="GO" value={String(ov?.trade_ai?.go_count ?? 0)} deltaColor="var(--green)" />
              <MetricTile label="Wait" value={String(ov?.trade_ai?.wait_count ?? 0)} deltaColor="var(--amber)" />
              <MetricTile label="No Go" value={String(ov?.trade_ai?.no_go_count ?? 0)} deltaColor="var(--red)" />
            </div>
            <button onClick={() => navigate('/trade-ai')} style={primaryAction}>Open Trade AI Workspace</button>
          </Card>

          <Card title="What Changed" subtitle={`${ov?.delta_events ?? 0} score changes`}>
            {(ov?.delta_events ?? 0) > 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>Latest run produced {ov?.delta_events} score/decision deltas. Use Trade AI and Research to review which setups improved or faded.</div>
            ) : (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No major score drift detected in the current run window.</div>
            )}
          </Card>

          <Card title="Income Gap" subtitle="progress toward $55K target">
            <div style={{ position: 'relative', height: 150 }}>
              <DoughnutChart
                labels={['Earned', 'Gap']}
                data={[currentIncome || 14342, Math.max(0, incomeTarget - (currentIncome || 14342))]}
                colors={['#0ecb81', '#f6465d']}
                height={150}
              />
              <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{currentIncome ? Math.round((currentIncome / incomeTarget) * 100) : 26}%</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>of {fmt$(incomeTarget)}</div>
              </div>
            </div>
          </Card>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
            <MetricTile label="Total Value" value={fmt$(ov?.portfolio_value ?? 0)} delta={`${fmtSigned$(ov?.today_change ?? 0)} today`} deltaColor={deltaColor(ov?.today_change)} onClick={() => navigate('/portfolio')} tooltip="4 accounts: 401k, IRA, Roth, Taxable" icon="📊" trend={(ov?.today_change ?? 0) > 0 ? 'up' : (ov?.today_change ?? 0) < 0 ? 'down' : 'flat'} />
            <MetricTile label="Cash" value={fmt$(ov?.total_cash ?? 0)} delta={ov?.portfolio_value ? `${((ov.total_cash / ov.portfolio_value) * 100).toFixed(1)}% of portfolio` : ''} onClick={() => navigate('/portfolio?filter=cash')} tooltip="Available for deployment" icon="💵" />
            <MetricTile label="Dividends/Yr" value={fmt$(divs?.total_annual ?? 0)} delta="See Dividends for live income" deltaColor="var(--green)" onClick={() => navigate('/dividends')} tooltip="Annual projected from 41 positions" icon="📈" trend="up" />
            <MetricTile label="Beta" value={ov?.weighted_beta != null ? ov.weighted_beta.toFixed(3) : '—'} delta="vs SPY 1.0" onClick={() => navigate('/risk')} tooltip="Portfolio volatility relative to S&P 500" icon="⚡" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
            <MetricTile label="Income Target" value="$55,000/yr" delta="annual goal" deltaColor="var(--text3)" tooltip="Min $37.5K · Target $55K · Stretch $67.5K" icon="🎯" />
            <MetricTile label="Current Income" value={fmt$(currentIncome)} delta={`${fmt$(incomeGap)} gap`} deltaColor={incomeGap > 0 ? 'var(--red)' : 'var(--green)'} onClick={() => navigate('/dividends')} tooltip="From 41 dividend positions across 4 accounts" icon="💰" trend={currentIncome > 12000 ? 'up' : 'flat'} />
            <MetricTile label="Income Gap" value={fmt$(incomeGap)} deltaColor="var(--red)" delta={incomeGap > 0 ? 'below target' : 'on target'} tooltip="Need more annual income to reach $55K" icon="📉" trend="down" />
            <MetricTile label="Roth Room" value={tax ? fmt$(tax.bracket_room_22pct || 66883) : '$66,883'} delta={`${tax?.current_bracket || 12}% bracket`} deltaColor="var(--green)" onClick={() => navigate('/retirement')} tooltip="Conversion capacity before 22% bracket" icon="🏦" />
          </div>

          <Card title="Income Progress" compact>
            <ProgressBar
              value={currentIncome}
              max={67500}
              label="Annual Income vs Targets"
              color="var(--green)"
              height={12}
              gradient
              markers={[
                { position: 37500, label: 'Min $37.5K', color: 'var(--amber)' },
                { position: 55000, label: 'Target $55K', color: 'var(--green)' },
                { position: 67500, label: 'Stretch $67.5K', color: 'var(--purple)' },
              ]}
              sublabel={`$${(currentIncome/1000).toFixed(1)}K earned · $${(incomeGap/1000).toFixed(1)}K to target`}
            />
          </Card>

          <Card title="Period Returns" subtitle="click a period for details">
            <PeriodReturnBars periods={ov?.periods ?? {}} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button onClick={() => navigate('/returns')} style={secondaryAction}>Open Returns</button>
              <button onClick={() => navigate('/attribution')} style={secondaryAction}>Open Attribution</button>
            </div>
          </Card>

          {(ov?.top_movers ?? []).length > 0 && (
            <Card title="Top Movers" subtitle="today's biggest moves">
              <BarChartJS
                labels={(ov?.top_movers ?? []).map(m => m.symbol)}
                data={(ov?.top_movers ?? []).map(m => m.day_change_pct)}
                height={120}
              />
            </Card>
          )}

          <SectionHeader title="Portfolio Events" count={eventCards.length} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {eventCards.map((card, idx) => (
              <button key={idx} onClick={() => navigate(card.to)} style={eventCard(card.tone)}>
                <div style={{ fontSize: 9, textTransform: 'uppercase', color: toneText(card.tone), letterSpacing: '.4px' }}>{card.tone === 'red' ? 'Concentration' : card.tone === 'green' ? 'Setups' : card.tone === 'blue' ? 'Journal' : 'Review'}</div>
                <div style={{ fontFamily: 'var(--sans)', fontSize: 18, fontWeight: 800, color: 'var(--text0)', margin: '10px 0 8px' }}>{card.title}</div>
                <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>{card.body}</div>
                <div style={{ marginTop: 10, fontSize: 10, color: 'var(--accent)' }}>{card.cta} →</div>
              </button>
            ))}
          </div>

          <Card title="Latest News" subtitle={`${topArticles.length} catalyst headlines`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {topArticles.map((article, idx) => (
                <button key={idx} onClick={() => navigate(`/research?symbol=${article.portfolio_symbol}`)} style={{ background: 'transparent', border: 'none', textAlign: 'left', padding: '6px 8px', borderRadius: 6, cursor: 'pointer' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ minWidth: 32, fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: article.llm_score >= 80 ? 'var(--green-dim)' : 'var(--accent-dim)', color: article.llm_score >= 80 ? 'var(--green)' : 'var(--accent)' }}>{article.llm_score}</span>
                    <span style={{ minWidth: 28, fontWeight: 700, color: 'var(--accent)' }}>{article.portfolio_symbol}</span>
                    <span style={{ flex: 1, color: 'var(--text1)', fontSize: 11 }}>{article.title}</span>
                    <span style={{ color: 'var(--text3)', fontSize: 9 }}>{article.source}</span>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Recent Notifications" subtitle={`${notifications.length} total`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {notifications.slice(0, 6).map((n, idx) => (
                <button key={idx} onClick={() => navigate('/reports')} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left' }}>
                  <span style={{ color: n.channel === 'telegram' ? 'var(--accent)' : 'var(--text3)', fontSize: 10, minWidth: 56 }}>{n.channel}</span>
                  <span style={{ flex: 1, color: 'var(--text1)', fontSize: 11 }}>{n.subject}</span>
                  <span style={{ color: n.status === 'sent' ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{n.status}</span>
                </button>
              ))}
            </div>
          </Card>

          <Card title="Watchlist" subtitle={`${watch?.count ?? 0} active items`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {watchItems.map(item => (
                <button key={`${item.symbol}-${item.source}`} onClick={() => navigate(`/watchlist?symbol=${item.symbol}`)} style={{ background: 'transparent', border: 'none', textAlign: 'left', cursor: 'pointer' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{item.symbol}</span>
                    <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 999, background: item.source === 'ai_generated' ? 'var(--green-dim)' : 'var(--accent-dim)', color: item.source === 'ai_generated' ? 'var(--green)' : 'var(--accent)' }}>{item.source.replace(/_/g, ' ')}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)' }}>{item.company || 'Coverage pending'} {item.rsi != null ? `· RSI ${item.rsi.toFixed(0)}` : ''}</div>
                </button>
              ))}
            </div>
          </Card>

          {keyDates.length > 0 && (
            <Card title="Key Dates" subtitle="retirement milestones">
              {keyDates.map(([label, value]) => (
                <button key={label} onClick={() => navigate('/retirement')} style={{ width: '100%', display: 'flex', justifyContent: 'space-between', padding: '4px 0', border: 'none', background: 'transparent', fontSize: 11, cursor: 'pointer' }}>
                  <span style={{ color: 'var(--text3)' }}>{label.replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text1)' }}>{String(value)}</span>
                </button>
              ))}
              <div style={{ borderTop: '1px solid var(--border)', marginTop: 6, paddingTop: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 11 }}>
                  <span style={{ color: 'var(--text3)' }}>Medicare</span>
                  <span style={{ color: 'var(--text1)' }}>Dec 2026</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 11 }}>
                  <span style={{ color: 'var(--text3)' }}>Roth YTD</span>
                  <span style={{ color: 'var(--text1)' }}>{tax ? fmt$(tax.roth_conversions_ytd) : '—'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 11 }}>
                  <span style={{ color: 'var(--text3)' }}>Bracket</span>
                  <span style={{ color: 'var(--text1)' }}>{tax ? `${tax.current_bracket}%` : '—'}</span>
                </div>
              </div>
            </Card>
          )}

          <Card title="Daily Brief" subtitle="morning workflow start">
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 8 }}>
              Overnight portfolio intelligence, pending decisions, and next steps from Aegis.
            </div>
            <button onClick={() => navigate('/morning-brief')} style={primaryAction}>Open Daily Brief</button>
          </Card>

          <Card title="Today's Alerts" subtitle={`${recentAlerts.length} recent`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {recentAlerts.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--text3)' }}>No recent alerts.</div>
              )}
              {recentAlerts.map((evt, idx) => (
                <button key={idx} onClick={() => navigate(`/research?symbol=${evt.symbol}`)} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left' }}>
                  <span style={{ minWidth: 36, fontWeight: 700, color: 'var(--accent)', fontSize: 11 }}>{evt.symbol}</span>
                  <span style={{ flex: 1, color: 'var(--text1)', fontSize: 11 }}>{evt.event_type.replace(/_/g, ' ')}</span>
                  <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: evt.severity === 'high' ? 'var(--red-dim)' : evt.severity === 'info' ? 'var(--green-dim)' : 'var(--amber-dim)', color: evt.severity === 'high' ? 'var(--red)' : evt.severity === 'info' ? 'var(--green)' : 'var(--amber)' }}>{evt.severity}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}

function Banner({ tone, text }: { tone: 'red' | 'amber'; text: string }) {
  return <div style={{ padding: '6px 10px', borderRadius: 999, background: tone === 'red' ? 'var(--red-dim)' : 'var(--amber-dim)', color: tone === 'red' ? 'var(--red)' : 'var(--amber)', fontSize: 10, fontWeight: 700 }}>{text}</div>
}
function bannerBtn(key: string): CSSProperties {
  return { border: 'none', cursor: 'pointer', padding: '6px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700 }
}
function tileButton(bg: string): CSSProperties {
  return { padding: '12px 10px', border: '1px solid var(--border)', background: bg, borderRadius: 8, textAlign: 'left', cursor: 'pointer' }
}
function eventCard(tone: string): CSSProperties {
  const color = toneText(tone)
  return { background: 'var(--bg-card)', border: `1px solid ${color}`, borderLeft: `3px solid ${color}`, borderRadius: 12, padding: 14, textAlign: 'left', cursor: 'pointer' }
}
function toneText(tone: string) {
  if (tone === 'red') return 'var(--red)'
  if (tone === 'green') return 'var(--green)'
  if (tone === 'amber') return 'var(--amber)'
  return 'var(--accent)'
}
const primaryAction: CSSProperties = { padding: '9px 12px', borderRadius: 8, border: '1px solid var(--accent)', background: 'var(--accent-dim)', color: 'var(--accent-bright)', fontWeight: 700, cursor: 'pointer' }
const secondaryAction: CSSProperties = { padding: '6px 10px', borderRadius: 999, border: '1px solid var(--border)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontSize: 10 }
