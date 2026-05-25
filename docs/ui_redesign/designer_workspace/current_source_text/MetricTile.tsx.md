# Source Export: MetricTile.tsx

- **Original path:** apps/command-center-v2/src/components/MetricTile.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 8964f3e523d2b0c8d6ae05440be86a8ad98f33cd90fc0dfc91cc6510c93ff098
- **File size:** 2639 bytes
- **Exists:** YES

```tsx
import { useState } from 'react'

interface MetricTileProps {
  label: string
  value: string
  delta?: string
  deltaColor?: string
  onClick?: () => void
  tooltip?: string
  icon?: string
  trend?: 'up' | 'down' | 'flat'
}

export default function MetricTile({ label, value, delta, deltaColor, onClick, tooltip, icon, trend }: MetricTileProps) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative',
        background: hovered ? 'rgba(20,26,38,0.95)' : 'rgba(16,20,28,0.92)',
        backdropFilter: 'blur(12px)',
        border: `1px solid ${hovered && onClick ? 'var(--accent)' : 'rgba(255,255,255,0.07)'}`,
        borderRadius: 12,
        padding: '12px 14px',
        minWidth: 100,
        boxShadow: hovered ? '0 4px 16px rgba(0,0,0,.3)' : '0 2px 8px rgba(0,0,0,.2)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all 150ms ease',
        transform: hovered && onClick ? 'translateY(-1px)' : 'none',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <div style={{ fontSize: 9, color: 'var(--text2)', fontFamily: 'var(--sans)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600 }}>
          {icon && <span style={{ marginRight: 4 }}>{icon}</span>}
          {label}
        </div>
        {trend && (
          <span style={{ fontSize: 10, color: trend === 'up' ? 'var(--green)' : trend === 'down' ? 'var(--red)' : 'var(--text3)' }}>
            {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'}
          </span>
        )}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color: deltaColor || 'var(--text0)', lineHeight: 1.15 }}>{value}</div>
      {delta && (
        <div style={{ fontSize: 10, color: deltaColor || 'var(--text2)', marginTop: 2 }}>{delta}</div>
      )}
      {/* Tooltip */}
      {tooltip && hovered && (
        <div style={{
          position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
          marginBottom: 8, padding: '6px 10px', borderRadius: 6,
          background: 'rgba(10, 14, 20, 0.97)', border: '1px solid rgba(74,144,244,0.2)',
          boxShadow: '0 4px 16px rgba(0,0,0,.5)',
          fontSize: 9, color: 'var(--text1)', whiteSpace: 'nowrap', fontFamily: 'var(--sans)',
          animation: 'tooltipFadeIn 150ms ease-out', zIndex: 50, pointerEvents: 'none',
        }}>
          {tooltip}
        </div>
      )}
    </div>
  )
}
```
