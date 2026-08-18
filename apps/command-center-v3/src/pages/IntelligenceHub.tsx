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
import ClosedLoopPanel from './ClosedLoopPanel'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab } from '../lib/terminalHubChrome'
interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Closed Loop', 'Command Center', 'Inferences', 'Signal Quality', 'News', 'Research', 'Sources', 'Workflow'] as const
type Tab = typeof TABS[number]

const TAB_SLUG: Record<Tab, string> = {
  'Closed Loop': 'closed-loop',
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
  const [terminalUi] = useTerminalUi()
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
          <div style={hubTitle()}>Intelligence</div>
          <div style={hubSubtitle(terminalUi)}>
            Command Center = triage queue · News/Research tabs hold the {totalArticles.toLocaleString()} article corpus
            {coordOk ? ' · Hermes live' : ' · Hermes check'}
            {ragPct != null && ` · RAG ${ragPct}%`}
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={hubTab(tab === t, terminalUi)}>{t}</button>
          ))}
          <button onClick={() => setShowTopics(true)} style={{
            ...hubTab(false, terminalUi), border: '1px solid rgba(168,85,247,.45)', color: '#c084fc',
          }}>Manage Topics</button>
        </div>
      </div>

      {showTopics && <ResearchTopicsModal onClose={() => setShowTopics(false)} />}

      {tab === 'Closed Loop' && <ClosedLoopPanel />}
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