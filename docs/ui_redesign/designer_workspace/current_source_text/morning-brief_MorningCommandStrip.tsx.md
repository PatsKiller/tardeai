# Source Export: MorningCommandStrip.tsx

- **Original path:** apps/command-center-v2/src/components/morning-brief/MorningCommandStrip.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** eb8842dc5cae8c8018b2da5101d3ca11e6efcc384f92e891ef49d503477f9f56
- **File size:** 743 bytes
- **Exists:** YES

```tsx
import s from './MorningBrief.module.css'

interface Cell { label: string; val: string; sub?: string; color?: string; onClick?: () => void }

export default function MorningCommandStrip({ cells }: { cells: Cell[] }) {
  return (
    <div className={s.strip}>
      {cells.map(c => (
        <div key={c.label} className={s.stripCell} data-click={c.onClick ? '' : undefined} onClick={c.onClick}>
          <div className={`${s.stripLabel} ${s.sans}`}>{c.label}</div>
          <div className={`${s.stripVal} ${s.sans}`} style={{ color: c.color || 'var(--text0)' }}>{c.val}</div>
          {c.sub && <div className={`${s.stripSub} ${s.sans}`} style={{ color: c.color || 'var(--text3)' }}>{c.sub}</div>}
        </div>
      ))}
    </div>
  )
}
```
