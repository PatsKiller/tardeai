import { locateIn, OFF_RAIL, type NavSection } from './navLocate.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) } }
const RAIL: NavSection[] = [
  { label: 'Trade', hubs: [{ to: '/', label: 'Home', exact: true }, { to: '/portfolio', label: 'Portfolio', exact: true }, { to: '/watch', label: 'Watch' }] },
  { label: 'Ops', hubs: [{ to: '/system', label: 'System', exact: true }, { to: '/system/releases', label: 'Releases & Schedules' }] },
]
const at = (p: string) => { const r = locateIn(p, RAIL); return `${r.section}·${r.page}` }
check('home is home', at('/') === 'Trade·Home')
check('rail hub', at('/portfolio') === 'Trade·Portfolio' && at('/system/releases') === 'Ops·Releases & Schedules')
check('/intelligence is not Home', at('/intelligence') === 'Intel·Intelligence')
check('/portfolio/re-entry under Portfolio section', at('/portfolio/re-entry') === 'Trade·Re-Entry')
check('/watch/intelligence/AAPL stays Watch', at('/watch/intelligence/AAPL') === 'Trade·Watch')
check('/watch-legacy is not Watch or Home', at('/watch-legacy') === 'Trade·Watch (legacy)')
check('unknown path does not claim Home', at('/nonexistent') === 'Command Center·Page')
const routed = ['/strategy', '/agents', '/hermes', '/retirement', '/reports', '/rotation', '/redeploy', '/rec-intel', '/advisory', '/defense']
check('every off-rail hub resolves to itself', routed.every(p => !at(p).endsWith('·Home') && OFF_RAIL.some(s => s.hubs.some(h => h.to === p))))
console.log(`navLocate: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
