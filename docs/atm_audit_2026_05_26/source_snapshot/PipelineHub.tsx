import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PipelineHealthMaster = lazy(() => import('./PipelineHealthMaster'))
const PipelineController = lazy(() => import('./PipelineController'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PipelineHub() {
  return (
    <>
      <p style={{ fontSize: 10, color: 'var(--text2)', margin: '0 0 -8px 0', letterSpacing: '.1px' }}>
        Stage health, run history, and freshness
      </p>
      <TabPage
        title="Pipeline Health"
        tabs={[
          { id: 'health', label: 'Stage Health', component: <Suspense fallback={<Loading />}><PipelineHealthMaster /></Suspense> },
          { id: 'controller', label: 'Stage Controller', component: <Suspense fallback={<Loading />}><PipelineController /></Suspense> },
        ]}
      />
    </>
  )
}
