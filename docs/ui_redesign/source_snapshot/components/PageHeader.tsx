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
