import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PaperOutcomes = lazy(() => import('./PaperOutcomes'))
const PaperTradeIntelligence = lazy(() => import('./PaperTradeIntelligence'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PaperReview() {
  return (
    <TabPage
      title="Paper Trade Review"
      tabs={[
        { id: 'outcomes', label: 'Outcomes', component: <Suspense fallback={<Loading />}><PaperOutcomes /></Suspense> },
        { id: 'intelligence', label: 'TCA & Intelligence', component: <Suspense fallback={<Loading />}><PaperTradeIntelligence /></Suspense> },
      ]}
    />
  )
}
