import { locate } from './navLocate.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) } }
const at = (p: string, s = '', prefer?: 'home' | 'intel' | 'ops') => { const r = locate(p, s, prefer); return `${r.section}·${r.page}` }
check('home is Home · Today', at('/') === 'Home·Today')
check('holdings', at('/portfolio') === 'Portfolio·Holdings')
check('releases', at('/system/releases') === 'Ops·Releases & Schedules')
check('/intelligence is not Home', at('/intelligence') === 'Intel·Intelligence')
check('/portfolio/re-entry is Re-Entry, not Holdings', at('/portfolio/re-entry') === 'Portfolio·Re-Entry')
check('/portfolio/re-entry/classic stays Re-Entry', at('/portfolio/re-entry/classic') === 'Portfolio·Re-Entry')
check('/watch/intelligence/AAPL stays Watch', at('/watch/intelligence/AAPL') === 'Trade·Watch')
check('/watch/discovery shows Watch', at('/watch/discovery') === 'Trade·Watch')
check('/watch-legacy shows Watch', at('/watch-legacy') === 'Trade·Watch')
check('/system/schwab-reauth shows System', at('/system/schwab-reauth') === 'Ops·System')
check('unknown path does not claim Home', at('/nonexistent') === 'Command Center·Page')
check('Risk/Defense/Re-Entry/Rotation moved under Portfolio', ['/risk', '/defense', '/rotation', '/portfolio/re-entry'].every(p => at(p).startsWith('Portfolio·')))
check('Retirement and Redeploy on the menu under Portfolio', at('/retirement') === 'Portfolio·Retirement' && at('/redeploy') === 'Portfolio·Redeploy')
check('/approvals defaults to Ops', at('/approvals') === 'Ops·Approvals')
check('/approvals?tab=waiting is Home · Needs you', at('/approvals', '?tab=waiting') === 'Home·Needs you')
check('/approvals from Ops stays Ops even on ?tab=waiting', at('/approvals', '?tab=waiting', 'ops') === 'Ops·Approvals')
check('/cio/questions defaults to Intel', at('/cio/questions') === 'Intel·My questions')
check('/cio/questions from Home stays Home', at('/cio/questions/abc', '', 'home') === 'Home·My questions')
check('/cio is CIO Desk, exact', at('/cio') === 'Intel·CIO Desk')
check('control plane page', at('/control-plane/audit') === 'Ops·CP · Audit')
console.log(`navLocate: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
