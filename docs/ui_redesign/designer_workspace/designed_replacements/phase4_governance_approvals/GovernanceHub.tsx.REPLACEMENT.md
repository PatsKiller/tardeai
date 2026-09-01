# GovernanceHub.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/GovernanceHub.tsx`

## Changes

- Title: "Governance" -> "Governance Center"
- Added subtitle below title via fragment wrapper
- Tab labels renamed for clarity:
  - "Paper Validation" -> "Paper Validation"  (unchanged -- already clear)
  - "Learning Governance" -> "Learning & Experiments"
  - "Approvals" -> "Approvals & Tasks"

## What did NOT change

- Same 3 lazy-loaded child tabs (PaperGovernance, LearningGovernance, Approvals)
- Same import paths for all child components
- Same Loading fallback component
- Same URL tab parameter parsing (tab=paper, tab=learning, tab=approvals)
- No new dependencies

## Full Replacement

```tsx
import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import TabPage from '../components/TabPage'

const PaperGovernance = lazy(() => import('./PaperGovernance'))
const LearningGovernance = lazy(() => import('./LearningGovernance'))
const Approvals = lazy(() => import('./Approvals'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function GovernanceHub() {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tabMap: Record<string, string> = { 'paper': 'paper', 'learning': 'learning', 'approvals': 'approvals' }
  const defaultTab = tabParam ? tabMap[tabParam] || undefined : undefined

  return (
    <>
      <div style={{ padding: '0 0 0 0' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4, marginTop: -4 }}>
          Policy rules, approval gates, validation controls, and audit readiness
        </div>
      </div>
      <TabPage
        title="Governance Center"
        defaultTab={defaultTab}
        tabs={[
          { id: 'paper', label: 'Paper Validation', component: <Suspense fallback={<Loading />}><PaperGovernance /></Suspense> },
          { id: 'learning', label: 'Learning & Experiments', component: <Suspense fallback={<Loading />}><LearningGovernance /></Suspense> },
          { id: 'approvals', label: 'Approvals & Tasks', component: <Suspense fallback={<Loading />}><Approvals /></Suspense> },
        ]}
      />
    </>
  )
}
```
