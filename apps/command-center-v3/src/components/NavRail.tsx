import { NavLink } from 'react-router-dom'

type Hub = { to: string; label: string; exact?: boolean; hardNav?: boolean }

const SECTIONS: { label: string; hubs: Hub[] }[] = [
  {
    label: 'Trade',
    hubs: [
      { to: '/', label: 'Home', exact: true },
      { to: '/portfolio', label: 'Portfolio', exact: true },
      { to: '/portfolio/re-entry', label: '↳ Re-Entry' },
      { to: '/risk', label: 'Risk' },
      { to: '/trading', label: 'Trading' },
      { to: '/strategy', label: 'Strategy' },
      { to: '/journal', label: 'TradeInView' },
      { to: '/watch', label: 'Watch' },
      { to: '/defense', label: 'Defense' },
    ],
  },
  {
    label: 'Intel',
    hubs: [
      { to: '/agents', label: 'Agents' },
      { to: '/research-intelligence', label: 'Research Intel' },
      { to: '/intelligence', label: 'Intelligence' },
      { to: '/hermes', label: 'Hermes' },
      { to: '/reports', label: 'Reports', hardNav: true },
      { to: '/rotation', label: 'Rotation' },
      { to: '/rec-intel', label: 'Rec Intelligence' },
    ],
  },
  {
    label: 'Ops',
    hubs: [
      { to: '/retirement', label: 'Retirement' },
      { to: '/health', label: 'Health' },
      { to: '/consumption', label: 'Consumption' },
      { to: '/system', label: 'System' },
    ],
  },
]

export default function NavRail() {
  const linkStyle = (active: boolean) => ({
    display: 'block', padding: '7px 16px', fontSize: 13, fontWeight: active ? 700 : 400,
    color: active ? '#60a5fa' : 'var(--text2)', textDecoration: 'none',
    background: active ? 'rgba(96,165,250,.06)' : 'transparent',
    borderLeft: active ? '3px solid #60a5fa' : '3px solid transparent',
  })

  return (
    <nav className="nav-rail" style={{
      width: 140, flexShrink: 0, minHeight: 0, alignSelf: 'stretch',
      padding: '8px 0', display: 'flex', flexDirection: 'column',
      borderRight: '1px solid var(--border)', background: 'var(--bg0)',
      overflowY: 'auto', overflowX: 'hidden',
    }}>
      {SECTIONS.map(sec => (
        <div key={sec.label} style={{ marginBottom: 4 }}>
          <div style={{
            padding: '6px 16px 4px', fontSize: 9, fontWeight: 800, letterSpacing: 0.6,
            textTransform: 'uppercase', color: 'var(--text3)',
          }}>{sec.label}</div>
          {sec.hubs.map(h => {
            if (h.hardNav) {
              const active = typeof window !== 'undefined' && window.location.pathname.startsWith(`/v3${h.to}`)
              return (
                <a key={h.to} href={`/v3${h.to}?_cc=${Date.now()}`} style={linkStyle(active)}>{h.label}</a>
              )
            }
            return (
              <NavLink key={h.to} to={h.to} end={h.exact} style={({ isActive }) => linkStyle(isActive)}>
                {h.label}
              </NavLink>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
