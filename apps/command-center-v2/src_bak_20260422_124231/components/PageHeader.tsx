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
      marginBottom: 14,
      paddingBottom: 10,
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      <div>
        <h1 style={{ fontFamily: 'var(--sans)', fontSize: 15, fontWeight: 700, color: 'var(--text0)', margin: 0, letterSpacing: '-.2px' }}>{title}</h1>
        {subtitle && <p style={{ fontSize: 10, color: 'var(--text3)', marginTop: 1 }}>{subtitle}</p>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 6 }}>{actions}</div>}
    </div>
  )
}
