import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['News', 'Research', 'Sources'] as const

export default function IntelligenceHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('News')
  const { data: intel } = useApi<any>('/api/v2/market-intelligence', 120_000)

  const totalArticles = intel?.total_articles ?? 0
  const topSymbols = intel?.top_mentioned_symbols ?? []
  const newsSentiment = intel?.news_sentiment ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Intelligence</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{totalArticles} articles · {topSymbols.length} symbols mentioned</div>
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

      {tab === 'News' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Market Intelligence</div>
          {intel?.news_by_source && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              {(Array.isArray(intel.news_by_source) ? intel.news_by_source : Object.entries(intel.news_by_source)).map((item: any, i: number) => {
                const src = typeof item === 'string' ? item : (Array.isArray(item) ? item[0] : item.source ?? item.name ?? `source-${i}`)
                const cnt = typeof item === 'object' && !Array.isArray(item) ? (item.count ?? item.articles ?? '') : (Array.isArray(item) ? item[1] : '')
                return <span key={i} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text2)' }}>{String(src)}{cnt ? `: ${cnt}` : ''}</span>
              })}
            </div>
          )}
          {topSymbols.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>Top mentioned symbols</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {topSymbols.slice(0, 15).map((s: any, i: number) => {
                  const sym = typeof s === 'string' ? s : (s.symbol ?? `item-${i}`)
                  const mentions = typeof s === 'object' ? s.mentions : null
                  return (
                    <span key={i}
                      onClick={() => onDrill({ title: sym, subtitle: mentions ? `${mentions} mentions` : 'Top mentioned', endpoint: '/api/v2/market-intelligence', rows: [typeof s === 'object' ? s : { symbol: s }] })}
                      style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: 'rgba(96,165,250,.1)', color: '#60a5fa', cursor: 'pointer', fontFamily: 'monospace' }}>
                      {sym}{mentions ? ` (${mentions})` : ''}
                    </span>
                  )
                })}
              </div>
            </div>
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)', padding: '6px 0', borderTop: '1px solid var(--border)' }}>
            Note: /api/v2/intelligence (Brave web search) is depleted per audit. Using /market-intelligence + /news.
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>Source: /api/v2/market-intelligence</div>
        </div>
      )}

      {tab === 'Research' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Research Topics</div>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>Research topics endpoint (/api/v2/research-topics) available — deep integration deferred. Use Intelligence News tab for current market data.</div>
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Brave web search depleted per audit — SearXNG internal search available at :18888</div>
      </div>}
      {tab === 'Sources' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Intelligence sources — Brave depleted per audit</div>}
    </div>
  )
}
