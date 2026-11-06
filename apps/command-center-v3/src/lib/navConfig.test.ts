/** Menu redesign nav/v001: nothing is removed. Every route the menu reached before the redesign (the old NavRail
 *  SECTIONS, the Control Plane preview and navLocate OFF_RAIL, snapshotted below at 722900548) is still a page in the
 *  nav table or opens one, and every route App.tsx registers resolves to a menu page instead of "Command Center". */
import { NAV, CONTROL_PLANE_GROUP, locateNav, sectionPages, stripPages, pageHref } from './navConfig.ts'

// No @types/node in this app: reach fs through Node's builtin loader (Node ≥ 22.3) with a local type.
declare const process: { exit(code?: number): never; getBuiltinModule(id: 'node:fs'): { readFileSync(p: URL, enc: 'utf8'): string } }
const readFileSync = process.getBuiltinModule('node:fs').readFileSync
let pass = 0, fail = 0
function check(name: string, cond: boolean, detail = '') { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) } }

/** Snapshot of the pre-redesign rail (NavRail.tsx SECTIONS + CONTROL_PLANE_PREVIEW at 722900548). */
const OLD_RAIL = [
  '/', '/portfolio', '/trading', '/watch', '/portfolio/re-entry', '/risk', '/defense', '/rotation', '/active-trader', '/journal', '/strategy',
  '/cio', '/advisory', '/cio/questions', '/research-intelligence', '/intelligence', '/closed-loop', '/hermes', '/rec-intel', '/reports', '/communications', '/prospectus',
  '/health', '/ops/jobs', '/agents', '/consumption', '/coordination', '/system/broker-access', '/system/releases', '/approvals', '/policy', '/conflicts/rules', '/system/ops-controls', '/system', '/ops/incidents',
  '/control-plane', '/control-plane/system', '/control-plane/agents', '/control-plane/workflows', '/control-plane/research', '/control-plane/data',
  '/control-plane/identity', '/control-plane/notifications', '/control-plane/learning', '/control-plane/maturity', '/control-plane/audit',
]
/** Snapshot of navLocate.ts OFF_RAIL at 722900548 (routed, located, but not on the menu). */
const OLD_OFF_RAIL = ['/portfolio/re-entry', '/strategy', '/retirement', '/redeploy', '/defense', '/watch-legacy', '/intelligence', '/agents', '/hermes', '/reports', '/rotation', '/rec-intel', '/advisory', '/system/schwab-reauth']

const allPages = NAV.flatMap(s => sectionPages(s, true))
const menuRoutes = new Set(allPages.map(p => p.to))

check('35 old rail items + 11 control plane pages snapshotted', OLD_RAIL.length === 46)
for (const to of OLD_RAIL) check(`old rail route ${to} is still a menu page`, menuRoutes.has(to))
for (const to of OLD_OFF_RAIL) {
  const here = locateNav(to)
  check(`off-rail route ${to} resolves to a menu page`, !!here && menuRoutes.has(here.page.to), here ? here.page.to : 'null')
}
check('Retirement and Redeploy are now menu pages', menuRoutes.has('/retirement') && menuRoutes.has('/redeploy'))

// Every route registered in App.tsx (params filled) resolves to a menu page; a redirect's target does.
const app = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
const routes = [...app.matchAll(/<Route path="([^"]+)" element=\{(.*)$/gm)].map(m => ({ path: '/' + m[1], element: m[2] }))
check('App.tsx routes discovered', routes.length >= 60, String(routes.length))
for (const r of routes) {
  if (r.path === '//*') continue // the App shell catch-all, not a page
  const redirect = /<Navigate to="([^"?]+)/.exec(r.element)
  const target = redirect ? redirect[1] : r.path.replace(/:[A-Za-z]+/g, 'x')
  const here = locateNav(target)
  check(`route ${r.path}${redirect ? ` → ${target}` : ''} is reachable from the menu`, !!here && menuRoutes.has(here.page.to), here ? '' : 'unlocated')
}
check('index route is Home · Today', locateNav('/')?.page.label === 'Today')

// Shape rules from the mockup.
check('five sections in order', NAV.map(s => s.label).join(',') === 'Home,Portfolio,Trade,Intel,Ops')
const portfolio = NAV.find(s => s.id === 'portfolio')!
check('Portfolio groups', portfolio.groups.map(g => `${g.label}:${g.pages.map(p => p.label).join('/')}`).join(' | ')
  === 'What I own:Holdings/Retirement | Protect:Risk/Defense | Reposition:Re-Entry/Rotation/Redeploy')
const intel = NAV.find(s => s.id === 'intel')!
check('Intel groups', intel.groups.map(g => g.label).join(',') === 'Desks,Research,Outputs' && sectionPages(intel, false).length === 11)
const ops = NAV.find(s => s.id === 'ops')!
check('Ops: 13 pages + Control Plane preview group', sectionPages(ops, false).length === 13 && sectionPages(ops, true).length === 24)
check('control plane group behind the flag', ops.groups.includes(CONTROL_PLANE_GROUP) && CONTROL_PLANE_GROUP.preview === true)
check('Home: Today / Needs you / My questions', NAV[0].groups[0].pages.map(pageHref).join(' ') === '/ /approvals?tab=waiting /cio/questions')
check('long sections keep the current page in the strip', stripPages(intel, false, intel.groups[1].pages[3]).includes(intel.groups[1].pages[3]))
check('short sections show every page in the strip', stripPages(portfolio, false, null).length === 7)

console.log(`navConfig: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
