import {
  doNowFrom, visibleItems, routerPath, positionsFreshness, moversBars, accountRows, cashPct, inMarketHours, money, pct, ageLabel,
} from './homeDoNow.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const now = Date.parse('2026-10-22T15:00:00Z') // 11:00 ET, Thursday — market hours
const it = (id: string, category: string, severity: string, m: number | null = null) => ({
  id, category, severity, title: id, why: 'w', action: { label: 'Go', where: '/v3/risk?symbol=X' }, money_at_risk_usd: m,
  money_basis: m ? 'market value with no stop' : null, sources: ['risk'], since: null,
})
const ok = {
  schema: 'HomeDoNow@v1', as_of: '2026-10-22T14:59:30Z', all_sources_answered: true,
  sources: { risk: { status: 'OK', as_of: '2026-10-22T14:59:00Z', as_of_basis: 'risk_snapshot.computed_at', age_s: 60, stale: false },
    desk_truth: { status: 'NO_RECEIPT', as_of_basis: 'no receipt', stale: false } },
  items: [it('stop:SPCX', 'protect', 'P1', 116000), ...Array.from({ length: 9 }, (_, i) => it(`fix${i}`, 'fix', 'P2')), it('d', 'decide', 'P2'), it('junk', 'other', 'P9')],
  rolled_up: { raw_items: 20, after_dedupe: 11, inbox_total: 135, needs_action_total: 18 },
  numbers: { status: 'OK', unprotected_positions: 8, unprotected_value_usd: 300000, unprotected_basis: 'no stop on record', heat_pct: 0.1, heat_limit_pct: 5, positions_source: 'holdings.json via risk_snapshot', as_of: 'x', stale: false },
}
const m = doNowFrom(ok, { nowMs: now })
check('ITEMS; junk category/severity dropped; server order kept', m.state === 'ITEMS' && m.items.length === 11 && m.items[0].id === 'stop:SPCX')
check('counts per tab', m.counts.all === 11 && m.counts.protect === 1 && m.counts.fix === 9 && m.counts.decide === 1)
check('where made router-relative', m.items[0].where === '/risk?symbol=X')
check('NO_RECEIPT is answered, not unavailable', m.unavailableSources.length === 0 && m.allSourcesAnswered)
check('rolled-up totals carried', m.rolledUp.inboxTotal === 135 && m.rolledUp.afterDedupe === 11)
check('numbers carried with basis', m.numbers.available && m.numbers.unprotected === 8 && m.numbers.heatPct === 0.1 && m.numbers.unprotectedBasis === 'no stop on record')
const top = visibleItems(m, 'all', false)
check('top 7 by default', top.shown.length === 7 && top.total === 11)
check('show all', visibleItems(m, 'all', true).shown.length === 11)
check('tab filter', visibleItems(m, 'fix', false).total === 9 && visibleItems(m, 'protect', false).shown[0].id === 'stop:SPCX')
check('empty + all answered = CLEAR', doNowFrom({ ...ok, items: [] }, { nowMs: now }).state === 'CLEAR')
const partial = doNowFrom({ ...ok, items: [], all_sources_answered: false, sources: { risk: { status: 'UNAVAILABLE', error: 'x' } } }, { nowMs: now })
check('empty with a source down is never CLEAR', partial.state === 'UNAVAILABLE' && partial.unavailableSources[0] === 'risk')
check('error without payload = UNAVAILABLE', doNowFrom(null, { error: 'HTTP 502' }).state === 'UNAVAILABLE')
check('loading', doNowFrom(null, { loading: true }).state === 'LOADING')
check('failed refresh keeps items as STALE', doNowFrom(ok, { error: 'timeout', nowMs: now }).state === 'STALE')
check('old answer is STALE', doNowFrom({ ...ok, as_of: '2026-10-22T14:00:00Z' }, { nowMs: now }).state === 'STALE')
check('wrong schema is UNAVAILABLE', doNowFrom({ ...ok, schema: 'NeedsAction@v1' }).state === 'UNAVAILABLE')
check('numbers unavailable never zero', doNowFrom({ ...ok, numbers: { status: 'UNAVAILABLE' } }).numbers.unprotected === null)
check('routerPath', routerPath('/v3/communications') === '/communications' && routerPath('/v3') === '/' && routerPath('https://x') === '/' && routerPath('//evil') === '/')

// positions freshness
const ov = (observed: string | null, status = 'FRESH') => ({ observation: { envelopes: { holdings: { observed_at: observed, freshness: { status } } } } })
check('market hours detection', inMarketHours(now) && !inMarketHours(Date.parse('2026-10-24T15:00:00Z')) && !inMarketHours(Date.parse('2026-10-22T21:00:00Z')))
const f50 = positionsFreshness(ov('2026-10-22T14:10:00Z'), now)
check('50 min old in market hours is STALE', f50.stale && f50.label === 'Positions 50 min old · STALE' && f50.tip.includes('holdings.json'))
check('10 min old is fresh', !positionsFreshness(ov('2026-10-22T14:50:00Z'), now).stale)
check('server STALE wins', positionsFreshness(ov('2026-10-22T14:55:00Z', 'STALE'), now).stale)
check('no observation time is STALE', positionsFreshness({}, now).stale && positionsFreshness({}, now).label.includes('age unknown'))
check('after hours, 50 min is not STALE', !positionsFreshness(ov('2026-10-22T21:00:00Z'), Date.parse('2026-10-22T21:50:00Z')).stale)

// movers, accounts, cash
const mv = moversBars({ today_change: -6795, top_movers: [{ symbol: 'V', day_change: 343 }, { symbol: 'SPCX', day_change: -6576 }, { symbol: 'Z', day_change: 0 }, { symbol: 'SCHD', day_change: 1844 }] })
check('movers sorted by absolute $; zero dropped; widths relative', mv.bars.map(b => b.sym).join(',') === 'SPCX,SCHD,V' && mv.bars[0].widthPct === 100 && mv.bars[2].widthPct === 5)
check('movers sum + total for the rest-of-book line', mv.shownSum === -6576 + 1844 + 343 && mv.total === -6795)
const perf = { current_value: 1255076, periods: { '1D': { change: -6795 }, YTD: { change: 30000, display_change: 25097, nav_is_not_market_only: true } },
  accounts: { schwab_roth: { current_value: 54013, periods: { '1D': { change: 341 }, YTD: { change: 1672 } } }, moomoo_live: { current_value: 529, periods: {} } } }
const rows = accountRows(perf, { today_by_account: { moomoo_live: { change: -1 } } })
check('all-accounts row prefers display_change (ex-transfers) and flags ≈', rows[0].ytd === 25097 && rows[0].ytdApprox && rows[0].d1 === -6795)
check('account rows; 1D falls back to overview', rows[1].name === 'Schwab Roth' && rows[2].d1 === -1 && rows[2].ytd === null)
check('fallback to today_by_account when performance missing', accountRows(null, { portfolio_value: 1, today_by_account: { a_b: { value: 5, change: 1 } } })[1].name === 'A B')
check('cash pct', Math.abs((cashPct({ total_cash: 823000, portfolio_value: 1255076 }) ?? 0) - 65.57) < 0.01 && cashPct({ portfolio_value: 0, total_cash: 1 }) === null && cashPct({}) === null)
check('formatting', money(-6795, true) === '−$6,795' && money(25097, true) === '+$25,097' && money(null) === '—' && pct(-0.54) === '−0.54%' && ageLabel(3000) === '50 min')
console.log(`homeDoNow: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
