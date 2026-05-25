import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import TabPage from '../components/TabPage'

const IntelligenceSources = lazy(() => import('./IntelligenceSources'))
const IntelligenceEntities = lazy(() => import('./IntelligenceEntities'))
const IntelligenceWhiteboard = lazy(() => import('./IntelligenceWhiteboard'))
const ContentHealth = lazy(() => import('./ContentHealth'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function IntelligenceHub() {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tabMap: Record<string, string> = { 'sources': 'sources', 'entities': 'entities', 'whiteboard': 'whiteboard', 'content-health': 'health', 'health': 'health' }
  const defaultTab = tabParam ? tabMap[tabParam] || undefined : undefined

  return (
    <TabPage
      title="Intelligence"
      defaultTab={defaultTab}
      tabs={[
        { id: 'sources', label: 'Sources', component: <Suspense fallback={<Loading />}><IntelligenceSources /></Suspense> },
        { id: 'entities', label: 'Entities', component: <Suspense fallback={<Loading />}><IntelligenceEntities /></Suspense> },
        { id: 'whiteboard', label: 'Whiteboard', component: <Suspense fallback={<Loading />}><IntelligenceWhiteboard /></Suspense> },
        { id: 'health', label: 'Content Health', component: <Suspense fallback={<Loading />}><ContentHealth /></Suspense> },
      ]}
    />
  )
}
