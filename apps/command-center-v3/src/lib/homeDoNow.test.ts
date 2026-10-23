import {
  doNowFrom, visibleItems, routerPath, positionsFreshness, moversBars, accountRows, cashPct, inMarketHours, money, pct, ageLabel, briefingSummary, parseObservedTime,
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
  numbers: { status: 'OK', unprotected_positions: 8, unprotected_value_usd: 300000, unprotected_basis: 'no stop on record', heat_pct: 0.1, heat_limit_pct: 5, positions_source: 'holdings file via risk_snapshot', as_of: 'x', stale: false },
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
check('50 min old in market hours is STALE', f50.stale && f50.label === 'Positions 50 min old · STALE' && f50.tip.includes('holdings'))
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
check('account rows by NAME; 1D falls back to overview', rows[1].name === 'Schwab Roth IRA' && rows[2].d1 === -1 && rows[2].ytd === null)
check('fallback to today_by_account when performance missing', accountRows(null, { portfolio_value: 1, today_by_account: { a_b: { value: 5, change: 1 } } })[1].name === 'A B')
check('cash pct', Math.abs((cashPct({ total_cash: 823000, portfolio_value: 1255076 }) ?? 0) - 65.57) < 0.01 && cashPct({ portfolio_value: 0, total_cash: 1 }) === null && cashPct({}) === null)
check('formatting', money(-6795, true) === '−$6,795' && money(25097, true) === '+$25,097' && money(null) === '—' && pct(-0.54) === '−0.54%' && ageLabel(3000) === '50 min')
// briefingSummary — /api/v2/command serves {content, generated_at}; never "[object Object]" (site validation 2026-10-22)
const bObj = briefingSummary({ content: 'The portfolio shows   limited exposure.', generated_at: '2026-10-22 16:20' })
check('briefing object → its content', bObj === 'The portfolio shows limited exposure.')
check('briefing never [object Object]', !briefingSummary({ content: 'x' }).includes('[object'))
check('briefing plain string kept', briefingSummary('plain text') === 'plain text')
check('briefing JSON string parsed', briefingSummary('{"content":"from json"}') === 'from json')
check('briefing truncated with ellipsis', briefingSummary('a'.repeat(200)).length === 111 && briefingSummary('a'.repeat(200)).endsWith('…'))
check('briefing empty/null → empty', briefingSummary(null) === '' && briefingSummary({}) === '' && briefingSummary('  ') === '')
// "YYYY-MM-DD HH:MM:SS ET" observation stamps (server format) — Date.parse alone gives NaN (site validation 2026-10-22)
check('ET stamp parsed (EDT)', parseObservedTime('2026-10-22 16:45:03 ET') === Date.parse('2026-10-22T20:45:03Z'))
check('ET stamp parsed (EST)', parseObservedTime('2026-12-01 09:30 ET') === Date.parse('2026-12-01T14:30:00Z'))
check('ISO still parsed', parseObservedTime('2026-10-22T15:10:43+00:00') === Date.parse('2026-10-22T15:10:43Z'))
check('garbage is NaN', Number.isNaN(parseObservedTime('soon')))
const etEnv = { observation: { envelopes: { holdings: { observed_at: '2026-10-22 16:45:03 ET', freshness: { status: 'FRESH' } } } } }
const etF = positionsFreshness(etEnv, Date.parse('2026-10-23T02:06:33Z'))
check('ET-stamped FRESH envelope after hours is not STALE / not age unknown', !etF.stale && !etF.label.includes('unknown'))
const utcEnv = { observation: { envelopes: { holdings: { observed_at: 'bad', freshness: { status: 'FRESH', observed_at_utc: '2026-10-22T20:45:03+00:00' } } } } }
check('observed_at_utc preferred', positionsFreshness(utcEnv, Date.parse('2026-10-22T21:00:00Z')).ageS === 897)
const dup = moversBars({ today_change: -10836, top_movers: [
  { symbol: 'SCHG', day_change: -0.21 }, { symbol: 'SPCX', day_change: -2912.2 }, { symbol: 'V', day_change: 846.27 }, { symbol: 'V', day_change: 5.16 },
  { symbol: 'SPCX', day_change: -8736.6 }, { symbol: 'SCHG', day_change: -3686.4 }] })
check('movers: one bar per symbol', new Set(dup.bars.map(b => b.sym)).size === dup.bars.length && dup.bars.length === 3)
check('movers: per-symbol sum', dup.bars[0].sym === 'SPCX' && dup.bars[0].amount === -11648.8 && dup.bars[1].sym === 'SCHG' && dup.bars[1].amount === -3686.61)
// Operator 2026-10-23 ("two SpaceX and two different accounts"): the Home card example, rows with their account
const op = moversBars({ today_change: 37, top_movers: [
  { symbol: 'SPCX', day_change: 1488, account: 'schwab_rollover_ira', account_label: 'Schwab Rollover IRA' },
  { symbol: 'SCHD', day_change: -850, account: 'schwab_rollover_ira' }, { symbol: 'V', day_change: -752, account: 'schwab_roth' },
  { symbol: 'SPCX', day_change: 507, account: 'schwab_taxable', account_label: 'Schwab Individual' },
  { symbol: 'XLB', day_change: -141, account: 'schwab_rollover_ira' }, { symbol: 'SCHG', day_change: -98, account: 'schwab_rollover_ira' }] })
const sp = op.bars[0]
check('SPCX grouped: one row, 2 accounts, sum +1,995', sp.sym === 'SPCX' && sp.multi && sp.accounts.length === 2 && sp.amount === 1995)
check('SPCX parts keep the account names and amounts', sp.accounts.map(a => `${a.label}:${a.amount}`).join('|') === 'Schwab Rollover IRA:1488|Schwab Individual:507')
check('single-account rows carry their account name', op.bars.find(b => b.sym === 'V')!.accountLabel === 'Schwab Roth IRA' && op.bars.find(b => b.sym === 'SCHD')!.accountLabel === 'Schwab Rollover IRA')
check('footer sums unchanged: shown = sum of groups; rest = day − shown', op.shownSum === 1995 - 850 - 752 - 141 - 98 && op.shownSum === 154 && (op.total! - op.shownSum) === -117)
check('no account number in any label', op.bars.every(b => b.accounts.every(a => !/\d{3,}/.test(a.label))))
console.log(`homeDoNow: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
