import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import ResearchTopicsModal from '../components/ResearchTopicsModal'
import CentralIntelligencePages from '../components/CentralIntelligencePages'
import InferenceLayersPanel from '../components/InferenceLayersPanel'
import IntelligenceNewsTab from '../components/intelligence/IntelligenceNewsTab'
import IntelligenceResearchTab from '../components/intelligence/IntelligenceResearchTab'
import IntelligenceOpsTab from '../components/intelligence/IntelligenceOpsTab'
import IntelligenceLearningTab from '../components/intelligence/IntelligenceLearningTab'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab } from '../lib/terminalHubChrome'
interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Command Center', 'Inferences', 'News', 'Topics', 'Ops', 'Learning'] as const
type Tab = typeof TABS[number]

const TAB_SLUG: Record<Tab, string> = {
  'Command Center': 'command',
  'Inferences': 'inferences',
  'News': 'news',
  'Topics': 'research',
  'Ops': 'ops',
  'Learning': 'learning',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([k, v]) => [v, k])) as Record<string, Tab>
const LEGACY_SLUG: Record<string, Tab> = { quality: 'Command Center', sources: 'Ops', workflow: 'Ops', preview: 'Command Center' }

export default function IntelligenceHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSlug = searchParams.get('tab') ?? ''
  const initialTab = SLUG_TAB[urlSlug] ?? LEGACY_SLUG[urlSlug] ?? 'Command Center'
  const [tab, setTab] = useState<Tab>(initialTab)
  const [showTopics, setShowTopics] = useState(false)

  useEffect(() => {
    const slug = searchParams.get('tab') ?? ''
    if (slug === 'rotation') {
      window.location.replace('/v3/rotation')
      return
    }
    const fromUrl = SLUG_TAB[slug] ?? LEGACY_SLUG[slug]
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
            Command Center = actionable triage queue · News/Topics hold the {totalArticles.toLocaleString()} article corpus · Learning tracks autonomy
            {coordOk ? ' · Hermes live' : ' · Hermes check'}
            {ragPct != null && ` · RAG ${ragPct}%`}
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={hubTab(tab === t, terminalUi)}>{t}</button>
          ))}
          <button onClick={() => setShowTopics(true)} style={{
            ...hubTab(false, terminalUi), border: '1px solid rgba(168,85,247,.45)', color: 'var(--purple)',
          }}>Manage Topics</button>
        </div>
      </div>

      {showTopics && <ResearchTopicsModal onClose={() => setShowTopics(false)} />}

      {tab === 'Command Center' && <CentralIntelligencePages onDrill={onDrill} />}
      {tab === 'Inferences' && <InferenceLayersPanel />}
      {tab === 'News' && <IntelligenceNewsTab onDrill={onDrill} />}
      {tab === 'Topics' && <IntelligenceResearchTab onDrill={onDrill} onManageTopics={() => setShowTopics(true)} />}
      {tab === 'Ops' && <IntelligenceOpsTab onDrill={onDrill} />}
      {tab === 'Learning' && <IntelligenceLearningTab onDrill={onDrill} />}
    </div>
  )
}
