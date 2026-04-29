import { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useFetch } from '../hooks/useFetch'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, fmtCompact, deltaColor, timeAgo } from '../lib/format'
import type { Enrichment } from '../lib/types'

interface Article { title: string; source: string; llm_score: number; published_at: string; llm_category: string; url?: string }
interface ResearchResp {
  found: boolean
  symbol: string
  company: string
  sector: string
  industry: string
  technicals: Record<string, number | null>
  fundamentals: Record<string, number | null>
  performance: Record<string, number | null>
  articles: Article[]
}
interface NotifResp { ok: boolean; notifications: { notification_type: string; channel: string; subject: string; body_summary: string; sent_at: string; status: string }[] }

export default function Research() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { data: ec } = useFetch<Record<string, Enrichment>>('/data/portfolios/state/ticker_enrichment_cache.json')
  const { data: notifs } = useFetch<NotifResp>('/api/notifications/recent')
  const [query, setQuery] = useState('')

  const tickers = useMemo(() => {
    if (!ec) return []
    return Object.keys(ec).filter(k => !k.startsWith('_') && typeof ec[k] === 'object' && ec[k]?.company).sort()
  }, [ec])

  const filtered = useMemo(() => {
    if (!query) return tickers.slice(0, 30)
    const q = query.toUpperCase()
    return tickers.filter(t => t.includes(q) || (ec?.[t]?.company || '').toUpperCase().includes(q)).slice(0, 30)
  }, [tickers, query, ec])

  const initialTicker = params.get('symbol')?.toUpperCase() || filtered[0] || null
  const [selectedTicker, setSelectedTicker] = useState<string | null>(initialTicker)
  useEffect(() => {
    if (!selectedTicker && filtered[0]) setSelectedTicker(filtered[0])
  }, [filtered, selectedTicker])
  useEffect(() => {
    if (selectedTicker) setParams(prev => { const p = new URLSearchParams(prev); p.set('symbol', selectedTicker); return p }, { replace: true })
  }, [selectedTicker, setParams])

  const { data: research } = useApi<ResearchResp>(selectedTicker ? `/api/v2/research/ticker/${selectedTicker}` : '/api/v2/research/ticker/NA')
  const escalationNotifs = (notifs?.notifications ?? []).filter(n =>
    n.notification_type === 'urgent_alert' || n.notification_type === 'draft_alert'
  ).filter(n => selectedTicker ? n.subject.includes(selectedTicker) || n.body_summary?.includes(selectedTicker) : true)

  return (
    <>
      <PageHeader title="Research" subtitle={`${tickers.length} tickers in enrichment cache`} />
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            type="text"
            placeholder="Search ticker or company..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={searchInput}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1, maxHeight: 680, overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 4, background: 'var(--bg-card)' }}>
            {filtered.map(t => (
              <button key={t} onClick={() => setSelectedTicker(t)} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 8px',
                fontSize: 11, border: 'none', borderRadius: 8,
                background: t === selectedTicker ? 'var(--accent-dim)' : 'transparent',
                color: t === selectedTicker ? 'var(--accent)' : 'var(--text1)', cursor: 'pointer', textAlign: 'left',
              }}>
                <span style={{ fontWeight: 700 }}>{t}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{ec?.[t]?.company?.slice(0, 14) || ''}</span>
              </button>
            ))}
          </div>
        </div>

        {research?.found ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, padding: '10px 14px', background: 'var(--bg2)', borderRadius: 12, border: '1px solid var(--border)' }}>
              <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{research.symbol}</span>
              <span style={{ fontSize: 12, color: 'var(--text2)' }}>{research.company}</span>
              <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{research.sector} / {research.industry?.slice(0, 28)}</span>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <MetricTile label="RSI" value={num(research.technicals.rsi, 1)} deltaColor={(research.technicals.rsi ?? 50) > 70 ? 'var(--red)' : (research.technicals.rsi ?? 50) < 30 ? 'var(--green)' : undefined} />
              <MetricTile label="P/E" value={num(research.fundamentals.pe, 1)} />
              <MetricTile label="Fwd P/E" value={num(research.fundamentals.forward_pe, 1)} />
              <MetricTile label="Mkt Cap" value={research.fundamentals.market_cap_b ? fmtCompact((research.fundamentals.market_cap_b || 0) * 1e9) : '—'} />
              <MetricTile label="Beta" value={num(research.technicals.beta, 2)} />
              <MetricTile label="Short %" value={research.fundamentals.short_float_pct != null ? `${num(research.fundamentals.short_float_pct, 1)}%` : '—'} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Card title="Technical Indicators" subtitle="from enrichment cache">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <TechRow label="SMA 20" value={research.technicals.sma20_pct as number | null} />
                  <TechRow label="SMA 50" value={research.technicals.sma50_pct as number | null} />
                  <TechRow label="SMA 200" value={research.technicals.sma200_pct as number | null} />
                  <TechRow label="ATR" value={research.technicals.atr as number | null} raw />
                  <TechRow label="RVOL" value={research.technicals.rvol as number | null} raw />
                  <TechRow label="52W High" value={research.technicals.week52_high_pct as number | null} />
                  <TechRow label="52W Low" value={research.technicals.week52_low_pct as number | null} />
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button onClick={() => navigate(`/technical?symbol=${research.symbol}`)} style={secondaryAction}>Open Technical</button>
                  <button onClick={() => navigate(`/portfolio?symbol=${research.symbol}`)} style={secondaryAction}>Open Holdings</button>
                </div>
              </Card>

              <Card title="Performance" subtitle="period returns">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <TechRow label="1W" value={research.performance.week as number | null} />
                  <TechRow label="1M" value={research.performance.month as number | null} />
                  <TechRow label="3M" value={research.performance.quarter as number | null} />
                  <TechRow label="6M" value={research.performance.half_year as number | null} />
                  <TechRow label="YTD" value={research.performance.ytd as number | null} />
                  <TechRow label="1Y" value={research.performance.year as number | null} />
                </div>
              </Card>
            </div>

            <SectionHeader title="Recent Articles" count={research.articles.length} />
            <Card>
              {research.articles.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No articles for {research.symbol} in current news batch</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {research.articles.map((a, i) => (
                    <a key={i} href={a.url || `https://finance.yahoo.com/quote/${research.symbol}`} target="_blank" rel="noreferrer" style={{ display: 'flex', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border)', alignItems: 'baseline', textDecoration: 'none' }}>
                      <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 700, flexShrink: 0, background: a.llm_score >= 80 ? 'var(--green-dim)' : a.llm_score >= 60 ? 'var(--accent-dim)' : 'var(--bg3)', color: a.llm_score >= 80 ? 'var(--green)' : a.llm_score >= 60 ? 'var(--accent)' : 'var(--text3)' }}>{a.llm_score}</span>
                      <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)' }}>{a.title}</span>
                      <span style={{ fontSize: 9, color: 'var(--text3)', whiteSpace: 'nowrap' }}>{a.source}</span>
                      {a.published_at && <span style={{ fontSize: 8, color: 'var(--text3)' }}>{timeAgo(a.published_at)}</span>}
                    </a>
                  ))}
                </div>
              )}
            </Card>

            {escalationNotifs.length > 0 && (
              <>
                <SectionHeader title="Active Alerts" count={escalationNotifs.length} />
                <Card>
                  {escalationNotifs.map((n, i) => (
                    <button key={i} onClick={() => navigate('/reports')} style={{ width: '100%', textAlign: 'left', padding: '4px 0', border: 'none', background: 'transparent', fontSize: 11, cursor: 'pointer' }}>
                      <span style={{ color: n.notification_type === 'urgent_alert' ? 'var(--red)' : 'var(--amber)', fontWeight: 600 }}>{n.subject}</span>
                      {n.body_summary && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{n.body_summary.slice(0, 120)}</div>}
                    </button>
                  ))}
                </Card>
              </>
            )}
          </div>
        ) : <div style={{ color: 'var(--text3)', padding: 40 }}>Select a ticker from the list to view research data.</div>}
      </div>
    </>
  )
}

function TechRow({ label, value, raw }: { label: string; value?: number | null; raw?: boolean }) {
  if (value == null) return <div><div style={{ fontSize: 9, color: 'var(--text3)' }}>{label}</div><div style={{ fontSize: 12, color: 'var(--text3)' }}>—</div></div>
  return <div><div style={{ fontSize: 9, color: 'var(--text3)' }}>{label}</div><div style={{ fontSize: 12, fontWeight: 600, color: raw ? 'var(--text0)' : deltaColor(value) }}>{raw ? value.toFixed(2) : fmtPct(value)}</div></div>
}
function num(v?: number | null, d = 1) {
  return v == null ? '—' : v.toFixed(d)
}
const searchInput = { padding: '6px 10px', fontSize: 12, fontFamily: 'var(--mono)', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text0)', outline: 'none' } as const
const secondaryAction = { padding: '6px 10px', borderRadius: 999, border: '1px solid var(--border)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontSize: 10 } as const
