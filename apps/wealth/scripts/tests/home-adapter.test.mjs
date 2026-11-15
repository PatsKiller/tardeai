import test from 'node:test'
import assert from 'node:assert/strict'
import { accountMap, ageLabel, homeToday, overviewModel, state, snapshotModel } from '../../src/pages/home/homeAdapter.ts'
const NOW = Date.parse('2026-11-15T19:00:00Z')
const envelope = data => ({ data, error: null, lastGood: null, lastGoodAgeSeconds: null, spec: { path: '/api/test' } })
test('missing and unzoned source clocks remain age unknown', () => {
  assert.match(ageLabel(null, NOW), /age unknown/)
  assert.match(ageLabel('2026-11-15T18:00:00', NOW), /age unknown/)
  assert.match(ageLabel('2026-11-15T18:00:00Z', NOW), /1.0 h old/)
})
test('nested failure cannot become current through HTTP success', () => {
  assert.equal(state(envelope({ ok: true, data: { ok: false, error: 'missing' } }), x => x, NOW).status, 'UNKNOWN')
})
test('error is visible; invalid cached HTTP-success body is not last good', () => {
  const e = { ...envelope(null), error: 'timed out', lastGood: { data: { ok: false } } }
  const s = state(e, x => x, NOW)
  assert.equal(s.status, 'ERROR')
  assert.equal(s.lastGood, null)
})
test('empty with no clock is unknown; dated empty is honest empty', () => {
  assert.equal(state(envelope({ items: [] }), r => r.items, NOW, r => r.as_of, x => !x.length).status, 'UNKNOWN')
  assert.equal(state(envelope({ items: [], as_of: '2026-11-15T18:00:00Z' }), r => r.items, NOW, r => r.as_of, x => !x.length).status, 'EMPTY')
})
test('overview cannot fall back to legacy total or invent daily profit', () => {
  assert.equal(overviewModel({ total_value: 123 }).value, null)
  const result = overviewModel({ portfolio_total: { value: 0 }, portfolio_aggregate: { accounts: [{ account: 'SYNTHETIC_ACCOUNT', account_label: 'Example retirement', total_usd: 27 }] } })
  assert.equal(result.value, 0)
  assert.doesNotMatch(JSON.stringify(result), /SYNTHETIC_ACCOUNT/)
})
test('stored movers keep unknown separate from zero, and source separate from build', () => {
  const s = snapshotModel({ snapshot: { generated_at: 'build', quotes_as_of: 'quote', moves: [{ symbol: 'TEST', held: true, change_pct: 0 }, { symbol: 'DEMO', held: false }] } }, new Map())
  assert.equal(s.moves[0].change, 0)
  assert.equal(s.moves[1].change, null)
  assert.equal(s.quoteClock, 'quote')
  assert.equal(s.build, 'build')
})
test('raw known account keys are removed from news and review output', () => {
  const key = 'synthetic-account-key'
  const result = homeToday({ overview: envelope({ data: { account_labels: { [key]: 'Example retirement' } } }), snapshot: envelope({ data: { snapshot: { feed: [{ title: key, so_what: key }], moves: [] } } }), priorities: envelope({ data: { items: [{ title: key, why: key }] } }) }, NOW)
  assert.doesNotMatch(JSON.stringify(result.snapshot.data), /synthetic-account-key/)
  assert.doesNotMatch(JSON.stringify(result.priorities.data), /synthetic-account-key/)
})
test('producer stale and greyed verdicts never render current', () => {
  for (const data of [{ stale: true }, { freshness: { stale: true } }, { _product: { status: 'UNKNOWN', greyed: true } }]) assert.equal(state(envelope({ data }), x => x, NOW).status, 'UNKNOWN')
})

test('review queue preserves order, separates category and removes evidence account keys', async () => {
  const { reviewModel } = await import('../../src/pages/home/homeAdapter.ts')
  const q = reviewModel({all_sources_answered:false,any_source_stale:true,items:[{category:'protect',title:'Review secret-key',evidence:{accounts:['secret-key'],account_labels:['Example account'],thesis:'Stored thesis',horizon:'Long term'}},{category:'fix',title:'Technical issue'}],sources:{risk:{status:'PARTIAL',as_of:'2026-11-15T18:00:00Z',as_of_basis:'source',stale:true}}})
  assert.equal(q.items[0].category,'protect'); assert.equal(q.items[1].category,'fix')
  assert.equal(q.items[0].thesis,'Stored thesis');assert.equal(q.items[0].horizon,'Long term')
  assert.doesNotMatch(JSON.stringify(q),/secret-key/)
  assert.equal(q.allAnswered,false);assert.equal(q.sources[0].stale,true)
})
test('market engine refuses missing, stale and more-than-one-hour evidence', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  for(const r of [{state:'evaluated',stale:false},{state:'evaluated',stale:false,as_of:'2026-11-15T17:59:59Z'},{state:'evaluated',stale:true,as_of:'2026-11-15T19:00:00Z'}]) assert.equal(marketState(envelope({data:r}),NOW).status,'UNKNOWN')
  assert.equal(marketState(envelope({data:{state:'evaluated',stale:false,as_of:'2026-11-15T18:00:00Z',tier:'YELLOW',score:0}}),NOW).data.score,0)
})
test('scenario frames and adapted market never expose probability or invented forecast', async () => {
  const { SCENARIOS, marketModel } = await import('../../src/pages/home/homeAdapter.ts')
  assert.equal(SCENARIOS.length,3)
  for(const frame of SCENARIOS) assert.match(frame.availability,/methodology pending/)
  assert.doesNotMatch(JSON.stringify(marketModel({probabilities:{crash:0.8},forward_price:123})),/probabilit|forward_price/)
})
test('news contextual reader uses the actual source_url field and rejects unsafe links', () => {
  const m = snapshotModel({snapshot:{feed:[{source_url:'https://example.com/research'},{source_url:'javascript:alert(1)'}]}},new Map())
  assert.equal(m.feed[0].url,'https://example.com/research');assert.equal(m.feed[1].url,null)
})
