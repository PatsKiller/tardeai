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
      { to: '/watch?tab=watchlist', label: 'Watch' },
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
    <nav className="nav-rail" style={{ width: 140, flexShrink: 0, minHeight: 0, alignSelf: 'stretch', padding: '8px 0', display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', background: 'var(--bg0)', overflowY: 'auto', overflowX: 'hidden' }}>
      {SECTIONS.map(section => (
        <div key={section.label} style={{ marginBottom: 4 }}>
          <div style={{ padding: '6px 16px 4px', fontSize: 9, fontWeight: 800, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--text3)' }}>{section.label}</div>
          {section.hubs.map(hub => {
            if (hub.hardNav) {
              const active = typeof window !== 'undefined' && window.location.pathname.startsWith(`/v3${hub.to}`)
              return <a key={hub.to} href={`/v3${hub.to}?_cc=${Date.now()}`} style={linkStyle(active)}>{hub.label}</a>
            }
            return <NavLink key={hub.to} to={hub.to} end={hub.exact} style={({ isActive }) => linkStyle(isActive)}>{hub.label}</NavLink>
          })}
        </div>
      ))}
    </nav>
  )
}
