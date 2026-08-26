/** Shadow control-plane hub. Not a live cutover. */

import { NavLink } from 'react-router-dom'

const LINKS = [
  ['/control-plane/system', 'System'],
  ['/control-plane/agents', 'Agent Office'],
  ['/control-plane/workflows', 'Workflow Trace'],
  ['/control-plane/research', 'Research Attention'],
  ['/control-plane/data', 'Data Integrity'],
  ['/control-plane/identity', 'Identity'],
  ['/control-plane/notifications', 'Notifications'],
  ['/control-plane/learning', 'Learning'],
  ['/control-plane/maturity', 'Maturity'],
  ['/control-plane/audit', 'Audit'],
] as const

export default function ControlPlaneHub() {
  return (
    <div data-page="control-plane-hub" data-preview="true" style={{ display: 'grid', gap: 12, maxWidth: 720 }}>
      <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.4 }}>CONTROL PLANE PREVIEW</div>
      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.5 }}>
        Shadow namespace under /control-plane/*. Legacy Command Center routes are unchanged.
        API existence is not LIVE. Feature flag: localStorage CC_CONTROL_PLANE_PREVIEW=1.
      </div>
      <div style={{ display: 'grid', gap: 6 }}>
        {LINKS.map(([to, label]) => (
          <NavLink key={to} to={to} style={{ color: 'var(--text0)', fontFamily: 'var(--mono)', fontSize: 12 }}>
            {label} · {to}
          </NavLink>
        ))}
      </div>
    </div>
  )
}
