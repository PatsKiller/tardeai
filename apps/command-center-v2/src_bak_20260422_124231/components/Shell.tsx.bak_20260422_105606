import { NavLink, Outlet } from 'react-router-dom'
import styles from './Shell.module.css'

// Primary analyst-facing navigation only.
// Admin utilities (Alerts, Log, Queue, Ops) are accessible via /v2/ops and /v2/alerts but NOT in primary nav.
const NAV_ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/trade-ai', label: 'Trade AI' },
  { to: '/portfolio', label: 'Holdings' },
  { to: '/journal', label: 'Journal' },
  { to: '/risk', label: 'Risk' },
  { to: '/dividends', label: 'Dividends' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/rebalance', label: 'Rebalance' },
  { to: '/correlation', label: 'Correlation' },
  { to: '/retirement', label: 'Retirement' },
  { to: '/forecast', label: 'Forecast' },
  { to: '/research', label: 'Research' },
  { to: '/reports', label: 'Reports' },
]

export default function Shell() {
  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.brand}>CC</div>
        <nav className={styles.nav}>
          {NAV_ITEMS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.active : ''}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.meta}>
          <span className={styles.dot} />
          <span>LIVE</span>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
