import { NavLink } from 'react-router-dom'

const HUBS = [
  { to: '/v3', label: 'Home', exact: true },
  { to: '/v3/portfolio', label: 'Portfolio' },
  { to: '/v3/risk', label: 'Risk' },
  { to: '/v3/trading', label: 'Trading' },
  { to: '/v3/strategy', label: 'Strategy' },
  { to: '/v3/agents', label: 'Agents' },
  { to: '/v3/intelligence', label: 'Intelligence' },
  { to: '/v3/hermes', label: 'Hermes' },
  { to: '/v3/retirement', label: 'Retirement' },
  { to: '/v3/journal', label: 'Journal' },
  { to: '/v3/system', label: 'System' },
]

export default function NavRail() {
  return (
    <nav style={{
      width: 140, flexShrink: 0, padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 2,
      borderRight: '1px solid var(--border)', background: 'var(--bg0)',
    }}>
      {HUBS.map(h => (
        <NavLink key={h.to} to={h.to} end={h.exact}
          style={({ isActive }) => ({
            display: 'block', padding: '8px 16px', fontSize: 13, fontWeight: isActive ? 700 : 400,
            color: isActive ? '#60a5fa' : 'var(--text2)', textDecoration: 'none',
            background: isActive ? 'rgba(96,165,250,.06)' : 'transparent',
            borderLeft: isActive ? '3px solid #60a5fa' : '3px solid transparent',
          })}
        >
          {h.label}
        </NavLink>
      ))}
    </nav>
  )
}
