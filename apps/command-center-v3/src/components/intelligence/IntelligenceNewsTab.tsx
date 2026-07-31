import { useMemo, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { useIntelligenceItemState } from '../../hooks/useIntelligenceItemState'
import type { DrillContext } from '../DetailDrawer'
import SynthesizedReportCard from '../SynthesizedReportCard'
import type { ReportCardItem } from '../SynthesizedReportCard'
import IntelligenceCardActions from './IntelligenceCardActions'
import { KPI, SectionHeader, DonutStat, dashboardCard } from './dashboardKit'
import { intelligenceItemId } from '../../lib/intelligenceItemId'

interface Props { onDrill: (ctx: DrillContext) => void }

interface Article {
  id: number
  title: string
  symbol: string | null
  source: string
  source_url: string
  strategy_type: string
  retirement_relevance: string
  relevance_score: number
  created_at: string
}

type RelevanceFilter = '' | 'high' | 'medium' | 'low'

function relToSeverity(r: string): ReportCardItem['severity'] {
  if (r === 'high') return 'warning'
  if (r === 'medium') return 'info'
  return 'info'
}

function articleItemId(a: Article) {
  return intelligenceItemId('news', a.source || 'news', a.symbol ?? undefined, a.title)
}

function toCard(a: Article): ReportCardItem {
  const actions: ReportCardItem['actions'] = []
  if (a.source_url) actions.push({ label: 'Open source', url: a.source_url })
  if (a.symbol) actions.push({ label: 'Portfolio', url: '/v3/portfolio' })
  return {
    id: articleItemId(a),
    type: 'News',
    channel: a.source,
    title: a.title,
    summary: `${a.strategy_type?.replace(/_/g, ' ') ?? ''} · score ${a.relevance_score ?? '—'}`,
    severity: relToSeverity(a.retirement_relevance),
    symbol: a.symbol ?? undefined,
    symbols: a.symbol ? [a.symbol] : [],
    created_at: a.created_at,
    quality_score: a.relevance_score,
    retirement_relevance: a.retirement_relevance,
    actions,
  }
}

export default function IntelligenceNewsTab({ onDrill }: Props) {
  const [strategy, setStrategy] = useState('')
  const [source, setSource] = useState('')
  const [relevance, setRelevance] = useState<RelevanceFilter>('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [showDismissed, setShowDismissed] = useState(false)
  const [kpiFilter, setKpiFilter] = useState<'all' | 'high' | 'no_link'>('all')

  const { data: intel } = useApi<any>('/api/v2/market-intelligence', 120_000)

  const params = [
    'limit=50',
    `offset=${page * 50}`,
    strategy && `strategy=${encodeURIComponent(strategy)}`,
    source && `source=${encodeURIComponent(source)}`,
    relevance && `relevance=${encodeURIComponent(relevance)}`,
    search && `search=${encodeURIComponent(search)}`,
  ].filter(Boolean).join('&')

  const { data, loading, error, refetch: refetchArticles } = useApi<{ articles: Article[]; total: number }>(`/api/v2/news/articles?${params}`, 60_000)

  const articles = data?.articles ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / 50))

  const cardIds = useMemo(() => articles.map(articleItemId), [articles])
  const { byId: stateById, refresh: refreshState } = useIntelligenceItemState(cardIds, 'news')

  const sources = useMemo(() => {
    const raw = intel?.news_by_source
    if (!raw) return []
    if (Array.isArray(raw)) {
      return raw.map((item: any) => typeof item === 'string' ? item : (item.source ?? item.name ?? String(item)))
    }
    return Object.keys(raw)
  }, [intel])

  const stats = useMemo(() => {
    const high = articles.filter(a => a.retirement_relevance === 'high').length
    const noLink = articles.filter(a => !a.source_url).length
    return { high, noLink, sources: sources.length }
  }, [articles, sources])

  const relevanceMix = useMemo(() => {
    const m: Record<string, number> = { high: 0, medium: 0, low: 0 }
    for (const a of articles) {
      const k = a.retirement_relevance || 'low'
      m[k] = (m[k] ?? 0) + 1
    }
    return [
      { name: 'High', value: m.high, color: 'var(--amber)' },
      { name: 'Medium', value: m.medium, color: 'var(--blue)' },
      { name: 'Low', value: m.low, color: 'var(--text3)' },
    ]
  }, [articles])

  const visible = useMemo(() => {
    return articles.filter(a => {
      const st = stateById.get(articleItemId(a)) ?? 'active'
      if (st === 'dismissed' && !showDismissed) return false
      if (kpiFilter === 'high' && a.retirement_relevance !== 'high') return false
      if (kpiFilter === 'no_link' && a.source_url) return false
      return true
    })
  }, [articles, stateById, showDismissed, kpiFilter])

  const dismissedCount = useMemo(() => articles.filter(a => stateById.get(articleItemId(a)) === 'dismissed').length, [articles, stateById])

  const input: React.CSSProperties = {
    background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text0)', fontSize: 11, padding: '6px 10px',
  }

  const onActionDone = () => { refreshState(); refetchArticles() }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <SectionHeader
        title="News Intelligence"
        subtitle={`${total.toLocaleString()} articles in corpus · Yahoo, Google News, Finnhub, Hermes bridge`}
        accent="var(--blue)"
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <KPI label="Corpus total" value={total.toLocaleString()} sub="all sources" active={kpiFilter === 'all'} onClick={() => setKpiFilter('all')} />
        <KPI label="High relevance" value={stats.high} sub="this page" color="var(--amber)" active={kpiFilter === 'high'} onClick={() => setKpiFilter(kpiFilter === 'high' ? 'all' : 'high')} />
        <KPI label="Missing source link" value={stats.noLink} sub="this page" color={stats.noLink ? 'var(--red)' : 'var(--green)'} active={kpiFilter === 'no_link'} onClick={() => setKpiFilter(kpiFilter === 'no_link' ? 'all' : 'no_link')} />
        <KPI label="Active sources" value={stats.sources} sub="ingestion feeds" color="var(--text0)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 12 }}>
        <div style={{ ...dashboardCard, padding: 12, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1.4fr auto', gap: 8, alignItems: 'center' }}>
          <select value={strategy} onChange={e => { setStrategy(e.target.value); setPage(0) }} style={input}>
            <option value="">All strategies</option>
            <option value="dividend_income">Dividend income</option>
            <option value="retirement_planning">Retirement planning</option>
            <option value="tax_planning">Tax planning</option>
            <option value="roth_conversion">Roth conversion</option>
            <option value="trust_estate">Trust & estate</option>
          </select>
          <select value={source} onChange={e => { setSource(e.target.value); setPage(0) }} style={input}>
            <option value="">All sources</option>
            {sources.map((s: string) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={relevance} onChange={e => { setRelevance(e.target.value as RelevanceFilter); setPage(0) }} style={input}>
            <option value="">All relevance</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} placeholder="Search title or symbol…" style={input} />
          <span style={{ fontSize: 10, color: 'var(--text3)', whiteSpace: 'nowrap' }}>Page {page + 1}/{pages}</span>
        </div>
        <div style={{ ...dashboardCard, padding: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Relevance mix (page)</div>
          <DonutStat data={relevanceMix} height={100} onSliceClick={name => setRelevance(name.toLowerCase() as RelevanceFilter)} />
        </div>
      </div>

      {loading && !articles.length && (
        <div style={{ ...dashboardCard, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading articles…</div>
      )}
      {error && (
        <div style={{ ...dashboardCard, padding: 16, color: 'var(--red)', fontSize: 12 }}>Failed to load articles: {error}</div>
      )}

      {dismissedCount > 0 && (
        <button type="button" onClick={() => setShowDismissed(v => !v)} style={{ ...input, cursor: 'pointer', alignSelf: 'flex-start' }}>
          {showDismissed ? 'Hide' : 'Show'} {dismissedCount} dismissed
        </button>
      )}

      {!loading && !error && visible.length === 0 && (
        <div style={{ ...dashboardCard, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No articles match the current filters.</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {visible.map(a => {
          const card = toCard(a)
          const st = stateById.get(card.id)
          return (
            <div
              key={a.id}
              onClick={() => onDrill({ title: a.title, subtitle: `${a.source} · ${a.symbol ?? '—'}`, endpoint: '/api/v2/news/articles', rows: [a] })}
              style={{ cursor: 'pointer', opacity: st === 'dismissed' ? 0.55 : st === 'reviewed' ? 0.85 : 1 }}
            >
              <SynthesizedReportCard
                item={card}
                footer={
                  <IntelligenceCardActions
                    itemId={card.id}
                    itemType="news"
                    symbol={a.symbol ?? undefined}
                    onDone={onActionDone}
                  />
                }
              />
            </div>
          )
        })}
      </div>

      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button disabled={page === 0} onClick={() => setPage(p => p - 1)} style={{ ...input, cursor: page === 0 ? 'default' : 'pointer' }}>Previous</button>
          <button disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)} style={{ ...input, cursor: page >= pages - 1 ? 'default' : 'pointer' }}>Next</button>
        </div>
      )}
    </div>
  )
}
