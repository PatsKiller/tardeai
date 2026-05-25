# Source Export: AccountBadge.tsx

- **Original path:** apps/command-center-v2/src/components/AccountBadge.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 34c5d8debcee7c249ea05ef1703febfdda3012f878d3ee4f8073539ff35d031c
- **File size:** 1083 bytes
- **Exists:** YES

```tsx
const STYLES: Record<string, { bg: string; label: string }> = {
  fidelity_401k:       { bg: '#7e22ce', label: '401k' },
  schwab_rollover_ira: { bg: '#1e40af', label: 'Roll IRA' },
  schwab_roth:         { bg: '#15803d', label: 'Roth' },
  schwab_taxable:      { bg: '#c2410c', label: 'Taxable' },
  rollover_ira:        { bg: '#1e40af', label: 'Roll IRA' },
  roth:                { bg: '#15803d', label: 'Roth' },
  taxable:             { bg: '#c2410c', label: 'Taxable' },
  '401k':              { bg: '#7e22ce', label: '401k' },
}

export default function AccountBadge({ account }: { account?: string | null }) {
  if (!account) return null
  const key = account.toLowerCase()
  const s = STYLES[key] || Object.entries(STYLES).find(([k]) => key.includes(k))?.[1] || { bg: '#6b7280', label: account.replace('schwab_', '').replace('fidelity_', '') }
  return (
    <span style={{
      background: s.bg, color: '#fff', borderRadius: 4, padding: '1px 6px',
      fontSize: 9, fontWeight: 700, whiteSpace: 'nowrap', letterSpacing: '.02em',
    }}>
      {s.label}
    </span>
  )
}
```
