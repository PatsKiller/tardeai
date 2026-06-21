import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import ResearchTopicsModal from '../components/ResearchTopicsModal'
import IntelligenceWorkflow from '../components/IntelligenceWorkflow'
import CentralIntelligencePages from '../components/CentralIntelligencePages'
import InferenceLayersPanel from '../components/InferenceLayersPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Command Center', 'Inferences', 'Signal Quality', 'News', 'Research', 'Sources', 'Workflow', 'Rotation'] as const

export default function IntelligenceHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Command Center')
  const [showTopics, setShowTopics] = useState(false)
  const { data: intel } = useApi<any>('/api/v2/market-intelligence', 120_000)
  const { data: researchData } = useApi<any>('/api/v2/research-topics', 120_000)
  const { data: rotation } = useApi<any>('/api/v2/rotation/summary', 300_000)

  const totalArticles = intel?.total_articles ?? 0
  const topSymbols = intel?.top_mentioned_symbols ?? []
  const newsSentiment = intel?.news_sentiment ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Intelligence</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{totalArticles} articles · {topSymbols.length} symbols mentioned · consolidated command + signal quality</div>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
          <button onClick={() => setShowTopics(true)} style={{
            padding: '4px 12px', fontSize: 11, borderRadius: 5, border: '1px solid rgba(168,85,247,.3)',
            cursor: 'pointer', background: 'rgba(168,85,247,.15)', color: '#a855f7', fontWeight: 600,
          }}>Manage Topics</button>
        </div>
      </div>

      {showTopics && <ResearchTopicsModal onClose={() => setShowTopics(false)} />}

      {tab === 'Command Center' && <CentralIntelligencePages mode="command" onDrill={onDrill} />}
      {tab === 'Inferences' && <InferenceLayersPanel />}
      {tab === 'Signal Quality' && <CentralIntelligencePages mode="quality" onDrill={onDrill} />}

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

      {tab === 'Research' && researchData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Research Topics</div>
          <div style={{ display: 'flex', gap: 12, marginBottom: 12, fontSize: 10 }}>
            <span style={{ color: '#60a5fa' }}>User topics: {researchData.user_topic_count ?? 0}</span>
            <span style={{ color: 'var(--text2)' }}>Monitor: {researchData.monitor_topic_count ?? 0}</span>
            <span style={{ color: researchData.gap_count > 0 ? '#f59e0b' : 'var(--text3)' }}>Gaps: {researchData.gap_count ?? 0}</span>
          </div>
          {(researchData.user_topics ?? []).map((t: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: t.topic ?? `Topic ${i}`, subtitle: `${t.source ?? ''} · ${t.status ?? ''}`, endpoint: '/api/v2/research-topics', rows: [t] })}
              style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <div style={{ fontWeight: 600, color: 'var(--text0)' }}>{t.topic}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{t.source} · {t.status} · researched {t.research_count ?? 0}x</div>
            </div>
          ))}
          {researchData.research_gaps?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#f59e0b', marginBottom: 6 }}>Research Gaps ({researchData.gap_count})</div>
              {(researchData.research_gaps ?? []).slice(0, 8).map((g: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: g.topic ?? `Gap ${i}`, subtitle: g.source ?? '', endpoint: '/api/v2/research-topics', rows: [g] })}
                  style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, color: 'var(--text2)' }}>
                  {g.topic ?? g.symbol ?? JSON.stringify(g).slice(0, 80)}
                </div>
              ))}
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/research-topics · Brave depleted — SearXNG at :18888</div>
        </div>
      )}
      {tab === 'Sources' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Intelligence sources — Brave depleted per audit · consolidated pages use morning brief, command, risk, trade AI, watchlist, open trades, market intelligence, research topics, and Hermes report reads.</div>}
      {tab === 'Workflow' && <IntelligenceWorkflow onDrill={onDrill} />}

      {tab === 'Rotation' && (() => {
        const rs = rotation?.summary ?? {}
        const cells: [string, any, string][] = [
          ['Trim review', rs.trim_review, '#ef4444'],
          ['Add review', rs.add_review, '#22c55e'],
          ['Rotation ideas', rs.rotation_ideas, '#60a5fa'],
          ['Watch', rs.watch, '#f59e0b'],
        ]
        return (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Rotation Intelligence</div>
              <span style={{ fontSize: 9, color: '#f59e0b', fontWeight: 600 }}>advisory only · no broker action</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
              {cells.map(([label, val, c]) => (
                <div key={label} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 20, fontWeight: 800, color: c }}>{val ?? '—'}</div>
                  <div style={{ fontSize: 8.5, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
                </div>
              ))}
            </div>
            <a href="/v3/rotation" style={{
              display: 'inline-block', padding: '6px 14px', fontSize: 11, fontWeight: 700, borderRadius: 6,
              textDecoration: 'none', background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid #60a5fa55',
            }}>Open Rotation Intelligence →</a>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 10 }}>
              Local review + Grok OAuth prompt, no API key · source: /api/v2/rotation/summary
            </div>
          </div>
        )
      })()}
    </div>
  )
}
