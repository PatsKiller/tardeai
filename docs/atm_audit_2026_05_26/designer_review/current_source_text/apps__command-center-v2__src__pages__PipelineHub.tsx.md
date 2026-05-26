# Source Export: apps/command-center-v2/src/pages/PipelineHub.tsx

| Field | Value |
|-------|-------|
| **Original Path** | `apps/command-center-v2/src/pages/PipelineHub.tsx` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:49:17Z` |
| **SHA256** | `e2f45a7c2e31c1c58e4ee31de71ce9caa943e871d0828cc365469bcc788cb5b6` |
| **File Size** | 909 bytes |

## Full Source

```tsx
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
```
