const assert = {
  equal(actual: unknown, expected: unknown) { if (actual !== expected) throw new Error(`${String(actual)} != ${String(expected)}`) },
  match(actual: string, expected: RegExp) { if (!expected.test(actual)) throw new Error(`${actual} does not match ${expected}`) },
}
import { TRADE_TABS, calendarPayload, replayPayload, etMonth, monthLabel, monthShift, serverMoney, serverNumber, storedReplayPath, tabParams, tradeLink, tradeTab } from './tradeInViewModel.ts'
assert.equal(tradeTab(new URLSearchParams()), 'journeys')
for (const [tab] of TRADE_TABS) assert.equal(tradeTab(new URLSearchParams({ tab }), true), tab)
assert.equal(tradeTab(new URLSearchParams('view=classic')), 'classic')
assert.equal(tradeTab(new URLSearchParams('tab=Options')), 'classic')
assert.equal(tradeTab(new URLSearchParams(), true), 'classic')
const original = new URLSearchParams('view=classic&tab=Options&symbol=FIXTURE')
assert.equal(tabParams(original, 'calendar').toString(), 'tab=calendar&symbol=FIXTURE')
assert.equal(original.get('view'), 'classic')
assert.equal(tradeLink('replay', { trade_id: 'rt:fixture/A B' }), '/journal?tab=replay&trade=rt%3Afixture%2FA+B')
assert.equal(monthShift('2031-12', 1), '2032-01')
assert.equal(monthShift('2032-01', -1), '2031-12')
assert.equal(monthShift('invalid', 1), 'invalid')
assert.equal(monthShift('2032-13', 1), '2032-13')
assert.equal(monthLabel('2032-13'), 'Month unavailable')
assert.equal(storedReplayPath('rt:fixture/A B', '1D'), '/api/v2/trade-chart?trade_id=rt%3Afixture%2FA+B&stored_only=1&interval=1D')
assert.equal(monthLabel('2032-02'), 'February 2032')
assert.equal(etMonth(new Date('2032-03-01T02:00:00Z')), '2032-02')
assert.equal(serverNumber(null), '—'); assert.equal(serverNumber(0), '0')
assert.equal(serverMoney(undefined), '—'); assert.equal(serverMoney(Number.NaN), '—')
assert.match(serverMoney(0), /\$0\.00/)
console.log('tradeInViewModel: navigation, explicit ranges and null/zero formatting passed')

assert.equal(calendarPayload({schema:'TradeCalendar@v1',days:[],weeks:[]}), null)
assert.equal(calendarPayload({schema:'wrong',days:[],weeks:[],summary:{},events:[],account_options:[],gaps:[]}), null)
assert.equal(replayPayload({schema:'TradeReplay@v1',bars:[],available_intervals:[]}), null)
assert.equal(replayPayload({data:{schema:'TradeCalendar@v1'}}), null)
