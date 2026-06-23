import type React from 'react'

/** Compact explainer: Path A paper auto test vs Path B live Schwab/Fidelity FA manual */

export default function ExecutionPathsStrip({ variant = 'full' }: { variant?: 'full' | 'paper' | 'live' }) {
  const box: React.CSSProperties = {
    padding: '10px 14px', marginBottom: 10, borderRadius: 8, fontSize: 10, lineHeight: 1.55,
    background: 'rgba(15,23,42,.45)', border: '1px solid var(--border)', color: 'var(--text2)',
  }
  const pathA = (
    <div>
      <span style={{ fontWeight: 800, color: '#A855F7' }}>Path A — Paper auto (testing)</span>
      {' '}Approve on this tab → Alpaca paper bracket. No real money, no 2FA. Builds P0 readiness stats.
    </div>
  )
  const pathB = (
    <div style={{ marginTop: variant === 'full' ? 6 : 0 }}>
      <span style={{ fontWeight: 800, color: '#60A5FA' }}>Path B — Live real money</span>
      {' '}Promote to Broker → <b>Broker Proposals</b>.
      {' '}<span style={{ color: '#60A5FA' }}>Schwab:</span> API auto (per-order 2FA) or manual.
      {' '}<span style={{ color: '#22C55E' }}>Fidelity:</span> manual only in <b>Active Trader Pro (FA)</b> — log via Executed manually.
    </div>
  )
  return (
    <div style={box}>
      {variant !== 'live' && pathA}
      {variant !== 'paper' && pathB}
      <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
        Same proposal queue until you pick a path. Doc: docs/PROPOSAL_EXECUTION_PATHS.md
      </div>
    </div>
  )
}