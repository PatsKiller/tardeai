import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const Journal = lazy(() => import('./Journal'))
const JournalAnalytics = lazy(() => import('./JournalAnalytics'))
const JournalReports = lazy(() => import('./JournalReports'))
const PaperJournal = lazy(() => import('./PaperJournal'))
const AutomatedTradeJournal = lazy(() => import('./AutomatedTradeJournal'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function JournalHub() {
  return (
    <TabPage
      title="Trade Journal"
      tabs={[
        { id: 'entries', label: 'Entries', component: <Suspense fallback={<Loading />}><Journal /></Suspense> },
        { id: 'analytics', label: 'Analytics', component: <Suspense fallback={<Loading />}><JournalAnalytics /></Suspense> },
        { id: 'reports', label: 'Reports', component: <Suspense fallback={<Loading />}><JournalReports /></Suspense> },
        { id: 'paper', label: 'Paper Journal', component: <Suspense fallback={<Loading />}><PaperJournal /></Suspense> },
        { id: 'automated', label: 'Automated Journal', component: <Suspense fallback={<Loading />}><AutomatedTradeJournal /></Suspense> },
      ]}
    />
  )
}
