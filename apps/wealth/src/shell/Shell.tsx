// Wealth shell, ported from the v02 reference (docs/wealth/design-reference/…_v02.html, sha256
// 23f96d84…): ribbon, fixed left nav with group icons, top bar, page heading, per-group tabs, the
// right-hand drawer host, and the context footer. Structure, classes and order follow the reference.
//
// Differences from the reference, each deliberate:
//  * The ribbon states this build's real identity (version, source sha, accepted or not), not
//    "fictional data".
//  * Top-bar values have no bound reader yet: they render UNKNOWN with the reason, never a number.
//  * Prototype-only controls are not ported: review dock, "Approve direction", phone preview,
//    review guide, design-review nav group, the demo account selector and the avatar initials.
//  * The shell polls nothing and fetches nothing heavy. Pages own their reads (api/readers.ts).
import { Fragment, useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import './v02.css'
import { Icon } from '../components/Icon'
import { DrawerProvider } from '../components/Drawer'
import { CueBadge } from '../components/primitives'
import { NAV, groupPath, resolve, viewPath } from './nav'

const SOURCE = __WEALTH_SOURCE_SHA__ ? __WEALTH_SOURCE_SHA__.slice(0, 9) : 'unknown'

const UNBOUND = {
  level: 'NEUTRAL' as const, label: 'UNKNOWN', icon: 'unassessed' as const,
  tooltip: 'No canonical reader is bound to the top bar yet (portfolio owner). Shown as UNKNOWN, never as a number.',
}

export function Shell() {
  const { pathname } = useLocation()
  const { group, view, known } = resolve(pathname)

  useEffect(() => {
    document.body.classList.remove('menu-open')
    window.scrollTo(0, 0)
    document.title = `${group.label} / ${view.label} • Trade-AI Wealth`
  }, [pathname, group.label, view.label])

  return (
    <DrawerProvider>
      <div className="preview-ribbon" role="note">
        <b>TRADE-AI WEALTH · v{__WEALTH_APP_VERSION__}</b>
        <span>build {SOURCE}</span>
        <span className="wide">Not yet accepted · Command Center stays available</span>
      </div>
      <div className="app">
        <aside>
          <div className="brand"><span className="brandmark">T</span><div><b>TRADE-AI</b><small>INVESTMENT DESK</small></div></div>
          <div className="nav-label">YOUR WORKSPACE</div>
          <nav id="main-nav" aria-label="Main pages">
            {NAV.map(x => (
              <Fragment key={x.id}>
                {x.sectionLabel ? <div className="nav-label">{x.sectionLabel}</div> : null}
                <NavLink to={groupPath(x)} className={x.id === group.id ? 'active' : ''} aria-current={x.id === group.id ? 'page' : undefined}>
                  <Icon name={x.icon} />{x.label}
                </NavLink>
              </Fragment>
            ))}
          </nav>
          <div className="nav-foot">One book. One decision record.<br /><br /><a href="/v3/">Command Center (classic) →</a></div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <div className="scope">
              <button className="mobile-menu quiet" aria-label="Open navigation" onClick={() => document.body.classList.toggle('menu-open')}>☰</button>
              <div className="top-values">
                <div><span className="muted">Account value</span><strong><CueBadge cue={UNBOUND} /></strong></div>
                <div><span className="muted">Regular-session move</span><strong><CueBadge cue={UNBOUND} /></strong></div>
              </div>
            </div>
            <div className="top-actions" />
          </header>
          <main className="page" id="main">
            <div className="page-heading">
              <div>
                <div className="eyebrow">{group.tagline}</div>
                <h1 style={{ marginTop: 7 }}>{group.label} <span className="muted" style={{ fontWeight: 300 }}>/</span> {view.label}</h1>
              </div>
            </div>
            <nav className="tabs" aria-label={`${group.label} tabs`}>
              {group.views.map(v => (
                <Link key={v.id} to={viewPath(group, v)} className={v.id === view.id ? 'active' : ''} aria-current={v.id === view.id ? 'page' : undefined}>{v.label}</Link>
              ))}
            </nav>
            {known ? <Outlet /> : <div className="note bad">Unknown Wealth address. Showing {group.label} / {view.label}.</div>}
            <div className="context-footer">TRADE-AI WEALTH v{__WEALTH_APP_VERSION__} · build {SOURCE} · design v0.2 · read-only: no orders, no approvals, no writes.</div>
          </main>
        </div>
      </div>
    </DrawerProvider>
  )
}
