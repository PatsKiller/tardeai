import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const IntelligenceSources = lazy(() => import('./IntelligenceSources'))
const IntelligenceEntities = lazy(() => import('./IntelligenceEntities'))
const IntelligenceWhiteboard = lazy(() => import('./IntelligenceWhiteboard'))
const ContentHealth = lazy(() => import('./ContentHealth'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function IntelligenceHub() {
  return (
    <TabPage
      title="Intelligence"
      tabs={[
        { id: 'sources', label: 'Sources', component: <Suspense fallback={<Loading />}><IntelligenceSources /></Suspense> },
        { id: 'entities', label: 'Entities', component: <Suspense fallback={<Loading />}><IntelligenceEntities /></Suspense> },
        { id: 'whiteboard', label: 'Whiteboard', component: <Suspense fallback={<Loading />}><IntelligenceWhiteboard /></Suspense> },
        { id: 'health', label: 'Content Health', component: <Suspense fallback={<Loading />}><ContentHealth /></Suspense> },
      ]}
    />
  )
}
