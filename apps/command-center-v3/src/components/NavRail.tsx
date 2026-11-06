import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useNavHere, openAllSheet } from '../hooks/useNavHere'
import { HOME_APPROVALS, titledWithCount, type NeedsYouSummary } from '../lib/homeApprovals'
import { NAV, isHere, pageHref, sectionPages, visibleGroups, type NavSection, type NavSectionId } from '../lib/navConfig'
import '../styles/navShell.css'

/** Level 1 of the menu (design nav/v001, operator-approved 2026-11-06).
 *
 *  Phone (≤ 820 px): a bottom tab bar with the five sections, always on screen; tapping the active tab again opens
 *  the section's "All ▾" grouped sheet (SectionStrip). Desktop: a rail with the same five sections, the active one
 *  expanded into its groups and pages, the others folded with a page count. One table drives both (lib/navConfig).
 *  The ☰ command bar and full-screen nav sheet are gone; every page they listed is still one or two taps away. */

const ICONS: Record<NavSectionId, ReactNode> = {
  home: <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />,
  portfolio: <><circle cx="12" cy="12" r="8" /><path d="M12 4v8l6 4" /></>,
  trade: <><path d="M4 18l5-6 4 3 7-9" /><path d="M15 6h5v5" /></>,
  intel: <><path d="M12 3a6 6 0 0 1 4 10.5V17H8v-3.5A6 6 0 0 1 12 3z" /><path d="M9 21h6" /></>,
  ops: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></>,
}
const Icon = ({ id }: { id: NavSectionId }) => <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[id]}</svg>

/** Where a section tab goes: its first page (Home → Today, Portfolio → Holdings, …). */
const sectionHref = (s: NavSection) => pageHref(s.groups[0].pages[0])

export default function NavRail() {
  const { here, showPreview, pathname } = useNavHere()
  // Home v008 "Needs you" (spec §1): open-decision count on Home and in the tab title. Background priority so the
  // page's own reads go first; a 403 or an unreadable store simply shows no badge.
  const needsYou = useApi<NeedsYouSummary>(`${HOME_APPROVALS}/summary`, 60_000, { priority: 'background' })
  const needsYouCount = typeof needsYou.data?.count === 'number' ? needsYou.data.count : null
  useEffect(() => {
    if (typeof document === 'undefined') return
    document.title = titledWithCount(document.title, needsYouCount)
  }, [needsYouCount, pathname])
  const railRef = useRef<HTMLElement | null>(null)

  // The rail always takes its clicks (operator 2026-10-08: "cant click watch"). Pages draw their own full-screen
  // overlays (z 900–10000: message panels, drawers, modals) on top of the rail, so a click on a nav link landed on
  // the backdrop instead. A click whose point is over the rail goes to the rail link under it, whatever is on top;
  // the route change then unmounts the page and its overlay. Capture phase, so the overlay never sees the click.
  // Desktop rail only: on a phone the rail is display:none (zero rect) and the bottom bar sits under the sheets.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const rail = railRef.current
      const target = e.target as Node | null
      if (!rail || !target || rail.contains(target)) return
      const r = rail.getBoundingClientRect()
      if (!r.width || e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return
      const under = document.elementsFromPoint(e.clientX, e.clientY).find(el => rail.contains(el))
      const link = under?.closest('a') as HTMLAnchorElement | null
      if (!link) return
      e.preventDefault()
      e.stopPropagation()
      link.click()
    }
    window.addEventListener('click', onClick, true)
    return () => window.removeEventListener('click', onClick, true)
  }, [])

  const badge = needsYouCount != null && needsYouCount > 0 ? needsYouCount : null
  const badgeTitle = badge ? `${badge} decision${badge === 1 ? '' : 's'} need you` : undefined

  return (
    <>
      <nav ref={railRef} className="nav-rail" aria-label="Sections">
        {NAV.map(section => {
          const active = here?.section.id === section.id
          const groups = visibleGroups(section, showPreview)
          const count = sectionPages(section, false).length
          return (
            <div key={section.id} className={'nav-sec' + (active ? ' is-active' : '')}>
              <Link
                to={sectionHref(section)}
                state={{ navSection: section.id }}
                className="nav-sec__head"
                aria-expanded={active}
                aria-current={active && here?.page === section.groups[0].pages[0] ? 'page' : undefined}
              >
                <Icon id={section.id} />
                <span className="nav-sec__label">{section.label}</span>
                {section.id === 'home' && badge
                  ? <span className="nav-badge" data-testid="nav-needs-you-badge" aria-hidden="true" title={badgeTitle}>{badge}</span>
                  : <span className="nav-sec__count" aria-hidden="true">{active ? '▾' : `▸ ${count}`}</span>}
              </Link>
              {active && groups.map(g => (
                <div key={g.label} className="nav-group" role="group" aria-label={g.label}>
                  {(groups.length > 1 || g.label !== section.label) && <div className="nav-eyebrow">{g.label}</div>}
                  {g.pages.map(p => (
                    <Link
                      key={p.label}
                      to={pageHref(p)}
                      state={{ navSection: section.id }}
                      className={'nav-item' + (isHere(here, section, p) ? ' is-active' : '')}
                      aria-current={isHere(here, section, p) ? 'page' : undefined}
                    >
                      {p.label}
                    </Link>
                  ))}
                </div>
              ))}
            </div>
          )
        })}
      </nav>

      <nav className="nav-tabbar" aria-label="Sections">
        {NAV.map(section => {
          const active = here?.section.id === section.id
          return (
            <Link
              key={section.id}
              to={sectionHref(section)}
              state={{ navSection: section.id }}
              className={'nav-tab' + (active ? ' is-active' : '')}
              aria-current={active ? 'page' : undefined}
              onClick={e => {
                // Tapping the section you are in opens its grouped "All ▾" sheet instead of reloading its first page.
                if (!active) return
                e.preventDefault()
                openAllSheet(section.id)
              }}
            >
              <Icon id={section.id} />
              <span className="nav-tab__label">{section.label}</span>
              {section.id === 'home' && badge && <span className="nav-badge nav-tab__badge" data-testid="nav-needs-you-tab-badge" aria-hidden="true" title={badgeTitle}>{badge}</span>}
            </Link>
          )
        })}
      </nav>
    </>
  )
}
