import { useNavigate } from 'react-router-dom'
import { dashboardCard } from './dashboardKit'

export type BriefSeverity = 'critical' | 'warning' | 'info' | 'positive'

export interface BriefAction {
  label: string
  url?: string
  onClick?: () => void
  primary?: boolean
}

export interface ActionBriefProps {
  what: string
  why: string
  who: string
  when: string
  how: string
  severity: BriefSeverity
  symbol?: string
  primaryAction: BriefAction
  secondaryActions?: BriefAction[]
  footer?: React.ReactNode
  onDrill?: () => void
}

const SEV_STYLE: Record<BriefSeverity, { label: string; color: string; bg: string }> = {
  critical: { label: 'CRITICAL', color: 'var(--red)', bg: 'rgba(239,68,68,.12)' },
  warning: { label: 'WARNING', color: 'var(--amber)', bg: 'rgba(245,158,11,.12)' },
  positive: { label: 'POSITIVE', color: 'var(--green)', bg: 'rgba(34,197,94,.12)' },
  info: { label: 'INFO', color: 'var(--blue)', bg: 'rgba(96,165,250,.12)' },
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '52px 1fr', gap: 10, alignItems: 'start', padding: '4px 0' }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em' }}>{k}</div>
      <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.45 }}>{v}</div>
    </div>
  )
}

export default function ActionBriefCard({
  what, why, who, when, how, severity, symbol, primaryAction, secondaryActions = [], footer, onDrill,
}: ActionBriefProps) {
  const navigate = useNavigate()
  const sv = SEV_STYLE[severity] ?? SEV_STYLE.info

  const runAction = (a: BriefAction, e: React.MouseEvent) => {
    e.stopPropagation()
    if (a.onClick) { a.onClick(); return }
    if (!a.url) return
    const route = a.url.startsWith('/v3/') ? a.url.slice(3) : a.url.startsWith('/v3') ? a.url.slice(3) || '/' : null
    if (route) navigate(route)
    else window.open(a.url, '_blank', 'noreferrer')
  }

  const primaryBtn: React.CSSProperties = {
    fontSize: 11, fontWeight: 800, padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
    border: `1px solid ${sv.color}`, background: sv.bg, color: sv.color,
  }
  const secondaryBtn: React.CSSProperties = {
    fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 7, cursor: 'pointer',
    border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
  }

  return (
    <div
      onClick={onDrill}
      style={{
        ...dashboardCard,
        borderLeft: `4px solid ${sv.color}`,
        padding: '14px 16px',
        cursor: onDrill ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, fontWeight: 900, padding: '2px 8px', borderRadius: 5, color: sv.color, background: sv.bg }}>{sv.label}</span>
          {symbol && <span style={{ fontSize: 13, fontWeight: 900, color: 'var(--blue)', fontFamily: 'var(--mono)' }}>{symbol}</span>}
        </div>
        <div style={{ textAlign: 'right', fontSize: 10, color: 'var(--text3)', whiteSpace: 'nowrap' }}>
          <div>{who}</div>
          <div>{when}</div>
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', padding: '8px 0', marginBottom: 10 }}>
        <Row k="What" v={what} />
        <Row k="Why" v={why} />
        <Row k="How" v={how} />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }} onClick={e => e.stopPropagation()}>
        <button type="button" style={primaryBtn} onClick={e => runAction(primaryAction, e)}>{primaryAction.label} →</button>
        {secondaryActions.map((a, i) => (
          <button key={i} type="button" style={secondaryBtn} onClick={e => runAction(a, e)}>{a.label}{a.url ? ' →' : ''}</button>
        ))}
      </div>

      {footer && <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border)' }} onClick={e => e.stopPropagation()}>{footer}</div>}
    </div>
  )
}
