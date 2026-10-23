// Where am I? — the mobile command bar's "SECTION · Page" label.
//
// Site validation 2026-10-22: every route that is routed in App.tsx but not on the rail fell back to
// "Trade · Home" (/intelligence, /strategy, /agents, /hermes, /reports, …), and /portfolio/re-entry
// did too because Portfolio's rail entry is exact. A phone showed "TRADE Home" above the
// Intelligence page. Off-rail routes now carry their own label, and an unknown path says so
// instead of claiming to be Home.

export type NavHub = { to: string; label: string; exact?: boolean }
export type NavSection = { label: string; hubs: NavHub[] }

/** Routed in App.tsx but off the rail (secondary hubs). Section = where the operator reaches it from. */
export const OFF_RAIL: NavSection[] = [
  { label: 'Trade', hubs: [
    { to: '/portfolio/re-entry', label: 'Re-Entry' },
    { to: '/strategy', label: 'Strategy' },
    { to: '/retirement', label: 'Retirement' },
    { to: '/redeploy', label: 'Redeploy' },
    { to: '/defense', label: 'Defense' },
    { to: '/watch-legacy', label: 'Watch (legacy)' },
  ] },
  { label: 'Intel', hubs: [
    { to: '/intelligence', label: 'Intelligence' },
    { to: '/agents', label: 'Agents' },
    { to: '/hermes', label: 'Hermes' },
    { to: '/reports', label: 'Reports' },
    { to: '/rotation', label: 'Rotation' },
    { to: '/rec-intel', label: 'Rec Intel' },
    { to: '/advisory', label: 'Advisory' },
  ] },
  { label: 'Ops', hubs: [
    { to: '/system/schwab-reauth', label: 'Schwab Re-auth' },
  ] },
]

/** Longest-prefix match over the rail sections, then the off-rail routes. */
export function locateIn(pathname: string, sections: NavSection[]): { section: string; page: string } {
  let best: { section: string; page: string; len: number } | null = null
  for (const sec of [...sections, ...OFF_RAIL]) {
    for (const h of sec.hubs) {
      const hit = h.exact ? pathname === h.to : pathname === h.to || pathname.startsWith(h.to + '/')
      if (hit && (!best || h.to.length > best.len)) best = { section: sec.label, page: h.label, len: h.to.length }
    }
  }
  return best ? { section: best.section, page: best.page } : { section: 'Command Center', page: 'Page' }
}
