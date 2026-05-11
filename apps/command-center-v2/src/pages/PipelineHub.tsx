import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PipelineHealthMaster = lazy(() => import('./PipelineHealthMaster'))
const PipelineController = lazy(() => import('./PipelineController'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PipelineHub() {
  return (
    <TabPage
      title="Pipeline Operations"
      tabs={[
        { id: 'health', label: 'Health Overview', component: <Suspense fallback={<Loading />}><PipelineHealthMaster /></Suspense> },
        { id: 'controller', label: 'Stage Controller', component: <Suspense fallback={<Loading />}><PipelineController /></Suspense> },
      ]}
    />
  )
}
