import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PaperOutcomes = lazy(() => import('./PaperOutcomes'))
const PaperTradeIntelligence = lazy(() => import('./PaperTradeIntelligence'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PaperReview() {
  return (
    <>
      <div style={{ padding: '0 0 0 0' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4, marginTop: -4 }}>
          Outcome review, TCA analysis, and strategy learning from closed paper trades
        </div>
      </div>
      <TabPage
        title="Paper Review & Learning"
        tabs={[
          { id: 'outcomes', label: 'Outcomes', component: <Suspense fallback={<Loading />}><PaperOutcomes /></Suspense> },
          { id: 'intelligence', label: 'TCA & Intelligence', component: <Suspense fallback={<Loading />}><PaperTradeIntelligence /></Suspense> },
        ]}
      />
    </>
  )
}
