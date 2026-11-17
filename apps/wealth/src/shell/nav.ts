// Navigation model, ported from the v02 reference `groups` (docs/wealth/design-reference/
// TradeAI_Wealth_Management_Mockups_v02.html). Same groups, labels, taglines, tab order and ids.
// Dropped: the reference's 'review' group (Design review / Review guide / Whole-site plan / Backend
// contract / Approval register). It is the prototype's approval tooling, not a product page.
//
// URL scheme: /wealth/<group>/<view>. The reference used #group/view hashes; the lead's router
// (App.tsx, routes/) maps these paths to pages. Unknown group → home; unknown view → the group's first.

import { FAMILIES } from '../routes/families'

export interface NavView { id: string; label: string }
export interface NavGroup { id: string; label: string; tagline: string; icon: string; views: NavView[]; sectionLabel?: string }

const g = (id: string, label: string, tagline: string, views: [string, string][], sectionLabel?: string): NavGroup =>
  ({ id, label, tagline, icon: id, views: views.map(([vid, vl]) => ({ id: vid, label: vl })), sectionLabel })

export const NAV: NavGroup[] = [
  g('home', 'Home', 'Daily direction', [['today', 'Investment desk'], ['outlook', 'Market outlook'], ['needs', 'Needs your review']]),
  g('portfolio', 'Portfolio', 'Wealth & returns', [['holdings', 'Holdings'], ['performance', 'Performance'], ['income', 'Income'], ['allocation', 'Allocation'], ['retirement', 'Retirement'], ['fundamentals', 'Fundamentals'], ['levels', 'Levels & valuation']]),
  g('protection', 'Risk & defense', 'Protect your book', [['exposure', 'Risk exposure'], ['coverage', 'Stop coverage'], ['defense', 'Defense plan'], ['hedges', 'Hedge alternatives'], ['scenarios', 'Stress scenarios'], ['review-log', 'Review history']]),
  g('watch', 'Watch', 'Ideas & conditions', [['overview', 'Overview'], ['my-list', 'My List'], ['suggestions', 'Suggestions'], ['prospects', 'Prospects'], ['setups', 'Setups'], ['sectors', 'Sectors'], ['discover', 'Discover'], ['alerts', 'Alerts'], ['pullbacks', 'Pullbacks']]),
  g('reposition', 'Reposition', 'Exit · rotate · redeploy', [['rotation', 'Defensive rotation'], ['reentry', 'Re-entry'], ['exits', 'Exit reviews'], ['capital', 'Capital book'], ['comparison', 'Plan comparison'], ['plan-lab', 'Plan lab'], ['event', 'Market events']]),
  g('trade', 'Trade', 'Governed trade reviews', [['desk', 'Scalping desk'], ['options', 'Options'], ['strategies', 'Strategies'], ['journal', 'Journal']]),
  g('intel', 'CIO & research', 'Understand & remember', [['desk', 'CIO desk'], ['questions', 'My questions'], ['research', 'Research'], ['company-files', 'Company files'], ['reports', 'Reports'], ['communications', 'Investment alerts'], ['history', 'Decision history']]),
  g('ops', 'Operations', 'Readiness & recovery', [['health', 'Readiness'], ['jobs', 'Jobs & schedules'], ['data', 'Data quality'], ['incidents', 'Incidents'], ['releases', 'Releases'], ['agents', 'Agents & resources'], ['memory', 'Memory integrity'], ['delivery', 'Delivery audit']], 'PLATFORM'),
]

export const VIEW_COUNT = NAV.reduce((n, x) => n + x.views.length, 0)

// A family root (`/cio`, `/journal`, `/risk`, …) is a registered page — App.tsx routes one path per entry in
// `routes/families.ts` — but it is not one of the eight NAV groups: the two registries answer different questions.
// Resolving it to a NAV group would print a heading the URL does not name and highlight a group the page is not in,
// so the shell gets a display-only group built from the family registry. NAV stays the eight groups it always was;
// ids the two registries share (`portfolio`, `watch`, `ops`) stay NAV's, because the NAV lookup runs first.
const FAMILY_GROUPS: ReadonlyMap<string, NavGroup> = new Map(
  FAMILIES
    .filter(f => f.path !== '/' && !NAV.some(x => x.id === f.id))
    .map(f => [f.path.split('/')[1], {
      id: f.id,
      label: 'Wealth', // the product the shell belongs to; the page itself is named by the view
      tagline: f.decision,
      icon: f.id,
      views: [{ id: f.id, label: f.title }],
    }]),
)

export function groupPath(grp: NavGroup): string { return `/${grp.id}/${grp.views[0].id}` }
export function viewPath(grp: NavGroup, v: NavView): string { return `/${grp.id}/${v.id}` }

/** True for the display-only group `resolve()` builds from the family registry; false for the eight NAV groups. */
export function isFamilyGroup(grp: NavGroup): boolean { return FAMILY_GROUPS.get(grp.id) === grp }

/** Resolve a router pathname (basename already stripped) to the active group and view. */
export function resolve(pathname: string): { group: NavGroup; view: NavView; known: boolean } {
  const [gid, vid] = pathname.replace(/^\/+/, '').split('/')
  const group = NAV.find(x => x.id === gid)
  if (group) {
    const view = group.views.find(v => v.id === vid)
    return { group, view: view ?? group.views[0], known: !vid || !!view }
  }
  // A family root is a page in its own right — App.tsx routes it directly — and it has no sub-views, so it is
  // known whatever follows the segment. Only an unregistered first segment is an unknown address.
  const family = FAMILY_GROUPS.get(gid)
  if (family) return { group: family, view: family.views[0], known: true }
  return { group: NAV[0], view: NAV[0].views[0], known: !gid }
}
