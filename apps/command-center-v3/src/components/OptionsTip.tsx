import type { CSSProperties, ReactNode } from 'react'

const helpCursor: CSSProperties = { cursor: 'help' }

/** Wrap any element with a native title tooltip */
export function Tip({ tip, children, style, as: Tag = 'span' }: {
  tip: string
  children: ReactNode
  style?: CSSProperties
  as?: 'span' | 'div' | 'label'
}) {
  const El = Tag
  return <El title={tip} style={{ ...helpCursor, ...style }}>{children}</El>
}

/** Label with dotted underline hint */
export function TipLabel({ tip, children, style }: { tip: string; children: ReactNode; style?: CSSProperties }) {
  return (
    <label title={tip} style={{ fontSize: 10, color: 'var(--text3)', cursor: 'help', ...style }}>
      {children}
    </label>
  )
}

/** Filter / facet chip with tooltip */
export function TipChip({
  tip,
  label,
  active,
  onClick,
  color = '#60a5fa',
  disabled,
}: {
  tip: string
  label: string
  active: boolean
  onClick: () => void
  color?: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      title={tip}
      disabled={disabled}
      onClick={onClick}
      style={{
        padding: '4px 10px',
        fontSize: 10,
        borderRadius: 5,
        cursor: disabled ? 'default' : 'help',
        border: `1px solid ${active ? color : 'var(--border)'}`,
        background: active ? `${color}22` : 'var(--bg2)',
        color: active ? color : 'var(--text3)',
        fontWeight: active ? 700 : 500,
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  )
}

/** KPI tile on Strategy Overview */
export function TipKpi({ tip, label, value, color }: { tip: string; label: string; value: ReactNode; color: string }) {
  return (
    <div title={tip} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, textAlign: 'center', cursor: 'help' }}>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>{label} ⓘ</div>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

/** Section header with tooltip */
export function TipSection({ tip, children }: { tip?: string; children: ReactNode }) {
  return (
    <div title={tip} style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 6, fontWeight: 700, letterSpacing: '.06em', cursor: tip ? 'help' : undefined }}>
      {children}{tip ? ' ⓘ' : ''}
    </div>
  )
}