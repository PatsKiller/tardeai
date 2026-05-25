# Source Export: Card.tsx

- **Original path:** apps/command-center-v2/src/components/Card.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 8c2257098e8288cd00022c2865ecd972be8d2ae3fcb2105d9a574a7404bdc289
- **File size:** 1899 bytes
- **Exists:** YES

```tsx
import { useState, type ReactNode, type CSSProperties } from 'react'

interface CardProps {
  title?: string
  subtitle?: string
  children: ReactNode
  className?: string
  compact?: boolean
  accentColor?: string
  hoverable?: boolean
  onClick?: () => void
  style?: CSSProperties
}

export default function Card({ title, subtitle, children, className, compact, accentColor, hoverable = false, onClick, style: extraStyle }: CardProps) {
  const [hovered, setHovered] = useState(false)
  const interactive = hoverable || !!onClick

  return (
    <div
      className={className}
      onClick={onClick}
      onMouseEnter={interactive ? () => setHovered(true) : undefined}
      onMouseLeave={interactive ? () => setHovered(false) : undefined}
      style={{
        background: hovered ? 'rgba(20,26,38,0.95)' : 'rgba(16,20,28,0.92)',
        backdropFilter: 'blur(12px)',
        border: `1px solid ${hovered && interactive ? 'rgba(74,144,244,0.2)' : 'rgba(255,255,255,0.07)'}`,
        borderRadius: 12,
        borderLeft: accentColor ? `3px solid ${accentColor}` : undefined,
        padding: compact ? '10px 12px' : '14px 16px',
        boxShadow: hovered ? '0 4px 20px rgba(0,0,0,.3)' : '0 2px 8px rgba(0,0,0,.2)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all 150ms ease',
        transform: hovered && onClick ? 'translateY(-1px)' : 'none',
        ...extraStyle,
      }}
    >
      {(title || subtitle) && (
        <div style={{ marginBottom: compact ? 8 : 10, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          {title && <h3 style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700, color: 'var(--text1)', margin: 0, letterSpacing: '.2px' }}>{title}</h3>}
          {subtitle && <span style={{ fontSize: 9, color: 'var(--text3)' }}>{subtitle}</span>}
        </div>
      )}
      {children}
    </div>
  )
}
```
