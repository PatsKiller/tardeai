import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { NAV_ALL_EVENT, useNavHere } from '../hooks/useNavHere'
import { NAV, isHere, pageHref, sectionPages, stripPages, visibleGroups, type NavSectionId } from '../lib/navConfig'
import '../styles/navShell.css'

/** Level 2 of the menu (design nav/v001): the pages of the current section as a pill strip at the top of the page,
 *  same component on phone and desktop. Long sections (Intel 11, Ops 13) show their most-used pages and end with
 *  "All ▾", a grouped sheet listing every page of the section; re-tapping the active bottom tab opens it too.
 *  The highlighted pill says where you are, so pages need no "← back to …" breadcrumb. Level 3 (a page's own
 *  underline tabs) is untouched. An unknown route shows no strip rather than pretending to be Home. */
export default function SectionStrip() {
  const { here, showPreview } = useNavHere()
  const { pathname } = useLocation()
  const [sheetFor, setSheetFor] = useState<NavSectionId | null>(null)
  const sheetRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const onAll = (e: Event) => setSheetFor((e as CustomEvent<NavSectionId>).detail)
    window.addEventListener(NAV_ALL_EVENT, onAll)
    return () => window.removeEventListener(NAV_ALL_EVENT, onAll)
  }, [])
  // The sheet never survives a route change.
  useEffect(() => { setSheetFor(null) }, [pathname])
  useEffect(() => {
    if (!sheetFor) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSheetFor(null) }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    sheetRef.current?.focus()
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey) }
  }, [sheetFor])

  const sheetSection = sheetFor ? NAV.find(s => s.id === sheetFor) ?? null : null
  if (!here && !sheetSection) return null

  const section = here?.section
  const pills = section ? stripPages(section, showPreview, here!.page) : []
  const hasMore = !!section && pills.length < sectionPages(section, showPreview).length

  return (
    <>
      {section && (
        <div className="section-strip" data-testid="section-strip">
          <div className="section-strip__where">
            <span className="section-strip__title">{section.label}</span>
            {here!.page.label !== section.label && <><span className="section-strip__sep" aria-hidden="true">›</span><span className="section-strip__page">{here!.page.label}</span></>}
          </div>
          <nav className="section-strip__pills" aria-label={`${section.label} pages`}>
            {pills.map(p => {
              const on = isHere(here, section, p)
              return (
                <Link key={p.label} to={pageHref(p)} state={{ navSection: section.id }} className={'section-pill' + (on ? ' is-active' : '')} aria-current={on ? 'page' : undefined}>
                  {p.label}
                </Link>
              )
            })}
            {hasMore && (
              <button type="button" className="section-pill section-pill--all" aria-haspopup="dialog" aria-expanded={sheetFor === section.id} onClick={() => setSheetFor(section.id)}>
                All ▾
              </button>
            )}
          </nav>
        </div>
      )}
      {sheetSection && (
        <div className="nav-all" data-testid="nav-all-sheet">
          <div className="nav-all__scrim" onClick={() => setSheetFor(null)} aria-hidden="true" />
          <div ref={sheetRef} className="nav-all__sheet" role="dialog" aria-modal="true" aria-label={`All ${sheetSection.label} pages`} tabIndex={-1}>
            <div className="nav-all__head">
              <span className="nav-all__title">{sheetSection.label}</span>
              <button type="button" className="nav-all__close" aria-label="Close" onClick={() => setSheetFor(null)}>✕</button>
            </div>
            {visibleGroups(sheetSection, showPreview).map(g => (
              <div key={g.label} className="nav-all__group" role="group" aria-label={g.label}>
                <div className="nav-all__label">{g.label}</div>
                <div className="nav-all__opts">
                  {g.pages.map(p => {
                    const on = isHere(here, sheetSection, p)
                    return (
                      <Link key={p.label} to={pageHref(p)} state={{ navSection: sheetSection.id }} className={'section-pill' + (on ? ' is-active' : '')} aria-current={on ? 'page' : undefined} onClick={() => setSheetFor(null)}>
                        {p.label}
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
