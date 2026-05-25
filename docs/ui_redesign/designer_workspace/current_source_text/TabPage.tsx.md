# Source Export: TabPage.tsx

- **Original path:** apps/command-center-v2/src/components/TabPage.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 949671b70575c46c4745cd31d206c1a8da1ad4ebb0a28dcccdf03bc9bad6f2cf
- **File size:** 1630 bytes
- **Exists:** YES

```tsx
import { useState } from 'react'

interface Tab {
  id: string
  label: string
  component: React.ReactNode
}

interface TabPageProps {
  title: string
  tabs: Tab[]
  defaultTab?: string
}

export default function TabPage({ title, tabs, defaultTab }: TabPageProps) {
  const [active, setActive] = useState(defaultTab || tabs[0]?.id || '')

  return (
    <div>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        borderBottom: '1px solid var(--border1, #2a2a3a)',
        marginBottom: 16,
        paddingBottom: 0,
      }}>
        <h2 style={{
          fontSize: 16,
          fontWeight: 700,
          color: 'var(--text0, #e0e0e0)',
          margin: 0,
          marginRight: 24,
          paddingBottom: 10,
        }}>
          {title}
        </h2>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActive(tab.id)}
            style={{
              padding: '8px 16px',
              fontSize: 12,
              fontWeight: active === tab.id ? 600 : 400,
              color: active === tab.id ? 'var(--accent, #4a90f4)' : 'var(--text2, #888)',
              background: 'none',
              border: 'none',
              borderBottom: active === tab.id ? '2px solid var(--accent, #4a90f4)' : '2px solid transparent',
              cursor: 'pointer',
              marginBottom: -1,
              transition: 'all 0.15s ease',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div>
        {tabs.find(t => t.id === active)?.component}
      </div>
    </div>
  )
}
```
