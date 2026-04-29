import type { ReactNode } from 'react'

interface DetailDrawerProps {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: ReactNode
}

export default function DetailDrawer({ open, onClose, title, subtitle, children }: DetailDrawerProps) {
  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }} onClick={onClose}>
      <div style={{
        width: 400, maxWidth: '90vw', height: '100vh', background: 'var(--bg1)', borderLeft: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', boxShadow: '-4px 0 20px rgba(0,0,0,.5)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexShrink: 0 }}>
          <div>
            <div style={{ fontFamily: 'var(--sans)', fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{title}</div>
            {subtitle && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{subtitle}</div>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 18, fontFamily: 'var(--mono)', padding: '0 4px' }}>{'\u00d7'}</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
          {children}
        </div>
      </div>
    </div>
  )
}

export function DrawerStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: color || 'var(--text0)' }}>{value}</div>
    </div>
  )
}

export function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6, paddingBottom: 4, borderBottom: '1px solid var(--border-subtle)' }}>{title}</div>
      {children}
    </div>
  )
}
