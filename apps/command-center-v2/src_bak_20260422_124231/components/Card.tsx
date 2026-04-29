import type { ReactNode } from 'react'

interface CardProps {
  title?: string
  subtitle?: string
  children: ReactNode
  className?: string
  compact?: boolean
}

export default function Card({ title, subtitle, children, className, compact }: CardProps) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: compact ? '8px 10px' : '12px 14px',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {(title || subtitle) && (
        <div style={{ marginBottom: compact ? 6 : 8, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          {title && <h3 style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 600, color: 'var(--text1)', margin: 0, letterSpacing: '.2px' }}>{title}</h3>}
          {subtitle && <span style={{ fontSize: 9, color: 'var(--text3)' }}>{subtitle}</span>}
        </div>
      )}
      {children}
    </div>
  )
}
