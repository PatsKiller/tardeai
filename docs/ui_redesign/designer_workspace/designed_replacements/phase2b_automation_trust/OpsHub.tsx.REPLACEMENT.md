# OpsHub.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/OpsHub.tsx`
- **Original SHA256**: `662fa85e8ad4a39b557eb2df591d3ab08df1a600a5f83b28f4cb67d637b776ad`

## Changes

- Title: "Operations" -> "Automation Trust Center"
- Tab labels renamed for clarity:
  - "System Hub" -> "Trust Overview"
  - "Ops Console" -> "Cron & Jobs"
  - "LLM Queue" -> "LLM Queue" (unchanged)
  - "Orchestration" -> "Orchestration" (unchanged)
- Added subtitle support: TabPage currently does not accept a `subtitle` prop, so the subtitle is rendered as a secondary `<p>` element below the TabPage title area. **Prerequisite**: Either extend `TabPage` to accept `subtitle`, or wrap in a fragment with a manual subtitle div above. The code below uses the fragment approach to avoid modifying TabPage.

## What did NOT change

- Same 4 lazy-loaded child tabs (SystemHub, Ops, LLMQueue, Orchestration)
- Same import paths for all child components
- Same Loading fallback component
- No new dependencies

## Full Replacement

```tsx
import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const SystemHub = lazy(() => import('./SystemHub'))
const Ops = lazy(() => import('./Ops'))
const Orchestration = lazy(() => import('./Orchestration'))
const LLMQueue = lazy(() => import('./LLMQueue'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function OpsHub() {
  return (
    <>
      <p style={{ fontSize: 10, color: 'var(--text2)', margin: '0 0 -8px 0', letterSpacing: '.1px' }}>
        Automation health, stale data, cron confidence, and queue status
      </p>
      <TabPage
        title="Automation Trust Center"
        tabs={[
          { id: 'hub', label: 'Trust Overview', component: <Suspense fallback={<Loading />}><SystemHub /></Suspense> },
          { id: 'ops', label: 'Cron & Jobs', component: <Suspense fallback={<Loading />}><Ops /></Suspense> },
          { id: 'queue', label: 'LLM Queue', component: <Suspense fallback={<Loading />}><LLMQueue /></Suspense> },
          { id: 'orchestration', label: 'Orchestration', component: <Suspense fallback={<Loading />}><Orchestration /></Suspense> },
        ]}
      />
    </>
  )
}
```
