import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useState, useRef, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import AdminModals from './AdminModals'
import styles from './Shell.module.css'

type OverviewMini = {
  portfolio_value: number
  today_change: number
  as_of?: string
  last_repriced?: string
  pending_approvals?: number
  trade_ai?: { vix?: number | null; breadth?: string | null; go_count?: number; wait_count?: number; no_go_count?: number; run_label?: string; run_date?: string }
  journal?: { total_pnl: number; win_rate: number }
}

interface NavItem { to: string; label: string }
interface NavGroup { label: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  { label: 'Home', items: [
    { to: '/', label: 'Overview' },
    { to: '/morning-brief', label: 'Daily Brief' },
  ]},
  { label: 'Portfolio', items: [
    { to: '/portfolio', label: 'Holdings' },
    { to: '/portfolio-intelligence', label: 'Portfolio Intel' },
    { to: '/dividends', label: 'Dividends' },
    { to: '/returns', label: 'Returns' },
    { to: '/attribution', label: 'Attribution' },
    { to: '/tax', label: 'Tax & Lots' },
  ]},
  { label: 'Analysis', items: [
    { to: '/trade-ai', label: '⚡ Trade AI' },
    { to: '/prospects', label: 'Prospects' },
    { to: '/strategy-desk', label: 'Strategy Desk' },
    { to: '/paper-proposals', label: 'Paper Proposals' },
    { to: '/execution-quality', label: 'Execution Quality' },
    { to: '/broker-reconciliation', label: 'Broker Recon' },
    { to: '/paper-outcomes', label: 'Paper Outcomes' },
    { to: '/strategy-admin', label: 'Strategy Admin' },
    { to: '/live-governance', label: 'Live Governance' },
    { to: '/incubator', label: 'Incubator' },
    { to: '/technical', label: 'Technical' },
    { to: '/risk', label: 'Risk' },
    { to: '/correlation', label: 'Correlation' },
    { to: '/forecast', label: 'Forecast' },
    { to: '/research', label: 'Research' },
  ]},
  { label: 'Strategy', items: [
    { to: '/watchlist', label: 'Watchlist' },
    { to: '/portfolio-monitor', label: 'Portfolio Monitor' },
    { to: '/cio', label: 'CIO Dashboard' },
    { to: '/rebalance', label: 'Rebalance' },
    { to: '/recovery', label: 'Recovery Watch' },
  ]},
  { label: 'Retirement', items: [
    { to: '/retirement', label: 'Retirement' },
    { to: '/ai-analyst', label: 'AI Analyst' },
    { to: '/reports', label: 'Reports' },
  ]},
  { label: 'Journal', items: [
    { to: '/journal', label: 'Journal' },
    { to: '/journal-analytics', label: 'Analytics' },
    { to: '/journal-reports', label: 'Reports' },
    { to: '/paper-journal', label: 'Paper Journal' },
  ]},
  { label: 'System', items: [
    { to: '/hub', label: 'System Hub' },
    { to: '/system-health', label: 'System Health' },
    { to: '/paper-status', label: 'Paper Status' },
    { to: '/agent-monitor', label: 'Agent Monitor' },
    { to: '/reports/agent_orchestration.html', label: 'Orchestration' },
    { to: '/intelligence-sources', label: 'Intel Sources' },
    { to: '/intelligence-entities', label: 'Intel Entities' },
    { to: '/intelligence-whiteboard', label: 'Whiteboard' },
    { to: '/agent-pipeline', label: 'Agent Pipeline' },
    { to: '/content-health', label: 'Content Health' },
    { to: '/actions', label: 'Actions' },
    { to: '/approvals', label: 'Approvals' },
  ]},
]

const UTILITY_NAV = [
  { to: '/alerts', label: 'Alerts & Actions' },
  { to: '/notifications', label: 'Notification Log' },
  { to: '/ops', label: 'Ops Console' },
  { to: '/orchestration', label: 'Orchestration' },
]

function fmtDollar(v?: number) {
  if (v == null || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}

function NavDropdown({ group, pendingApprovals }: { group: NavGroup; pendingApprovals: number }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const location = useLocation()

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on route change
  useEffect(() => { setOpen(false) }, [location.pathname])

  // Check if any item in this group is active
  const isGroupActive = group.items.some(item =>
    item.to === '/' ? location.pathname === '/v2' || location.pathname === '/v2/' || location.pathname === '/' : location.pathname.startsWith(`/v2${item.to}`) || location.pathname === item.to
  )

  // Single-item group: render as direct link
  if (group.items.length === 1) {
    const item = group.items[0]
    return (
      <NavLink to={item.to} end={item.to === '/'} className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}>
        {item.label}
      </NavLink>
    )
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        className={`${styles.navLink} ${isGroupActive ? styles.active : ''}`}
        style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}
      >
        {group.label}
        <span style={{ fontSize: 8, opacity: 0.5 }}>{open ? '▲' : '▼'}</span>
        {group.label === 'System' && pendingApprovals > 0 && (
          <span style={{ marginLeft: 2, fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 8, background: 'var(--red)', color: '#fff', verticalAlign: 'super' }}>
            {pendingApprovals}
          </span>
        )}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, zIndex: 50,
          minWidth: 180, background: 'var(--bg2)', border: '1px solid var(--border-hover)',
          borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,.5)',
          padding: 4, marginTop: 2,
        }}>
          {group.items.map(item => (
            item.to === '/agent-monitor' || item.to.startsWith('/reports/') ? (
              <a key={item.to} href={item.to} className={styles.dropLink}
                onClick={() => setOpen(false)}>
                {item.label}
              </a>
            ) : (
              <NavLink key={item.to} to={item.to} end={item.to === '/'}
                className={({ isActive }) => isActive ? styles.dropActive : styles.dropLink}
                onClick={() => setOpen(false)}
              >
                {item.label}
                {item.label === 'Approvals' && pendingApprovals > 0 && (
                  <span style={{ marginLeft: 'auto', fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 8, background: 'var(--red)', color: '#fff' }}>
                    {pendingApprovals}
                  </span>
                )}
              </NavLink>
            )
          ))}
        </div>
      )}
    </div>
  )
}

export default function Shell() {
  const [utilOpen, setUtilOpen] = useState(false)
  const [personalOpen, setPersonalOpen] = useState(false)
  const navigate = useNavigate()
  const { data } = useApi<OverviewMini>('/api/v2/overview', 30000)

  const regime = data?.trade_ai?.breadth || '—'
  const setupState = `${data?.trade_ai?.go_count ?? 0} GO · ${data?.trade_ai?.wait_count ?? 0} WAIT · ${data?.trade_ai?.no_go_count ?? 0} NO GO`
  const pendingApprovals = data?.pending_approvals ?? 0

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.tape}>
          <div className={styles.brandWrap}>
            <span className={styles.brandBolt}>⚡</span>
            <span className={styles.brand}>Command Center</span>
          </div>
          <TapeMetric label="Portfolio" value={fmtDollar(data?.portfolio_value)} onClick={() => navigate('/portfolio')} />
          <TapeMetric label="Today" value={fmtDollar(data?.today_change)} good={(data?.today_change ?? 0) > 0} bad={(data?.today_change ?? 0) < 0} onClick={() => navigate('/returns')} />
          <TapeMetric label="VIX" value={data?.trade_ai?.vix != null ? String(data.trade_ai.vix.toFixed(1)) : '—'} onClick={() => navigate('/trade-ai')} />
          <TapeMetric label="Regime" value={regime} bad={String(regime).toLowerCase().includes('bear')} onClick={() => navigate('/trade-ai')} />
          <TapeMetric label="Last Run" value={`${data?.trade_ai?.run_label || '—'} ${data?.trade_ai?.run_date || ''}`.trim()} onClick={() => navigate('/trade-ai')} />
          <TapeMetric label="Setup State" value={setupState} good={(data?.trade_ai?.go_count ?? 0) > 0} onClick={() => navigate('/trade-ai')} />
          <TapeMetric label="Journal P&L" value={fmtDollar(data?.journal?.total_pnl)} good={(data?.journal?.total_pnl ?? 0) >= 0} onClick={() => navigate('/journal-analytics')} />
          <TapeMetric label="Win Rate" value={data?.journal?.win_rate != null ? `${data.journal.win_rate}%` : '—'} good={(data?.journal?.win_rate ?? 0) >= 50} onClick={() => navigate('/journal-analytics')} />
          <div className={styles.live}><span className={styles.dot} />{data?.as_of || 'Live'}</div>
          <button className={styles.utilityBtn} onClick={() => setPersonalOpen(true)} title="Personal Situation — age, SSDI, filing status, accounts">👤</button>
          <button className={styles.utilityBtn} onClick={() => setUtilOpen(v => !v)}>
            Utilities
            {pendingApprovals > 0 && (
              <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 8, background: 'var(--red)', color: '#fff', minWidth: 16, textAlign: 'center', display: 'inline-block' }}>
                {pendingApprovals}
              </span>
            )}
          </button>
        </div>

        <div className={styles.navRow}>
          <nav className={styles.nav}>
            {NAV_GROUPS.map(group => (
              <NavDropdown key={group.label} group={group} pendingApprovals={pendingApprovals} />
            ))}
          </nav>
          {utilOpen && (
            <div className={styles.utilityMenu}>
              <div className={styles.utilityTitle}>Admin / Ops Utility</div>
              {UTILITY_NAV.map(item => (
                <NavLink key={item.to} to={item.to} className={styles.utilityLink} onClick={() => setUtilOpen(false)}>
                  {item.label}
                </NavLink>
              ))}
            </div>
          )}
        </div>
      </header>
      {personalOpen && <AdminModals type="personal" onClose={() => setPersonalOpen(false)} />}
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}

function TapeMetric({ label, value, good, bad, onClick }: { label: string; value: string; good?: boolean; bad?: boolean; onClick?: () => void }) {
  return (
    <div className={styles.metric} onClick={onClick} style={onClick ? { cursor: 'pointer' } : undefined}>
      <div className={styles.metricLabel}>{label}</div>
      <div className={`${styles.metricValue} ${good ? styles.good : ''} ${bad ? styles.bad : ''}`}>{value}</div>
    </div>
  )
}
