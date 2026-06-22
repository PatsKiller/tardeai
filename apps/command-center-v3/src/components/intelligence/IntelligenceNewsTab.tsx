import { useMemo, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import type { DrillContext } from '../DetailDrawer'

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

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }

function relColor(r: string) {
  if (r === 'high') return '#22c55e'
  if (r === 'medium') return '#f59e0b'
  return 'var(--text3)'
}

function fmtWhen(s?: string) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return s }
}

export default function IntelligenceNewsTab({ onDrill }: Props) {
  const [strategy, setStrategy] = useState('')
  const [source, setSource] = useState('')
  const [relevance, setRelevance] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const { data: intel } = useApi<any>('/api/v2/market-intelligence', 120_000)

  const params = [
    'limit=50',
    `offset=${page * 50}`,
    strategy && `strategy=${encodeURIComponent(strategy)}`,
    source && `source=${encodeURIComponent(source)}`,
    relevance && `relevance=${encodeURIComponent(relevance)}`,
    search && `search=${encodeURIComponent(search)}`,
  ].filter(Boolean).join('&')

  const { data, loading, error } = useApi<{ articles: Article[]; total: number }>(`/api/v2/news/articles?${params}`, 60_000)

  const articles = data?.articles ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / 50))

  const sources = useMemo(() => {
    const raw = intel?.news_by_source
    if (!raw) return []
    if (Array.isArray(raw)) {
      return raw.map((item: any) => typeof item === 'string' ? item : (item.source ?? item.name ?? String(item)))
    }
    return Object.keys(raw)
  }, [intel])

  const input: React.CSSProperties = {
    background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text0)', fontSize: 11, padding: '6px 10px',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ ...card, padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>News Library</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
            {total.toLocaleString()} articles · Yahoo, Google News, Finnhub, Hermes bridge
          </div>
        </div>
        {sources.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {sources.slice(0, 8).map((s: string) => (
              <span key={s} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text2)' }}>{s}</span>
            ))}
          </div>
        )}
      </div>

      <div style={{ ...card, padding: 12, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1.4fr auto', gap: 8, alignItems: 'center' }}>
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
        <select value={relevance} onChange={e => { setRelevance(e.target.value); setPage(0) }} style={input}>
          <option value="">All relevance</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <input value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} placeholder="Search title or symbol…" style={input} />
        <span style={{ fontSize: 10, color: 'var(--text3)', whiteSpace: 'nowrap' }}>Page {page + 1}/{pages}</span>
      </div>

      {loading && !articles.length && (
        <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading articles…</div>
      )}
      {error && (
        <div style={{ ...card, padding: 16, color: '#ef4444', fontSize: 12 }}>Failed to load articles: {error}</div>
      )}

      {!loading && !error && articles.length === 0 && (
        <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No articles match the current filters.</div>
      )}

      <div style={{ ...card, overflow: 'hidden' }}>
        {articles.map((a, i) => (
          <div key={a.id}
            onClick={() => onDrill({ title: a.title, subtitle: `${a.source} · ${a.symbol ?? '—'}`, endpoint: '/api/v2/news/articles', rows: [a] })}
            style={{
              padding: '10px 14px', borderBottom: i < articles.length - 1 ? '1px solid var(--border)' : undefined,
              cursor: 'pointer', display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, alignItems: 'start',
            }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)', lineHeight: 1.35 }}>{a.title}</div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <span>{a.source}</span>
                {a.symbol && <span style={{ fontFamily: 'monospace', color: '#60a5fa' }}>{a.symbol}</span>}
                <span>{a.strategy_type?.replace(/_/g, ' ')}</span>
                <span style={{ color: relColor(a.retirement_relevance) }}>{a.retirement_relevance} relevance</span>
                {a.relevance_score > 0 && <span>score {a.relevance_score}</span>}
              </div>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', textAlign: 'right', whiteSpace: 'nowrap' }}>{fmtWhen(a.created_at)}</div>
          </div>
        ))}
      </div>

      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button disabled={page === 0} onClick={() => setPage(p => p - 1)} style={{
            padding: '5px 14px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--bg2)', color: page === 0 ? 'var(--text3)' : 'var(--text0)', cursor: page === 0 ? 'default' : 'pointer',
          }}>Previous</button>
          <button disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)} style={{
            padding: '5px 14px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--bg2)', color: page >= pages - 1 ? 'var(--text3)' : 'var(--text0)', cursor: page >= pages - 1 ? 'default' : 'pointer',
          }}>Next</button>
        </div>
      )}
    </div>
  )
}