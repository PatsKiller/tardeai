/** The one navigation table (design nav/v001, operator-approved 2026-11-06: "I approve the menu redesign implement").
 *
 *  section → group → page → route. It drives the phone bottom tab bar (level 1), the desktop rail with the active
 *  section expanded into its groups, the level-2 sub-tab strip and its "All ▾" grouped sheet, and "where am I"
 *  (locateNav). Level 3 stays each page's own underline tabs (?tab=), which this file never touches.
 *
 *  Nothing is removed: every route the old rail (NavRail.tsx SECTIONS + the Control Plane preview) or the off-rail
 *  list (navLocate.ts OFF_RAIL) reached is still a page here or matches one (navConfig.test.ts asserts it).
 *  URLs do not change, so bookmarks, Telegram deep links and ?tab= keep working.
 *
 *  Two pages appear in two sections on purpose (mockup §3 note 8): Home › Needs you and Ops › Approvals open
 *  /approvals; Home › My questions opens /cio/questions (Intel › CIO Desk › My questions since intel/v001). The Home copies are `alias` entries:
 *  the same route, so nothing is duplicated, and "where am I" follows the section the operator came from. */

export type NavSectionId = 'home' | 'portfolio' | 'trade' | 'intel' | 'ops'

export type NavPage = {
  /** Route path (router-relative, without the /v3 basename). */
  to: string
  label: string
  /** Match only the exact path (no sub-paths). */
  exact?: boolean
  /** Query string the link carries, e.g. '?tab=waiting'. A located URL carrying it prefers this page. */
  search?: string
  /** A second copy of a page that lives in another section (same route). */
  alias?: boolean
  /** Shown in the phone strip before "All ▾" for the long sections. Short sections show every page. */
  strip?: boolean
  /** Extra off-menu path prefixes that belong to this page (opened from it, not listed separately). */
  match?: string[]
}
export type NavGroup = { label: string; pages: NavPage[]; preview?: boolean }
export type NavSection = { id: NavSectionId; label: string; groups: NavGroup[] }

/** Control Plane preview: same flag (localStorage CC_CONTROL_PLANE_PREVIEW=1, or being on /control-plane), same 11 pages. */
export const CONTROL_PLANE_GROUP: NavGroup = {
  label: 'Preview (flag)',
  preview: true,
  pages: [
    { to: '/control-plane', label: 'Control Plane', exact: true },
    { to: '/control-plane/system', label: 'CP · System' },
    { to: '/control-plane/agents', label: 'CP · Agent Office' },
    { to: '/control-plane/workflows', label: 'CP · Workflow Trace' },
    { to: '/control-plane/research', label: 'CP · Research' },
    { to: '/control-plane/data', label: 'CP · Data' },
    { to: '/control-plane/identity', label: 'CP · Identity' },
    { to: '/control-plane/notifications', label: 'CP · Notifications' },
    { to: '/control-plane/learning', label: 'CP · Learning' },
    { to: '/control-plane/maturity', label: 'CP · Maturity' },
    { to: '/control-plane/audit', label: 'CP · Audit' },
  ],
}

export const NAV: NavSection[] = [
  {
    id: 'home', label: 'Home', groups: [
      { label: 'Home', pages: [
        { to: '/', label: 'Today', exact: true },
        { to: '/approvals', search: '?tab=waiting', label: 'Needs you', alias: true },
        { to: '/cio/questions', label: 'My questions', alias: true },
      ] },
    ],
  },
  {
    id: 'portfolio', label: 'Portfolio', groups: [
      { label: 'What I own', pages: [
        { to: '/portfolio', label: 'Holdings', exact: true },
        { to: '/retirement', label: 'Retirement' },
      ] },
      { label: 'Protect', pages: [
        { to: '/risk', label: 'Risk' },
        { to: '/defense', label: 'Defense' },
      ] },
      { label: 'Reposition', pages: [
        { to: '/portfolio/re-entry', label: 'Re-Entry' },
        { to: '/rotation', label: 'Rotation', match: ['/advisor-changes'] },
        { to: '/redeploy', label: 'Redeploy' },
      ] },
    ],
  },
  {
    id: 'trade', label: 'Trade', groups: [
      { label: 'Trade', pages: [
        { to: '/trading', label: 'Trading', match: ['/go/order', '/go/proposal', '/manual-execution'] },
        { to: '/watch', label: 'Watch', match: ['/watch-legacy', '/watchlist', '/watchpool', '/sectors', '/pullback-macd'] },
        { to: '/active-trader', label: 'Active Trader' },
        { to: '/strategy', label: 'Strategy', match: ['/rec-intel'] },
        { to: '/journal', label: 'Journal (TradeInView)', match: ['/trade-in-view'] },
      ] },
    ],
  },
  {
    id: 'intel', label: 'Intel', groups: [
      // Intel consolidation (intel/v001, 2026-11-06): Advisory → CIO Desk › Holdings verdicts; My questions → a CIO
      // Desk tab; Intelligence + Research lineage → Research Intel tabs; Rec Intelligence → Strategy (Trade) and
      // Prospectus › My history; Hermes → Ops › Engines. The old URLs redirect (App.tsx) and still locate here.
      { label: 'Desks', pages: [
        { to: '/cio', label: 'CIO Desk', exact: true, strip: true, match: ['/advisory', '/cio/questions'] },
      ] },
      { label: 'Research', pages: [
        { to: '/research-intelligence', label: 'Research Intel', strip: true, match: ['/research', '/intelligence', '/closed-loop'] },
        { to: '/prospectus', label: 'Prospectus' },
      ] },
      { label: 'Outputs', pages: [
        { to: '/reports', label: 'Reports' },
        { to: '/communications', label: 'Communications' },
      ] },
    ],
  },
  {
    id: 'ops', label: 'Ops', groups: [
      { label: 'Is it running', pages: [
        { to: '/health', label: 'Health', strip: true },
        { to: '/ops/jobs-n8n', label: 'Jobs & n8n', strip: true },
        { to: '/ops/jobs', label: 'Jobs & health' },
        { to: '/ops/incidents', label: 'Incidents', strip: true },
      ] },
      { label: 'Agents & cost', pages: [
        { to: '/agents', label: 'Agents' },
        { to: '/consumption', label: 'LLM Spend' },
        { to: '/coordination', label: 'Coordination' },
        { to: '/ops/engines', label: 'Engines', match: ['/hermes'] },
      ] },
      { label: 'Decide', pages: [
        { to: '/approvals', label: 'Approvals', strip: true },
        { to: '/policy', label: 'Rulebook' },
        { to: '/conflicts/rules', label: 'Conflicts' },
      ] },
      { label: 'Configure', pages: [
        { to: '/system/ops-controls', label: 'Ops Controls' },
        { to: '/system/releases', label: 'Releases & Schedules' },
        { to: '/system/broker-access', label: 'Broker Access' },
        // Not exact: /system/schwab-reauth (opened from System) lands here; the longer /system/* pages win by prefix length.
        { to: '/system', label: 'System' },
      ] },
      CONTROL_PLANE_GROUP,
    ],
  },
]

/** The groups a viewer sees: the Control Plane preview group only behind its flag (unchanged rule). */
export function visibleGroups(section: NavSection, showPreview: boolean): NavGroup[] {
  return section.groups.filter(g => !g.preview || showPreview)
}

export function sectionPages(section: NavSection, showPreview: boolean): NavPage[] {
  return visibleGroups(section, showPreview).flatMap(g => g.pages)
}

/** Pages in the level-2 strip: every page for short sections, the `strip` subset (plus the current page) for long ones. */
export function stripPages(section: NavSection, showPreview: boolean, current: NavPage | null): NavPage[] {
  const all = sectionPages(section, showPreview)
  const marked = all.filter(p => p.strip)
  if (!marked.length) return all
  return current && !marked.includes(current) ? [...marked, current] : marked
}

export const pageHref = (p: NavPage) => p.to + (p.search ?? '')

export type NavHere = { section: NavSection; page: NavPage } | null

function hitLength(pathname: string, p: NavPage): number {
  const prefixes = [p.to, ...(p.match ?? [])]
  let best = -1
  for (const [i, to] of prefixes.entries()) {
    const exact = i === 0 && p.exact
    const hit = exact ? pathname === to : pathname === to || pathname.startsWith(to === '/' ? '/' : to + '/')
    if (hit && !(to === '/' && !exact && pathname !== '/')) best = Math.max(best, to.length)
  }
  return best
}

/** Where am I: longest route-prefix match over every page. When one route lives in two sections, prefer
 *  (1) the section the operator navigated from, (2) the copy whose query matches the URL, (3) the primary copy. */
export function locateNav(pathname: string, search = '', prefer?: NavSectionId | null): NavHere {
  type Hit = { section: NavSection; page: NavPage; len: number }
  let hits: Hit[] = []
  let bestLen = -1
  for (const section of NAV) {
    for (const group of section.groups) {
      for (const page of group.pages) {
        const len = hitLength(pathname, page)
        if (len < 0) continue
        if (len > bestLen) { bestLen = len; hits = [{ section, page, len }] }
        else if (len === bestLen) hits.push({ section, page, len })
      }
    }
  }
  if (!hits.length) return null
  const query = new URLSearchParams(search)
  const queryMatch = (p: NavPage) => !!p.search && [...new URLSearchParams(p.search)].every(([k, v]) => query.get(k) === v)
  const pick = (prefer && hits.find(h => h.section.id === prefer))
    || hits.find(h => queryMatch(h.page))
    || hits.find(h => !h.page.alias)
    || hits[0]
  return { section: pick.section, page: pick.page }
}

/** True when `page` is the located page (alias copies count as the same route only inside their own section). */
export function isHere(here: NavHere, section: NavSection, page: NavPage): boolean {
  return !!here && here.section.id === section.id && here.page === page
}
