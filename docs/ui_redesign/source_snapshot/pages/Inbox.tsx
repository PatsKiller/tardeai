import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const AlertsActions = lazy(() => import('./AlertsActions'))
const Notifications = lazy(() => import('./Notifications'))
const ActionCenter = lazy(() => import('./ActionCenter'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function Inbox() {
  return (
    <TabPage
      title="Inbox"
      tabs={[
        { id: 'actions', label: 'Actions & Alerts', component: <Suspense fallback={<Loading />}><AlertsActions /></Suspense> },
        { id: 'notifications', label: 'Notification Log', component: <Suspense fallback={<Loading />}><Notifications /></Suspense> },
        { id: 'tasks', label: 'Task Queue', component: <Suspense fallback={<Loading />}><ActionCenter /></Suspense> },
      ]}
    />
  )
}
