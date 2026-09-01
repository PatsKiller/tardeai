# PipelineHub.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/PipelineHub.tsx`
- **Original SHA256**: `58a46df8622af09ccd98ff1e794704c13cf38a2dc5b51cc78078268cd6bdba55`

## Changes

- Title: "Pipeline Operations" -> "Pipeline Health"
- Subtitle added: "Stage health, run history, and freshness"
- Tab labels renamed:
  - "Health Overview" -> "Stage Health"
  - "Stage Controller" -> "Stage Controller" (unchanged)
- Same fragment+subtitle approach as OpsHub to avoid modifying TabPage

## What did NOT change

- Same 2 lazy-loaded child tabs (PipelineHealthMaster, PipelineController)
- Same import paths
- Same Loading fallback
- No new dependencies

## Full Replacement

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
