import { blockingReasons, cardRail, cycleHeaderSort, ladderGeometry, levelPercent, rowMarketFacts, rowZone } from './watchRecordCardModel.ts'
import { positionQuery, activeCount } from './watchListsModel.ts'
import type { ListRow } from './watchListsModel.ts'
let count = 0
function eq(label: string, actual: unknown, expected: unknown) { count++; if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${label}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`) }
const row = { symbol: 'AAA', price: 10, price_as_of: '2026-10-23T19:45:00Z', lane: 'forming', conviction: 80, conflicts: [], next_action: { kind: 'none' }, levels_ref: { support_ref: 9, resistance_ref: 11, entry_low_ref: 9.5, entry_high_ref: 10.5 } } as unknown as ListRow
eq('header descending', cycleHeaderSort(null, 'conviction'), 'conviction_desc')
eq('header ascending', cycleHeaderSort('conviction_desc', 'conviction'), 'conviction_asc')
eq('header default', cycleHeaderSort('conviction_asc', 'conviction'), '')
eq('setup toggle on/off', [cycleHeaderSort(null, 'setup'), cycleHeaderSort('setup', 'setup')], ['setup', ''])
eq('URL carries exact server query', positionQuery(new URLSearchParams('conv=70&stance=RE-ENTER,WATCH&stage=reentry,blocked&psort=conviction_asc&position=formerly_held')),
  { conv: '70', stance: 'RE-ENTER,WATCH', stage: 'reentry,blocked', position: 'formerly_held', sort: 'conviction_asc' })
eq('all groups counted', activeCount(new URLSearchParams('conv=70&stance=WATCH&stage=forming')), 3)
eq('zone only existing paired references', rowZone(row), [9.5, 10.5])
eq('missing pair not invented', rowZone({ ...row, levels_ref: {} } as ListRow), [null, null])
eq('ladder needs both ordered references', ladderGeometry(null, 11, 10, [9, 10]), null)
eq('inverted references refuse scale', ladderGeometry(11, 9, 10, [9, 10]), null)
eq('clamps without fabricating endpoints', ladderGeometry(9, 11, 50, [0.01, 99]), { price: 100, zone: [0, 100] })
eq('missing price has no marker', ladderGeometry(9, 11, null, [9, 10])?.price, null)
eq('missing zone not invented', ladderGeometry(9, 11, 10, [null, 10])?.zone, null)
eq('percent source values', [levelPercent(9, 10), levelPercent(11, 10), levelPercent(10, 10)], ['−10.0%', '+10.0%', '0.0%'])
eq('no divide by missing/zero', [levelPercent(9, null), levelPercent(9, 0)], ['—', '—'])
const b = { ...row, conflicts: [{ kind: 'stance', summary: 'Another disagreement' }, { kind: 'trade_ai_block', summary: 'Deterministic check failed' }] } as ListRow
eq('one highest priority callout, other reasons retained', blockingReasons(b), ['Deterministic check failed', 'Another disagreement'])
eq('conflict rail', cardRail(b), 'breach')
eq('ready rail only server actionable', cardRail({ ...row, lane: 'actionable' }), 'favorable')
eq('high score alone grants no readiness', cardRail(row), 'neutral')
const original = rowMarketFacts(row)
eq('fallback preserves original observation', original.price.as_of, row.price_as_of)
eq('fallback does not invent quote provider/freshness', [original.price.source, original.price.freshness], [null, 'UNKNOWN'])
const canon = { ...row, market_facts: original }
eq('canonical fact object retained', rowMarketFacts(canon) === original, true)
const historyOnly = { ...row, lane: 'actionable', trade_ai_state: null,
  next_action: { kind: 'propose', label: 'Propose', reason: 'Recorded view agrees' },
  conflicts: [{ kind: 'cio_record_conflict', summary: 'Prior disagreement', resolved: true,
    a: { value: 'WATCH', source: 'stored CIO', at: null }, b: { value: 'RE_ENTER', source: 'prior review', at: null } }],
} as ListRow
eq('resolved history does not block a current proposal', blockingReasons(historyOnly), [])
eq('resolved history does not show a breach rail', cardRail(historyOnly), 'favorable')
eq('a malformed resolved flag stays blocking', blockingReasons({ ...historyOnly,
  conflicts: [{ ...historyOnly.conflicts[0], resolved: 'false' as unknown as boolean }],
}), ['Prior disagreement'])
eq('open disagreement remains blocking', blockingReasons({ ...historyOnly,
  conflicts: [...historyOnly.conflicts, { ...historyOnly.conflicts[0], summary: 'Current disagreement', resolved: false }],
}), ['Current disagreement'])
console.log(`watchRecordCardModel: ${count} assertions passed`)
