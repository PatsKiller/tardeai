import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import TabPage from '../components/TabPage'

const PaperGovernance = lazy(() => import('./PaperGovernance'))
const LearningGovernance = lazy(() => import('./LearningGovernance'))
const Approvals = lazy(() => import('./Approvals'))
const BrokerAccountAdmin = lazy(() => import('./BrokerAccountAdmin'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function GovernanceHub() {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tabMap: Record<string, string> = { 'paper': 'paper', 'learning': 'learning', 'approvals': 'approvals' }
  const defaultTab = tabParam ? tabMap[tabParam] || undefined : undefined

  return (
    <>
      <div style={{ padding: '0 0 0 0' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4, marginTop: -4 }}>
          Policy rules, approval gates, validation controls, and audit readiness
        </div>
      </div>
      <TabPage
        title="Governance Center"
        defaultTab={defaultTab}
        tabs={[
          { id: 'paper', label: 'Paper Validation', component: <Suspense fallback={<Loading />}><PaperGovernance /></Suspense> },
          { id: 'learning', label: 'Learning & Experiments', component: <Suspense fallback={<Loading />}><LearningGovernance /></Suspense> },
          { id: 'approvals', label: 'Approvals & Tasks', component: <Suspense fallback={<Loading />}><Approvals /></Suspense> },
          { id: 'accounts', label: 'Broker Accounts', component: <Suspense fallback={<Loading />}><BrokerAccountAdmin /></Suspense> },
        ]}
      />
    </>
  )
}
