const assert = {
  equal(actual: unknown, expected: unknown) { if (actual !== expected) throw new Error(`${String(actual)} != ${String(expected)}`) },
  match(actual: string, expected: RegExp) { if (!expected.test(actual)) throw new Error(`${actual} does not match ${expected}`) },
}
import { TRADE_TABS, calendarPayload, coverageReason, replayPayload, replayPriceFormat, responseReason, etMonth, monthLabel, monthShift, serverMoney, serverNumber, storedReplayPath, tabParams, tradeLink, tradeTab } from './tradeInViewModel.ts'
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

assert.equal(coverageReason({status:'COMPLETE',reasons:[],missing_sources:[]}), 'Source coverage: complete (server declaration)')
assert.equal(coverageReason({status:'PARTIAL',missing_sources:['fixture-ledger']}), 'fixture-ledger')

assert.equal(responseReason({data:{reason:'explicit month required'}}), 'explicit month required')
assert.equal(responseReason({error:{unsafe:'object'}}), null)
const emptyReplay = {schema:'TradeReplay@v1',kind:'none',bars:[],markers:[],available_intervals:[],stats:{max_gain_pct:null,max_drawdown_pct:null,metrics_basis:'no stored bars',exit_label:'Unknown',exit_basis:'No stored exit evidence',exit_kind:'unknown',coach_note:null},source:{stored_only:true},gaps:[]}
assert.equal(replayPayload(emptyReplay), emptyReplay)
assert.equal(replayPayload({...emptyReplay,source:{stored_only:false}}), null)
assert.equal(replayPayload({...emptyReplay,kind:'candles',bars:[{time:'2032-04-09',close:19}]}), null)
assert.equal(replayPayload({...emptyReplay,kind:'closes',bars:[{time:'2032-04-09',close:19}]} )?.kind, 'closes')
assert.equal(replayPayload({...emptyReplay,kind:'closes',bars:[{time:'2032-04-09',close:0}]}), null)

assert.equal(replayPriceFormat([0.0042,0.0043]).precision, 4)
assert.equal(replayPriceFormat([4.2e-7]).precision, 8)
assert.equal(replayPriceFormat([150.125]).precision, 3)
assert.equal(replayPriceFormat([null,undefined,Number.NaN]).precision, 2)

assert.equal(replayPayload({...emptyReplay,stats:{...emptyReplay.stats,coach_note:{text:'unsupported object'}}}), null)
