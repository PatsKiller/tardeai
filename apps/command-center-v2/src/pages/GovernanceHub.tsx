import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import TabPage from '../components/TabPage'

const PaperGovernance = lazy(() => import('./PaperGovernance'))
const LearningGovernance = lazy(() => import('./LearningGovernance'))
const Approvals = lazy(() => import('./Approvals'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function GovernanceHub() {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tabMap: Record<string, string> = { 'paper': 'paper', 'learning': 'learning', 'approvals': 'approvals' }
  const defaultTab = tabParam ? tabMap[tabParam] || undefined : undefined

  return (
    <TabPage
      title="Governance"
      defaultTab={defaultTab}
      tabs={[
        { id: 'paper', label: 'Paper Validation', component: <Suspense fallback={<Loading />}><PaperGovernance /></Suspense> },
        { id: 'learning', label: 'Learning Governance', component: <Suspense fallback={<Loading />}><LearningGovernance /></Suspense> },
        { id: 'approvals', label: 'Approvals', component: <Suspense fallback={<Loading />}><Approvals /></Suspense> },
      ]}
    />
  )
}
