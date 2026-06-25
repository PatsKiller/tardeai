import { NavLink } from 'react-router-dom'

const HUBS = [
  { to: '/', label: 'Home', exact: true },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/risk', label: 'Risk' },
  { to: '/trading', label: 'Trading' },
  { to: '/strategy', label: 'Strategy' },
  { to: '/agents', label: 'Agents' },
  { to: '/intelligence', label: 'Intelligence' },
  { to: '/hermes', label: 'Hermes' },
  { to: '/retirement', label: 'Retirement' },
  { to: '/journal', label: 'Journal' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/watchpool', label: 'Watchpool' },
  { to: '/sectors', label: 'Sectors' },
  { to: '/reports', label: 'Reports', hardNav: true },
  { to: '/rotation', label: 'Rotation' },
  { to: '/rec-intel', label: 'Rec Intelligence' },
  { to: '/advisor-changes', label: 'Advisor Changes' },
  { to: '/health', label: 'Health' },
  { to: '/system', label: 'System' },
]

export default function NavRail() {
  return (
    <nav className="nav-rail" style={{
      width: 140, flexShrink: 0, padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 2,
      borderRight: '1px solid var(--border)', background: 'var(--bg0)',
    }}>
      {HUBS.map(h => {
        const linkStyle = (active: boolean) => ({
          display: 'block', padding: '8px 16px', fontSize: 13, fontWeight: active ? 700 : 400,
          color: active ? '#60a5fa' : 'var(--text2)', textDecoration: 'none',
          background: active ? 'rgba(96,165,250,.06)' : 'transparent',
          borderLeft: active ? '3px solid #60a5fa' : '3px solid transparent',
        })
        if ((h as { hardNav?: boolean }).hardNav) {
          const active = typeof window !== 'undefined' && window.location.pathname.startsWith(`/v3${h.to}`)
          return (
            <a
              key={h.to}
              href={`/v3${h.to}?_cc=${Date.now()}`}
              style={linkStyle(active)}
            >
              {h.label}
            </a>
          )
        }
        return (
          <NavLink key={h.to} to={h.to} end={h.exact}
            style={({ isActive }) => linkStyle(isActive)}
          >
            {h.label}
          </NavLink>
        )
      })}
    </nav>
  )
}
