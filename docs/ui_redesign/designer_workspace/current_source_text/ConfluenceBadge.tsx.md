# Source Export: ConfluenceBadge.tsx

- **Original path:** apps/command-center-v2/src/components/ConfluenceBadge.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 2d7cbd77aea1fd563c4b305f1013ec2c2808e0a6d382bbf741a46eb93c876e9e
- **File size:** 1835 bytes
- **Exists:** YES

```tsx
/**
 * ConfluenceBadge.tsx
 * Displays confluence tier chip and individual strategy badges.
 * Used on Watchlist, TradeAI, and WatchlistSymbolPanel pages.
 */
import React from 'react'

const TIER_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  STRONG:   { bg: '#064E3B', text: '#6EE7B7', border: '#10B981' },
  MODERATE: { bg: '#451A03', text: '#FCD34D', border: '#F59E0B' },
  WEAK:     { bg: '#1E293B', text: '#94A3B8', border: '#475569' },
  NONE:     { bg: '#1E293B', text: '#64748B', border: '#334155' },
}

interface ConfluenceBadgeProps {
  tier: string
  bullishCount: number
  badges: string[]
  compact?: boolean
}

export const ConfluenceBadge: React.FC<ConfluenceBadgeProps> = ({
  tier, bullishCount, badges, compact = false
}) => {
  const colors = TIER_COLORS[tier] || TIER_COLORS.NONE

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
      <span style={{
        backgroundColor: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.border}`,
        borderRadius: '4px',
        padding: '2px 6px',
        fontSize: '11px',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}>
        {tier} {bullishCount > 0 ? `(${bullishCount})` : ''}
      </span>
      {!compact && badges.slice(0, 6).map(badge => (
        <span key={badge} style={{
          backgroundColor: '#1E293B',
          color: '#CBD5E1',
          border: '1px solid #334155',
          borderRadius: '3px',
          padding: '1px 5px',
          fontSize: '10px',
          fontWeight: 500,
        }}>
          {badge}
        </span>
      ))}
      {!compact && badges.length > 6 && (
        <span style={{ color: '#64748B', fontSize: '10px' }}>+{badges.length - 6}</span>
      )}
    </div>
  )
}

export default ConfluenceBadge
```
