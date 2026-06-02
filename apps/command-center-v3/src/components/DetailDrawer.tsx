import type { ReactNode } from 'react'

export interface DrillContext {
  title: string
  subtitle?: string
  endpoint: string
  rows: Record<string, any>[]
}

interface Props {
  ctx: DrillContext | null
  onClose: () => void
}

export default function DetailDrawer({ ctx, onClose }: Props) {
  if (!ctx) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }} onClick={onClose}>
      <div style={{
        width: 420, maxWidth: '90vw', height: '100vh', background: 'var(--bg1)',
        borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
        boxShadow: '-4px 0 20px rgba(0,0,0,.5)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{ctx.title}</div>
            {ctx.subtitle && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{ctx.subtitle}</div>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 18, padding: '0 4px' }}>{'\u00d7'}</button>
        </div>
        {/* Provenance badge — read-only */}
        <div style={{ padding: '6px 16px', background: 'rgba(59,130,246,.04)', borderBottom: '1px solid var(--border)', fontSize: 9, color: 'var(--text3)', fontFamily: 'monospace' }}>
          Source: {ctx.endpoint}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
          {ctx.rows.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 11 }}>No data rows</div>}
          {ctx.rows.map((row, i) => (
            <div key={i} style={{ marginBottom: 10, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6, fontSize: 11 }}>
              {Object.entries(row).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{k}</span>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace', fontSize: 10, maxWidth: 240, textAlign: 'right', wordBreak: 'break-word' }}>
                    {typeof v === 'object' ? JSON.stringify(v) : String(v ?? '--')}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
        {/* Read-only footer */}
        <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border)', fontSize: 8, color: 'var(--text3)', textAlign: 'center' }}>
          Read-only drill view. No action controls. Level 7 prohibited.
        </div>
      </div>
    </div>
  )
}

export function DrawerStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: color || 'var(--text0)' }}>{value}</div>
    </div>
  )
}

export function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6, paddingBottom: 4, borderBottom: '1px solid var(--border)' }}>{title}</div>
      {children}
    </div>
  )
}
