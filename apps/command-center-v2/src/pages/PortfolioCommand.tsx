import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const Portfolio = lazy(() => import('./Portfolio'))
const PortfolioMonitor = lazy(() => import('./PortfolioMonitor'))
const PortfolioIntelligence = lazy(() => import('./PortfolioIntelligence'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PortfolioCommand() {
  return (
    <TabPage
      title="Portfolio Command"
      tabs={[
        { id: 'holdings', label: 'Holdings', component: <Suspense fallback={<Loading />}><Portfolio /></Suspense> },
        { id: 'health', label: 'Health & Risk', component: <Suspense fallback={<Loading />}><PortfolioMonitor /></Suspense> },
        { id: 'intelligence', label: 'Intelligence', component: <Suspense fallback={<Loading />}><PortfolioIntelligence /></Suspense> },
      ]}
    />
  )
}
