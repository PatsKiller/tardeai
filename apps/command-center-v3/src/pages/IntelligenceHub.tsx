import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import ResearchTopicsModal from '../components/ResearchTopicsModal'
import IntelligenceWorkflow from '../components/IntelligenceWorkflow'
import CentralIntelligencePages from '../components/CentralIntelligencePages'
import InferenceLayersPanel from '../components/InferenceLayersPanel'
import IntelligenceNewsTab from '../components/intelligence/IntelligenceNewsTab'
import IntelligenceResearchTab from '../components/intelligence/IntelligenceResearchTab'
import IntelligenceSourcesTab from '../components/intelligence/IntelligenceSourcesTab'
interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Command Center', 'Inferences', 'Signal Quality', 'News', 'Research', 'Sources', 'Workflow'] as const
type Tab = typeof TABS[number]

const TAB_SLUG: Record<Tab, string> = {
  'Command Center': 'command',
  'Inferences': 'inferences',
  'Signal Quality': 'quality',
  'News': 'news',
  'Research': 'research',
  'Sources': 'sources',
  'Workflow': 'workflow',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([k, v]) => [v, k])) as Record<string, Tab>

export default function IntelligenceHub({ onDrill }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSlug = searchParams.get('tab') ?? ''
  const initialTab = SLUG_TAB[urlSlug] ?? 'Command Center'
  const [tab, setTab] = useState<Tab>(initialTab)
  const [showTopics, setShowTopics] = useState(false)

  useEffect(() => {
    const slug = searchParams.get('tab') ?? ''
    if (slug === 'rotation') {
      window.location.replace('/v3/rotation')
      return
    }
    const fromUrl = SLUG_TAB[slug]
    if (fromUrl && fromUrl !== tab) setTab(fromUrl)
  }, [searchParams])

  const selectTab = (t: Tab) => {
    setTab(t)
    const next = new URLSearchParams(searchParams)
    next.set('tab', TAB_SLUG[t])
    setSearchParams(next, { replace: true })
  }

  const { data: intel } = useApi<any>('/api/v2/market-intelligence', 120_000)
  const { data: hermes } = useApi<any>('/api/v2/hermes/health', 120_000)
  const totalArticles = intel?.total_articles ?? 0
  const coordOk = hermes?.coordinator_active
  const ragPct = hermes?.rag_pipeline?.coverage_pct

  return (
    <div>
      <div className="hub-title-row">
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Intelligence</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {totalArticles.toLocaleString()} articles · Hermes {coordOk ? 'coordinator live' : 'coordinator check'}
            {ragPct != null && ` · RAG ${ragPct}%`}
          </div>
        </div>
        <div className="hub-tabs">
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={{
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
      {tab === 'News' && <IntelligenceNewsTab onDrill={onDrill} />}
      {tab === 'Research' && <IntelligenceResearchTab onDrill={onDrill} onManageTopics={() => setShowTopics(true)} />}
      {tab === 'Sources' && <IntelligenceSourcesTab onDrill={onDrill} />}
      {tab === 'Workflow' && <IntelligenceWorkflow onDrill={onDrill} />}
    </div>
  )
}