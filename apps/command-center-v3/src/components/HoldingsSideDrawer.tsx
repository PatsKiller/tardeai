import HoldingsDetailPanel, { type HoldingsDetailContext } from './HoldingsDetailPanel'
import { BB } from '../lib/holdingsTerminalTokens'

interface Props {
  open: boolean
  title: string
  subtitle?: string
  ctx: HoldingsDetailContext | null
  onClose: () => void
}

export default function HoldingsSideDrawer({ open, title, subtitle, ctx, onClose }: Props) {
  if (!open || !ctx) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', justifyContent: 'flex-end', background: 'rgba(2,6,12,.55)' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(560px, 94vw)', height: '100vh', background: BB.bg,
        borderLeft: `1px solid ${BB.border}`, display: 'flex', flexDirection: 'column',
        boxShadow: '-12px 0 40px rgba(0,0,0,.6)',
      }}>
        <div style={{ padding: '14px 18px', borderBottom: `1px solid ${BB.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: BB.text0, fontFamily: BB.mono }}>{title}</div>
            {subtitle && <div style={{ fontSize: 10, color: BB.text3, marginTop: 3 }}>{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: BB.text3, cursor: 'pointer', fontSize: 22 }}>×</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          <HoldingsDetailPanel {...ctx} />
        </div>
      </div>
    </div>
  )
}