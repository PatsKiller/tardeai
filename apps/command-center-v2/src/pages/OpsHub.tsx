import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const SystemHub = lazy(() => import('./SystemHub'))
const Ops = lazy(() => import('./Ops'))
const Orchestration = lazy(() => import('./Orchestration'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function OpsHub() {
  return (
    <TabPage
      title="Operations"
      tabs={[
        { id: 'hub', label: 'System Hub', component: <Suspense fallback={<Loading />}><SystemHub /></Suspense> },
        { id: 'ops', label: 'Ops Console', component: <Suspense fallback={<Loading />}><Ops /></Suspense> },
        { id: 'orchestration', label: 'Orchestration', component: <Suspense fallback={<Loading />}><Orchestration /></Suspense> },
      ]}
    />
  )
}
