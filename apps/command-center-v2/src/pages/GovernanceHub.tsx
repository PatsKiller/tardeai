import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PaperGovernance = lazy(() => import('./PaperGovernance'))
const LearningGovernance = lazy(() => import('./LearningGovernance'))
const Approvals = lazy(() => import('./Approvals'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function GovernanceHub() {
  return (
    <TabPage
      title="Governance"
      tabs={[
        { id: 'paper', label: 'Paper Validation', component: <Suspense fallback={<Loading />}><PaperGovernance /></Suspense> },
        { id: 'learning', label: 'Learning Governance', component: <Suspense fallback={<Loading />}><LearningGovernance /></Suspense> },
        { id: 'approvals', label: 'Approvals', component: <Suspense fallback={<Loading />}><Approvals /></Suspense> },
      ]}
    />
  )
}
