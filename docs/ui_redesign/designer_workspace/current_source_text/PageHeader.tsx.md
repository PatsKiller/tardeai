# Source Export: PageHeader.tsx

- **Original path:** apps/command-center-v2/src/components/PageHeader.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 4a2b6e8d6bc08c6b82555b5ac2471966fc5dd390117450e1c9d785dd58ed6393
- **File size:** 847 bytes
- **Exists:** YES

```tsx
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  actions?: ReactNode
}

export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      marginBottom: 16,
      paddingBottom: 12,
      borderBottom: '1px solid var(--border)',
    }}>
      <div>
        <h1 style={{ fontFamily: 'var(--sans)', fontSize: 16, fontWeight: 800, color: '#fff', margin: 0, letterSpacing: '-.3px' }}>{title}</h1>
        {subtitle && <p style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2, letterSpacing: '.1px' }}>{subtitle}</p>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>{actions}</div>}
    </div>
  )
}
```
