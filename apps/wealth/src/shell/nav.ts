// Navigation model, ported from the v02 reference `groups` (docs/wealth/design-reference/
// TradeAI_Wealth_Management_Mockups_v02.html). Same groups, labels, taglines, tab order and ids.
// Dropped: the reference's 'review' group (Design review / Review guide / Whole-site plan / Backend
// contract / Approval register). It is the prototype's approval tooling, not a product page.
//
// URL scheme: /wealth/<group>/<view>. The reference used #group/view hashes; the lead's router
// (App.tsx, routes/) maps these paths to pages. Unknown group → home; unknown view → the group's first.

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
  g('trade', 'Trade', 'Governed trade reviews', [['desk', 'Trade desk'], ['active', 'Active positions'], ['options', 'Options'], ['strategies', 'Strategies'], ['journal', 'Journal']]),
  g('intel', 'CIO & research', 'Understand & remember', [['desk', 'CIO desk'], ['questions', 'My questions'], ['research', 'Research'], ['company-files', 'Company files'], ['reports', 'Reports'], ['communications', 'Investment alerts'], ['history', 'Decision history']]),
  g('ops', 'Operations', 'Readiness & recovery', [['health', 'Readiness'], ['jobs', 'Jobs & schedules'], ['data', 'Data quality'], ['incidents', 'Incidents'], ['releases', 'Releases'], ['agents', 'Agents & resources'], ['memory', 'Memory integrity'], ['delivery', 'Delivery audit']], 'PLATFORM'),
]

export const VIEW_COUNT = NAV.reduce((n, x) => n + x.views.length, 0)

export function groupPath(grp: NavGroup): string { return `/${grp.id}/${grp.views[0].id}` }
export function viewPath(grp: NavGroup, v: NavView): string { return `/${grp.id}/${v.id}` }

/** Resolve a router pathname (basename already stripped) to the active group and view. */
export function resolve(pathname: string): { group: NavGroup; view: NavView; known: boolean } {
  const [gid, vid] = pathname.replace(/^\/+/, '').split('/')
  const group = NAV.find(x => x.id === gid)
  if (!group) return { group: NAV[0], view: NAV[0].views[0], known: !gid }
  const view = group.views.find(v => v.id === vid)
  return { group, view: view ?? group.views[0], known: !vid || !!view }
}
