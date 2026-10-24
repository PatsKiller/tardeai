// node --experimental-strip-types src/lib/watchListsModel.test.ts
// Watch lists page model (operator 2026-10-23) on the captured fixture (src/fixtures/watchLists.fixture.ts).
declare const process: { exit(code?: number): never }
import { WATCH_LISTS_FIXTURE as FIX } from '../fixtures/watchLists.fixture.ts'
import {
  POSITION_FILTER_KEYS, activeCount, alertLevelsLabel, chipsFor, positionChip, positionQuery, reentryLabel,
  riskRewardCell, roundTripLabel, roundTripPath, toggleOption, unwrapAny, withQuery, type ListRow,
  heldAccountNames, soldByName,
} from './watchListsModel.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const C = unwrapAny<any>(FIX.curation)!
const U = unwrapAny<any>(FIX.universe)!
ok('curation unwraps', C && C.my_watchlist && C.suggests)
ok('universe unwraps', U && Array.isArray(U.items))
ok('unwrap accepts {ok,data}', unwrapAny({ ok: true, data: FIX.curation }) !== null)

// My Watchlist: starred first, every row is yours, never capped.
const mine: ListRow[] = C.my_watchlist.rows
ok('my watchlist has rows', mine.length > 0)
ok('every row is yours', mine.every(r => r.mine))
const firstUnstarred = mine.findIndex(r => !r.starred)
ok('starred first', firstUnstarred === -1 || mine.slice(firstUnstarred).every(r => !r.starred))
eq('the twelve stars are listed', C.my_watchlist.starred, 12)
ok('no row of yours is Expired', mine.every(r => r.lane !== 'expired'))

// Suggests: the top of the same ranking — ascending universe rank, never one of yours, never held.
const sug: ListRow[] = C.suggests.rows
const ranks = sug.map(r => r.universe_rank as number)
ok('suggests ascend by universe rank', ranks.every((v, i) => i === 0 || ranks[i - 1] < v))
const mineSet = new Set(mine.map(r => r.symbol))
ok('suggests never repeat your names', sug.every(r => !mineSet.has(r.symbol) || !r.mine))
ok('suggests never held', sug.every(r => r.position_state !== 'held'))
ok('n within 1..30', C.suggests.n >= 1 && C.suggests.n <= 30)
eq('how explains the five lists', C.how.map((h: any) => h.id), ['my_watchlist', 'suggests', 'prospects', 'full_universe', 'proposals'])

// Full universe, re-entry preset: formerly held first; NAVN is Re-entry / formerly held, never Add-On / ADD.
const navn = U.items.find((r: any) => r.symbol === 'NAVN') as ListRow & { type: string; stance: string }
ok('NAVN present', !!navn)
eq('NAVN type and status', [navn.type, (navn as any).position_status, navn.position_state], ['re_entry', 'formerly_held', 'formerly_held'])
ok('NAVN stance is not ADD', navn.stance !== 'ADD')
eq('NAVN round trip', [navn.last_round_trip!.entry_price, navn.last_round_trip!.exit_price, navn.last_round_trip!.pnl_usd, navn.last_round_trip!.pnl_pct],
  [25.64, 26.02, 189.73, 1.48])
eq('NAVN round trip label', roundTripLabel(navn.last_round_trip), '+1.48% · +$189.73 · 0.36R · Trailing stop')
ok('NAVN path', roundTripPath(navn.last_round_trip).startsWith('10/19 $25.64 → 10/22 $26.02'))
eq('NAVN re-entry alert levels', alertLevelsLabel(navn.reentry), '25.853 / 25.1 / 26.02')
ok('NAVN re-entry label has the zone and the reclaim', /\$24\.80–\$25\.10/.test(reentryLabel(navn.reentry)) && /close > \$26\.02/.test(reentryLabel(navn.reentry)))
eq('NAVN position chip', positionChip(navn)?.label, 'formerly held · sold 10/22')
const firstNever = U.items.findIndex((r: any) => r.position_state !== 'formerly_held')
ok('formerly held first', firstNever === -1 || U.items.slice(firstNever).every((r: any) => r.position_state !== 'formerly_held'))

// One cell for risk / reward / R:R.
eq('risk reward cell', riskRewardCell({ risk_pct: 4.21, reward_pct: 20.24, rr: 4.8 }), '−4.2% / +20.2% · 4.8x')
eq('risk reward cell empty', riskRewardCell(null), '—')

// Filters live in the URL and pass straight to the server.
const sp = new URLSearchParams('tab=opportunities&position=formerly_held&result=won,lost&r_min=0.5&psort=pnl_pct&junk=1')
eq('position query', positionQuery(sp), { position: 'formerly_held', result: 'won,lost', r_min: '0.5', sort: 'pnl_pct' })
eq('active count', activeCount(sp), 3)
eq('toggle adds', toggleOption('won', 'lost'), 'won,lost')
eq('toggle removes', toggleOption('won,lost', 'won'), 'lost')
eq('with query', withQuery('/api/x', { a: '1' }), '/api/x?a=1')
eq('with query empty', withQuery('/api/x', {}), '/api/x')
ok('filter keys cover the operator list', ['position', 'result', 'pnl_usd_min', 'pnl_pct_max', 'exit_cause', 'exited_within', 'reentry', 'reentry_dist_min', 'r_max'].every(k => (POSITION_FILTER_KEYS as readonly string[]).includes(k)))

// Count chips come from server facets with the server's own rule as the tooltip.
const specs = C.my_watchlist.position_filters
ok('every server filter has its rule', Object.values(specs).every((s: any) => typeof s.server === 'string' && s.server.length > 20))
const chips = chipsFor('position', specs.position, U.position_facets)
eq('position chips', chips.map(c => c.opt), ['held', 'formerly_held', 'never_held'])
ok('formerly held chip counts', chips[1].count > 0)

// Which account (operator 2026-10-23: "two SpaceX and two different accounts" / names only, never numbers)
const heldTwo = positionChip({ position_state: 'held', held_accounts: ['schwab_rollover_ira', 'schwab_taxable'] })
eq('held in two accounts', heldTwo?.label, 'held · 2 accounts')
ok('held tooltip names both accounts', !!heldTwo?.tip.includes('Schwab Rollover IRA, Schwab Individual'))
eq('held in one account names it', positionChip({ position_state: 'held', held_accounts: ['schwab_roth'] })?.label, 'held · Schwab Roth IRA')
eq('held account names', heldAccountNames({ held_accounts: ['schwab_taxable'] }), ['Schwab Individual'])
const soldChip = positionChip({ position_state: 'formerly_held', last_sell_at: '2026-10-22T15:00:00Z', last_sell_account: 'schwab_rollover_ira' })
ok('formerly held names the account that sold', !!soldChip?.label.endsWith('· Schwab Rollover IRA'))
eq('sold by falls back to the round trip account', soldByName({ last_round_trip: { account: 'schwab_taxable' } as any }), 'Schwab Individual')
eq('sold by unknown is empty', soldByName({}), '')
ok('no account number in a chip', !/\d{3,}/.test(positionChip({ position_state: 'formerly_held', last_sell_at: null, last_sell_account: '12345678' })!.label.replace(/sold .*?·/, '')))

if (failed) { console.error(`${failed} watchListsModel test(s) failed`); process.exit(1) }
console.log('watchListsModel: ok')
