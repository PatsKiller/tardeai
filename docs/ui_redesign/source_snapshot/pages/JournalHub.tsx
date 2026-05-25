import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import TabPage from '../components/TabPage'

const Journal = lazy(() => import('./Journal'))
const JournalAnalytics = lazy(() => import('./JournalAnalytics'))
const JournalReports = lazy(() => import('./JournalReports'))
const AutomatedTradeJournal = lazy(() => import('./AutomatedTradeJournal'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function JournalHub() {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tabMap: Record<string, string> = { 'automated-journal': 'automated', 'analytics': 'analytics', 'reports': 'reports', 'entries': 'entries', 'automated': 'automated' }
  const defaultTab = tabParam ? tabMap[tabParam] || undefined : undefined

  return (
    <TabPage
      title="Trade Journal"
      defaultTab={defaultTab}
      tabs={[
        { id: 'entries', label: 'Entries', component: <Suspense fallback={<Loading />}><Journal /></Suspense> },
        { id: 'analytics', label: 'Analytics', component: <Suspense fallback={<Loading />}><JournalAnalytics /></Suspense> },
        { id: 'reports', label: 'Reports', component: <Suspense fallback={<Loading />}><JournalReports /></Suspense> },
        { id: 'automated', label: 'Automated Journal', component: <Suspense fallback={<Loading />}><AutomatedTradeJournal /></Suspense> },
      ]}
    />
  )
}
