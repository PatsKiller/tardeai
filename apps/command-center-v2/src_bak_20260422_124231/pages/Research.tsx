import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useFetch } from '../hooks/useFetch'
import { fmt$, fmtPct, fmtCompact, deltaColor, timeAgo } from '../lib/format'
import type { Enrichment, NewsData, Catalyst } from '../lib/types'

interface NotifResp { ok: boolean; notifications: { notification_type: string; channel: string; subject: string; body_summary: string; sent_at: string; status: string }[] }

export default function Research() {
  const { data: ec } = useFetch<Record<string, Enrichment>>('/data/portfolios/state/ticker_enrichment_cache.json')
  const { data: news } = useFetch<NewsData>('/data/portfolios/state/portfolio_news.json')
  const { data: notifs } = useFetch<NotifResp>('/api/notifications/recent')
  const [query, setQuery] = useState('')
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

  const tickers = useMemo(() => {
    if (!ec) return []
    return Object.keys(ec).filter(k => !k.startsWith('_') && typeof ec[k] === 'object' && ec[k]?.company).sort()
  }, [ec])

  const filtered = useMemo(() => {
    if (!query) return tickers.slice(0, 20)
    const q = query.toUpperCase()
    return tickers.filter(t => t.includes(q) || (ec?.[t]?.company || '').toUpperCase().includes(q)).slice(0, 20)
  }, [tickers, query, ec])

  const ticker = selectedTicker || filtered[0] || null
  const enrich = ticker ? ec?.[ticker] : null

  // Articles for selected ticker
  const allArticles = news?.all_scored || news?.catalysts || []
  const tickerArticles = useMemo(() => {
    if (!ticker) return []
    return allArticles.filter((a: Catalyst) => a.portfolio_symbol === ticker).slice(0, 12)
  }, [ticker, allArticles])

  // Escalation-related notifications
  const escalationNotifs = (notifs?.notifications ?? []).filter(n =>
    n.notification_type === 'urgent_alert' || n.notification_type === 'draft_alert'
  )

  return (
    <>
      <PageHeader title="Research" subtitle={`${tickers.length} tickers in enrichment cache`} />

      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 12 }}>

        {/* Left: Ticker selector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            type="text"
            placeholder="Search ticker..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{
              padding: '6px 10px', fontSize: 12, fontFamily: 'var(--mono)',
              background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              color: 'var(--text0)', outline: 'none',
            }}
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1, maxHeight: 500, overflowY: 'auto' }}>
            {filtered.map(t => (
              <button
                key={t}
                onClick={() => setSelectedTicker(t)}
                style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '5px 8px', fontSize: 11, border: 'none', borderRadius: 'var(--radius)',
                  background: t === ticker ? 'var(--accent-dim)' : 'transparent',
                  color: t === ticker ? 'var(--accent)' : 'var(--text1)',
                  cursor: 'pointer', fontFamily: 'var(--mono)', textAlign: 'left',
                }}
              >
                <span style={{ fontWeight: 600 }}>{t}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                  {ec?.[t]?.company?.slice(0, 12) || ''}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Right: Ticker detail */}
        {enrich ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

            {/* Header strip */}
            <div style={{
              display: 'flex', alignItems: 'baseline', gap: 12,
              padding: '10px 14px', background: 'var(--bg2)', borderRadius: 'var(--radius-lg)',
              border: '1px solid var(--border)',
            }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>{ticker}</span>
              <span style={{ fontSize: 12, color: 'var(--text2)' }}>{enrich.company}</span>
              <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{enrich.sector} / {enrich.industry?.slice(0, 25)}</span>
            </div>

            {/* KPI strip */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <MetricTile label="RSI" value={enrich.rsi?.toFixed(1) ?? '—'} deltaColor={
                enrich.rsi > 70 ? 'var(--red)' : enrich.rsi < 30 ? 'var(--green)' : undefined
              } />
              <MetricTile label="P/E" value={enrich.pe?.toFixed(1) ?? '—'} />
              <MetricTile label="Fwd P/E" value={enrich.forward_pe?.toFixed(1) ?? '—'} />
              <MetricTile label="Mkt Cap" value={enrich.market_cap_b ? fmtCompact(enrich.market_cap_b * 1e9) : '—'} />
              <MetricTile label="Beta" value={enrich.beta?.toFixed(2) ?? '—'} />
              <MetricTile label="Short %" value={enrich.short_float_pct?.toFixed(1) + '%' ?? '—'} />
            </div>

            {/* Two column: Technicals + Performance */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Card title="Technical Indicators">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <TechRow label="SMA 20" value={enrich.sma20_pct} />
                  <TechRow label="SMA 50" value={enrich.sma50_pct} />
                  <TechRow label="SMA 200" value={enrich.sma200_pct} />
                  <TechRow label="ATR" value={enrich.atr} raw />
                  <TechRow label="RVOL" value={enrich.rvol} raw />
                  <TechRow label="52W High" value={enrich.week52_high_pct} />
                  <TechRow label="52W Low" value={enrich.week52_low_pct} />
                  <TechRow label="Volatility W" value={enrich.volatility_w_pct} />
                </div>
              </Card>

              <Card title="Performance">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <TechRow label="1W" value={enrich.perf_week_pct} />
                  <TechRow label="1M" value={enrich.perf_month_pct} />
                  <TechRow label="3M" value={enrich.perf_quarter_pct} />
                  <TechRow label="6M" value={enrich.perf_halfyr_pct} />
                  <TechRow label="YTD" value={enrich.perf_ytd_pct} />
                  <TechRow label="1Y" value={enrich.perf_year_pct} />
                  <div><div style={{ fontSize: 9, color: 'var(--text3)' }}>EPS TTM</div><div style={{ fontSize: 12, color: 'var(--text0)' }}>{enrich.eps_ttm != null ? fmt$(enrich.eps_ttm, 2) : '—'}</div></div>
                  <div><div style={{ fontSize: 9, color: 'var(--text3)' }}>EPS Growth 5Y</div><div style={{ fontSize: 12, color: deltaColor(enrich.eps_past_5y ?? 0) }}>{enrich.eps_past_5y ? fmtPct(enrich.eps_past_5y) : '—'}</div></div>
                </div>
              </Card>
            </div>

            {/* Article stream */}
            <SectionHeader title="Recent Articles" count={tickerArticles.length} />
            <Card>
              {tickerArticles.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No articles for {ticker} in current news batch</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {tickerArticles.map((a, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border)', alignItems: 'baseline' }}>
                      <span style={{
                        fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 600, flexShrink: 0,
                        background: a.llm_score >= 80 ? 'var(--green-dim)' : a.llm_score >= 60 ? 'var(--accent-dim)' : 'var(--bg3)',
                        color: a.llm_score >= 80 ? 'var(--green)' : a.llm_score >= 60 ? 'var(--accent)' : 'var(--text3)',
                      }}>
                        {a.llm_score}
                      </span>
                      <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)' }}>{a.title}</span>
                      <span style={{ fontSize: 9, color: 'var(--text3)', whiteSpace: 'nowrap' }}>{a.source}</span>
                      {a.published_at && <span style={{ fontSize: 8, color: 'var(--text3)' }}>{timeAgo(a.published_at)}</span>}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Escalation alerts */}
            {escalationNotifs.length > 0 && (
              <>
                <SectionHeader title="Active Alerts" count={escalationNotifs.length} />
                <Card>
                  {escalationNotifs.map((n, i) => (
                    <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                      <span style={{ color: n.notification_type === 'urgent_alert' ? 'var(--red)' : 'var(--amber)', fontWeight: 600 }}>
                        {n.subject}
                      </span>
                      {n.body_summary && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{n.body_summary.slice(0, 120)}</div>}
                    </div>
                  ))}
                </Card>
              </>
            )}
          </div>
        ) : (
          <div style={{ color: 'var(--text3)', padding: 40, textAlign: 'center' }}>
            Select a ticker from the list to view research data
          </div>
        )}
      </div>
    </>
  )
}

function TechRow({ label, value, raw }: { label: string; value?: number; raw?: boolean }) {
  if (value == null) return <div><div style={{ fontSize: 9, color: 'var(--text3)' }}>{label}</div><div style={{ fontSize: 12, color: 'var(--text3)' }}>—</div></div>
  return (
    <div>
      <div style={{ fontSize: 9, color: 'var(--text3)' }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: raw ? 'var(--text0)' : deltaColor(value) }}>
        {raw ? value.toFixed(2) : fmtPct(value)}
      </div>
    </div>
  )
}
