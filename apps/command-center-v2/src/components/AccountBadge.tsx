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
