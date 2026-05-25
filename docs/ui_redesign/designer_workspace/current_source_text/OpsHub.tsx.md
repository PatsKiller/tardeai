# Source Export: OpsHub.tsx

- **Original path:** apps/command-center-v2/src/pages/OpsHub.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 662fa85e8ad4a39b557eb2df591d3ab08df1a600a5f83b28f4cb67d637b776ad
- **File size:** 967 bytes
- **Exists:** YES

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
    <TabPage
      title="Operations"
      tabs={[
        { id: 'hub', label: 'System Hub', component: <Suspense fallback={<Loading />}><SystemHub /></Suspense> },
        { id: 'ops', label: 'Ops Console', component: <Suspense fallback={<Loading />}><Ops /></Suspense> },
        { id: 'queue', label: 'LLM Queue', component: <Suspense fallback={<Loading />}><LLMQueue /></Suspense> },
        { id: 'orchestration', label: 'Orchestration', component: <Suspense fallback={<Loading />}><Orchestration /></Suspense> },
      ]}
    />
  )
}
```
