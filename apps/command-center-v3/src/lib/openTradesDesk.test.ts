// Pure-logic tests for openTradesDesk.ts (Open Trades protect-first desk, 2026-10-22).
//   node --experimental-strip-types src/lib/openTradesDesk.test.ts
import { ageText, buildDeskModel, filterRows, money, sortRows, stopHistory, toDeskRow } from './openTradesDesk.ts'
import { OPEN_TRADES_FIXTURE } from './openTradesDesk.fixture.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('openTradesDesk')
const data = OPEN_TRADES_FIXTURE.intelligence.data
const m = buildDeskModel(data)

check('write-off SRNE is out of the table', !m.rows.some(r => r.sym === 'SRNE') && m.writeOffs.map(r => r.sym).join() === 'SRNE')
check('headline excludes the write-off', m.headline.positions === 23 && m.headline.writeOffCount === 1)
check('headline unrealized = served total (write-off excluded)', Math.abs((m.headline.unrealized ?? 0) - data.summary.total_unrealized_pnl) < 0.01)
check('small positions folded into the drawer', m.small.length === 13 && !m.rows.some(r => r.small))
check('table keeps the 10 larger positions', m.rows.length === 10)
check('protect-first is largest dollar exposure first', m.protect.map(r => r.sym).slice(0, 3).join() === 'SCHD,SPCX,SCHG')
check('protect-first only rows with no working stop', m.protect.every(r => r.stopState === 'none'))
check('mutual fund is not "no working stop"', m.rows.find(r => r.sym === 'AMANX')?.stopState === 'na')
check('fractional moomoo NVDA is n/a', m.small.find(r => r.sym === 'NVDA')?.stopState === 'na' || m.rows.find(r => r.sym === 'NVDA')?.stopState === 'na')
const v = m.rows.find(r => r.sym === 'V' && r.account === 'schwab_roth')!
check('working stop text from the live mark', v.stopState === 'ok' && /working \$399\.82 · 3\.1% away/.test(v.stopText))
// XLB read 1.5% from its stop at the stale 07:30 price; at the live mark it is 2.2% away (audit 2026-10-22)
check('XLB proximity from the live mark', m.rows.find(r => r.sym === 'XLB')?.stopState === 'ok' && /2\.2% away/.test(m.rows.find(r => r.sym === 'XLB')?.stopText ?? ''))
check('near when the served flag says so', toDeskRow({ symbol: 'Q', shares: 5, protection_state: 'protected', stop_price: 9.9, stop_distance_pct: 1, protection: { stop_near: true } }).stopState === 'near')
const dell = m.rows.find(r => r.sym === 'DELL')!
check('paper row badged', dell.paper && dell.tags.includes('paper') && dell.accountLabel === 'Alpaca Paper')
check('account label from broker_accounts', v.accountLabel === 'Schwab Roth IRA')
check('stale mark keeps its age, day move hidden', m.rows.find(r => r.sym === 'AMANX')?.markStale === true && m.rows.find(r => r.sym === 'AMANX')?.todayPct === null)
check('filter unprot', filterRows(m.rows, 'unprot').every(r => r.stopState === 'none'))
check('filter paper', filterRows(m.rows, 'paper').map(r => r.sym).join() === 'DELL')
check('filter by account', filterRows(m.rows, 'all', 'schwab_taxable').every(r => r.account === 'schwab_taxable'))
check('sort by stop puts unprotected first', sortRows(m.rows, 'stop')[0].stopState === 'none')
check('sort by P/L worst first', (sortRows(m.rows, 'pl')[0].pl ?? 0) <= (sortRows(m.rows, 'pl')[1].pl ?? 0))
check('stop history names the broker order', stopHistory(v.raw)[0].startsWith('Broker stop $399.82 × 130'))
check('stop history partial coverage', stopHistory(v.raw).some(l => l.startsWith('Covers 130 of 130.4985')))
check('stop history fallback', stopHistory({})[0] === 'No stop on record')
check('money signed', money(-870.4, { signed: true }) === '−$870' && money(13539, { signed: true }) === '+$13,539')
check('age text', ageText(0.2) === '12 min' && ageText(139.5) === '6 d' && ageText(null) === 'age unknown')
check('unknown basis shows as pending, not zero', toDeskRow({ symbol: 'X', shares: 1, current_price: 5, unrealized_pnl: null }).pl === null)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
