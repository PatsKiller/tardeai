/** Pure replay transport: preserves recorded identity, original fill clocks and explicit zero/null values. */
import { buildReplayTrade } from './replayTrade.ts'
const equal = (actual: unknown, expected: unknown) => { if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${JSON.stringify(actual)} != ${JSON.stringify(expected)}`) }
const row = { symbol: 'FIXTURE', trade_id: 'rt:fixture:one', trade_key: 'fixture-key', account: 'fixture-account', entry_date: '2032-04-09', exit_date: '2032-04-12', entry_time: '2032-04-09T14:17:12Z', exit_time: '2032-04-12T17:41:08Z', entry_price: 0, exit_price: null, sell_price: 0 }
const before = JSON.stringify(row), out = buildReplayTrade(row)
equal([out.trade_id, out.trade_key, out.account], [row.trade_id, row.trade_key, row.account])
equal([out.entry_time, out.exit_time], [row.entry_time, row.exit_time])
equal([out.entry_price, out.exit_price], [0, 0])
equal(JSON.stringify(row), before)
const missing = buildReplayTrade({ symbol: 'FIXTURE' })
equal([missing.entry_price, missing.exit_price, missing.entry_time, missing.exit_time], [undefined, undefined, null, null])
equal(missing.trade_id, undefined)
console.log('replayTrade: recorded identity, original clocks and missing facts preserved')
