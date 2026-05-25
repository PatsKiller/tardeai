# Source Export: GovernanceHub.tsx

- **Original path:** apps/command-center-v2/src/pages/GovernanceHub.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** ea8aa48c665e618d4d348a891ecc5d065220f98fbc966b36a59f5c2055406f8b
- **File size:** 1228 bytes
- **Exists:** YES

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
    <TabPage
      title="Governance"
      defaultTab={defaultTab}
      tabs={[
        { id: 'paper', label: 'Paper Validation', component: <Suspense fallback={<Loading />}><PaperGovernance /></Suspense> },
        { id: 'learning', label: 'Learning Governance', component: <Suspense fallback={<Loading />}><LearningGovernance /></Suspense> },
        { id: 'approvals', label: 'Approvals', component: <Suspense fallback={<Loading />}><Approvals /></Suspense> },
      ]}
    />
  )
}
```
