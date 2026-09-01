# PaperReview.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/PaperReview.tsx`

## Changes

- Title: "Paper Trade Review" -> "Paper Review & Learning"
- Added subtitle via fragment wrapper
- Tab labels unchanged (already clear)

## What did NOT change

- Same 2 lazy-loaded child tabs (PaperOutcomes, PaperTradeIntelligence)
- Same import paths
- Same Loading fallback
- No new dependencies

## Full Replacement

```tsx
import { lazy, Suspense } from 'react'
import TabPage from '../components/TabPage'

const PaperOutcomes = lazy(() => import('./PaperOutcomes'))
const PaperTradeIntelligence = lazy(() => import('./PaperTradeIntelligence'))

const Loading = () => <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>

export default function PaperReview() {
  return (
    <>
      <div style={{ padding: '0 0 0 0' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4, marginTop: -4 }}>
          Outcome review, TCA analysis, and strategy learning from closed paper trades
        </div>
      </div>
      <TabPage
        title="Paper Review & Learning"
        tabs={[
          { id: 'outcomes', label: 'Outcomes', component: <Suspense fallback={<Loading />}><PaperOutcomes /></Suspense> },
          { id: 'intelligence', label: 'TCA & Intelligence', component: <Suspense fallback={<Loading />}><PaperTradeIntelligence /></Suspense> },
        ]}
      />
    </>
  )
}
```
