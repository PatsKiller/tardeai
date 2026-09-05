import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

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
      { to: '/active-trader', label: 'Active Trader' },
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
      { to: '/closed-loop', label: 'Closed Loop' },
      { to: '/hermes', label: 'Hermes' },
      { to: '/advisory', label: 'Advisory Desk' },
      { to: '/cio', label: 'CIO Desk' },
      { to: '/reports', label: 'Reports', hardNav: true },
      { to: '/communications', label: 'Communications' },
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
      { to: '/system', label: 'System', exact: true },
      { to: '/system/schwab-reauth', label: 'Schwab Reauth' },
    ],
  },
]

const CONTROL_PLANE_PREVIEW: { label: string; hubs: Hub[] } = {
  label: 'Control Plane (preview)',
  hubs: [
    { to: '/control-plane', label: 'Hub', exact: true },
    { to: '/control-plane/system', label: 'System' },
    { to: '/control-plane/agents', label: 'Agent Office' },
    { to: '/control-plane/workflows', label: 'Workflow Trace' },
    { to: '/control-plane/research', label: 'Research' },
    { to: '/control-plane/data', label: 'Data' },
    { to: '/control-plane/identity', label: 'Identity' },
    { to: '/control-plane/notifications', label: 'Notifications' },
    { to: '/control-plane/learning', label: 'Learning' },
    { to: '/control-plane/maturity', label: 'Maturity' },
    { to: '/control-plane/audit', label: 'Audit' },
  ],
}

/** Longest-prefix match so /portfolio/re-entry resolves to Re-Entry, not Portfolio. */
function locate(pathname: string): { section: string; page: string } {
  let best: { section: string; page: string; len: number } | null = null
  for (const sec of [...SECTIONS, CONTROL_PLANE_PREVIEW]) {
    for (const h of sec.hubs) {
      const hit = h.exact ? pathname === h.to : pathname === h.to || pathname.startsWith(h.to + '/')
      if (hit && (!best || h.to.length > best.len)) {
        best = { section: sec.label, page: h.label, len: h.to.length }
      }
    }
  }
  return best ? { section: best.section, page: best.page } : { section: 'Trade', page: 'Home' }
}

export default function NavRail() {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [previewFlag, setPreviewFlag] = useState(false)
  useEffect(() => {
    try { setPreviewFlag(localStorage.getItem('CC_CONTROL_PLANE_PREVIEW') === '1') } catch { /* private mode */ }
  }, [pathname])
  const showControlPlane = previewFlag || pathname.startsWith('/control-plane')
  const sections = showControlPlane ? [...SECTIONS, CONTROL_PLANE_PREVIEW] : SECTIONS
  const here = locate(pathname)
  const panelRef = useRef<HTMLDivElement | null>(null)

  // Close on navigation — the sheet must never survive a route change.
  useEffect(() => { setOpen(false) }, [pathname])

  // Escape closes; lock body scroll so the page behind cannot scroll under the sheet.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Reports forces a full page load (it ships its own bundle). Stamping the cache
  // buster at CLICK time, not render time, keeps the href stable across re-renders.
  const hardHref = useCallback((to: string) => `/v3${to}?_cc=${Date.now()}`, [])

  const items = (
    <>
      {sections.map(sec => (
        <div key={sec.label} className="nav-group">
          <div className="nav-eyebrow">{sec.label}</div>
          {sec.hubs.map(h =>
            h.hardNav ? (
              <a
                key={h.to}
                className="nav-item"
                href={hardHref(h.to)}
                aria-current={pathname.startsWith(h.to) ? 'page' : undefined}
                onClick={e => { e.currentTarget.href = hardHref(h.to) }}
              >
                {h.label}
              </a>
            ) : (
              <NavLink
                key={h.to}
                to={h.to}
                end={h.exact}
                className={({ isActive }) => 'nav-item' + (isActive ? ' is-active' : '')}
              >
                {h.label}
              </NavLink>
            ),
          )}
        </div>
      ))}
    </>
  )

  return (
    <>
      {/* Mobile command bar — replaces the rail below 820px. States where you are in
          the app's own taxonomy rather than showing a bare hamburger. */}
      <div className="nav-bar">
        <button
          type="button"
          className="nav-bar__toggle"
          aria-expanded={open}
          aria-controls="nav-sheet"
          aria-label={open ? 'Close navigation' : 'Open navigation'}
          onClick={() => setOpen(v => !v)}
        >
          <span className="nav-bar__glyph" aria-hidden="true">{open ? '✕' : '☰'}</span>
          <span className="nav-bar__where">
            <span className="nav-bar__section">{here.section}</span>
            <span className="nav-bar__page">{here.page}</span>
          </span>
        </button>
      </div>

      <nav
        id="nav-sheet"
        ref={panelRef}
        tabIndex={-1}
        aria-label="Sections"
        className={'nav-rail' + (open ? ' is-open' : '')}
      >
        {/* Sheet header — mobile only. The sheet covers the whole viewport, so it
            carries its own close control rather than depending on where the command
            bar happens to sit under the metric strip. */}
        <div className="nav-sheet__head">
          <span className="nav-bar__where">
            <span className="nav-bar__section">{here.section}</span>
            <span className="nav-bar__page">{here.page}</span>
          </span>
          <button
            type="button"
            className="nav-sheet__close"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          >
            ✕
          </button>
        </div>
        {items}
      </nav>
    </>
  )
}
