// Wealth shell, ported from the v02 reference (docs/wealth/design-reference/…_v02.html, sha256
// 23f96d84…): ribbon, fixed left nav with group icons, top bar, page heading, per-group tabs, the
// right-hand drawer host, and the context footer. Structure, classes and order follow the reference.
//
// Differences from the reference, each deliberate:
//  * The ribbon states this build's real identity (version, source sha, accepted or not), not
//    "fictional data".
//  * Top-bar values have no bound reader of their own: the shell may not originate the heavy holdings reader, so
//    it renders the snapshot the Holdings page publishes. Where nothing is published it says the book is not read
//    on that route; it never shows a number it did not receive and never an UNKNOWN without a reason.
//  * Prototype-only controls are not ported: review dock, "Approve direction", phone preview,
//    review guide, design-review nav group, the demo account selector and the avatar initials.
//  * The shell polls nothing and fetches nothing heavy. Pages own their reads (api/readers.ts).
import { Fragment, useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import './v02.css'
// v04 is the approved fidelity target (operator order 2026-11-15T0301Z). Its sheet is the reference's own
// <style> body and a strict superset of v02 — 257 shared selectors identical, 0 changed — so importing it
// after v02.css adds v04's classes and moves nothing else.
import './v04.css'
import { Icon } from '../components/Icon'
import { DrawerProvider, useDrawer } from '../components/Drawer'
import { PortfolioTopBar } from '../pages/portfolio/TopBar'
import { OperatingHeader, OperatingHeaderProvider, useOperatingHeader } from './OperatingHeader'
import { BookSnapshotProvider } from '../pages/portfolio/snapshot'
import { NAV, groupPath, resolve, viewPath } from './nav'

const SOURCE = __WEALTH_SOURCE_SHA__ ? __WEALTH_SOURCE_SHA__.slice(0, 9) : 'unknown'

export function Shell() {
  // The snapshot sits inside the drawer host so both the top bar and any page can read the one published book.
  return (
    <DrawerProvider>
      <BookSnapshotProvider>
        <OperatingHeaderProvider><ShellFrame /></OperatingHeaderProvider>
      </BookSnapshotProvider>
    </DrawerProvider>
  )
}

// The reference's "Page intent" drawer: process text from v02, with this build's identity. No data.
function intentBody(groupLabel: string, viewLabel: string) {
  return (
    <>
      <h3>{groupLabel} / {viewLabel}</h3>
      <p>Primary question: what does the investor need to understand or decide here? The mockup is a proposed UI contract, not evidence that its backend already exists.</p>
      <h3>Parallel implementation mandate</h3>
      <p>Build a net-new Wealth application beside the current site. Freeze old-site feature upgrades. Reuse canonical backend authority and CIO history; redesign measured bottlenecks. Decommission only after replacement acceptance and rollback readiness.</p>
      <h3>Before each slice</h3>
      <p>Map the actual route, retained capabilities, canonical source, producer, clock, owner and acceptance. Use available backend first. Missing capabilities remain owned work.</p>
      <h3>This build</h3>
      <p>Wealth v{__WEALTH_APP_VERSION__} · build {SOURCE}. Not yet accepted; Command Center stays available. Read-only: no orders, no approvals, no writes.</p>
    </>
  )
}

function ShellFrame() {
  const drawer = useDrawer()
  const { pathname } = useLocation()
  const { group, view, known } = resolve(pathname)
  const operating = useOperatingHeader()

  useEffect(() => {
    document.body.classList.remove('menu-open')
    window.scrollTo(0, 0)
    document.title = `${group.label} / ${view.label} • Trade-AI Wealth`
  }, [pathname, group.label, view.label])

  return (
    <>
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
          <header className="wealth-operating-region">
            <PortfolioTopBar controlsOnly />
            <OperatingHeader />
          </header>
          <main className="page" id="main">
            <div className="page-heading">
              <div>
                <div className="eyebrow">{group.tagline}</div>
                <h1 style={{ marginTop: 7 }}>{group.label} <span className="muted" style={{ fontWeight: 300 }}>/</span> {view.label}</h1>
                <p>One book, clear evidence, supported next steps</p>
              </div>
              <div className="heading-action">
                <button className="small" onClick={() => drawer.open({ eyebrow: 'PAGE INTENT', title: 'Page intent & implementation gate', body: intentBody(group.label, view.label) })}>Page intent →</button>
              </div>
            </div>
            <nav className="tabs" aria-label={`${group.label} tabs`}>
              {group.views.map(v => (
                <Link key={v.id} to={viewPath(group, v)} className={v.id === view.id ? 'active' : ''} aria-current={v.id === view.id ? 'page' : undefined}>{v.label}{group.id === 'home' && v.id === 'needs' ? <span className="home-queue-count" title="Live stored review queue total"> · {operating.queueTotal ?? 'not served'}</span> : null}</Link>
              ))}
            </nav>
            {known ? <Outlet /> : <div className="note bad">Unknown Wealth address. Showing {group.label} / {view.label}.</div>}
            <div className="context-footer">TRADE-AI WEALTH v{__WEALTH_APP_VERSION__} · build {SOURCE} · design v0.4 · read-only: no orders, no approvals, no writes.</div>
          </main>
        </div>
      </div>
    </>
  )
}
