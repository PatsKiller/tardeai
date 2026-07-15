import { useState } from 'react'
import HoldingsDetailPanel, { type HoldingsDetailContext } from './HoldingsDetailPanel'
import { BB } from '../lib/holdingsTerminalTokens'

interface Props {
  open: boolean
  title: string
  subtitle?: string
  ctx: HoldingsDetailContext | null
  onClose: () => void
}

/**
 * Ticker drawer — default 75% viewport width for full tabbed detail.
 * ⛶ expands to true full screen when needed for stop 2FA panels.
 */
export default function HoldingsSideDrawer({ open, title, subtitle, ctx, onClose }: Props) {
  const [fullScreen, setFullScreen] = useState(false)
  if (!open || !ctx) return null

  const width = fullScreen ? '100vw' : 'min(1200px, 75vw)'

  return (
    <div
      data-testid="holdings-side-drawer"
      style={{
        position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', justifyContent: 'flex-end',
        background: 'rgba(2,6,12,.55)',
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label={`${title} ticker details`}
        style={{
          width, height: '100vh', background: BB.bg,
          borderLeft: `1px solid ${BB.border}`, display: 'flex', flexDirection: 'column',
          boxShadow: '-12px 0 40px rgba(0,0,0,.6)', transition: 'width .15s ease',
        }}
      >
        <div style={{
          padding: '14px 18px', borderBottom: `1px solid ${BB.border}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexShrink: 0,
          background: BB.bgRow,
        }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: BB.text0, fontFamily: BB.mono }}>{title}</div>
            {subtitle && <div style={{ fontSize: 11, color: BB.text3, marginTop: 4 }}>{subtitle}</div>}
            <div style={{ fontSize: 9, color: BB.text3, marginTop: 6 }}>
              Overview · P&L · Technicals · Analyst & Targets · News · Earnings · Stops · AI
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button
              type="button"
              onClick={() => setFullScreen(f => !f)}
              aria-label={fullScreen ? 'Exit full screen' : 'Full screen'}
              title={fullScreen ? 'Exit full screen' : 'Expand to full screen'}
              style={{
                background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 6,
                color: BB.text3, cursor: 'pointer', fontSize: 14, padding: '2px 9px',
              }}
            >
              {fullScreen ? '🗗' : '⛶'}
            </button>
            <button
              type="button"
              onClick={onClose}
              data-testid="holdings-drawer-close"
              aria-label="Close"
              style={{ background: 'transparent', border: 'none', color: BB.text3, cursor: 'pointer', fontSize: 22 }}
            >
              ×
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px 28px' }}>
          <HoldingsDetailPanel {...ctx} />
        </div>
      </div>
    </div>
  )
}
