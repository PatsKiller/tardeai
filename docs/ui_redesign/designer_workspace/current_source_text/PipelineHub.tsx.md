# Source Export: PipelineHub.tsx

- **Original path:** apps/command-center-v2/src/pages/PipelineHub.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 58a46df8622af09ccd98ff1e794704c13cf38a2dc5b51cc78078268cd6bdba55
- **File size:** 724 bytes
- **Exists:** YES

```tsx
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
```
