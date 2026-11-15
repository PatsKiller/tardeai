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
test('market engine honours explicit producer/product verdict and keeps its source/build clocks separate', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  for(const r of [{state:'evaluated',stale:false},{state:'evaluated',stale:false,as_of:'2026-11-15T18:00:00Z'},{state:'evaluated',stale:true,as_of:'2026-11-15T19:00:00Z',_product:{status:'OK'}}]) assert.equal(marketState(envelope({data:r}),NOW).status,'UNKNOWN')
  const s=marketState(envelope({data:{state:'evaluated',stale:false,as_of:'2026-11-15T17:59:57Z',generated_at:'2026-11-15T19:00:00Z',stale_after_hours:1,_product:{status:'OK'},tier:'YELLOW',score:0}}),NOW)
  assert.equal(s.status,'OK');assert.equal(s.data.score,0);assert.equal(s.data.built,'2026-11-15T19:00:00Z');assert.ok(s.ageHours>1)
  assert.match(marketState(envelope({ok:false,error:'Stored projection missing'}),NOW).reason,/Stored projection missing/)
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

test('R1 ordinary uppercase words and numeric prose are preserved; genuine identifier shapes are withheld', async()=>{
 const {safeText}=await import('../../src/pages/home/homeAdapter.ts')
 assert.equal(safeText('QUARTERLY DIVIDEND DECLARED 12345678'),'QUARTERLY DIVIDEND DECLARED 12345678')
 assert.equal(safeText('Z123456789'),'[account withheld]')
 assert.equal(safeText('synthetic-key',new Map([['synthetic-key','Example account']])),'Example account')
})
test('R2 scanner watch:true maps to Watch without inventing scope for unmarked rows',async()=>{
 const {marketMoversModel}=await import('../../src/pages/home/homeAdapter.ts')
 const m=marketMoversModel({signals:{sample:{rows:[{symbol:'HELD',held:true},{symbol:'WATCH',watch:true},{symbol:'UNKNOWN'}]}}})
 assert.deepEqual(m.map(x=>x.held),[true,false,null])
})
test('R3 stored CIO summary object text and its own source clock survive; mixed-run text supersedes it',()=>{
 const m=snapshotModel({snapshot:{cio_brief:{summary:{text:'Stored historical summary',source:'llm'},as_of:'2026-11-01T01:00:00Z'},quotes_as_of:'different-quote-clock'}},new Map())
 assert.equal(m.brief,'Stored historical summary');assert.equal(m.briefAt,'2026-11-01T01:00:00Z');assert.equal(m.briefSource,'llm')
 assert.equal(snapshotModel({snapshot:{cio_brief:{summary:{text:'Must not display'},run:{same_run:false,text:'Brief pieces disagree'}}}},new Map()).brief,'Brief pieces disagree')
})
test('R4 producer week.events, ET event time, window and no-feed statement are retained',()=>{
 const m=snapshotModel({snapshot:{week_ahead:{from:'2026-11-15',to:'2026-11-23',fed_speakers:'no feed — not listed',events:[{date:'2026-11-18',label:'Synthetic event',time_et:'14:00',kind:'macro'}]}}},new Map())
 assert.equal(m.week[0].title,'Synthetic event');assert.equal(m.week[0].time,'14:00');assert.equal(m.weekFrom,'2026-11-15');assert.equal(m.fedSpeakers,'no feed — not listed')
})
test('S1/S2 macro and extended prints retain separate price, reference and source time, with no invented comparable change',()=>{
 const m=snapshotModel({snapshot:{moves:[{symbol:'TEST',price:10,change_pct:1,extended:{state:'level_only',session_label:'After hours',price:11,change_pct:99,printed_at:'2026-11-15T18:00:00Z',reference_date:'2026-11-13'}}],macro:{headlines:[{title:'Synthetic macro',url:'https://example.org/macro'}],futures:{status:'available',quotes:[{label:'Synthetic index',level:123,change_pct:99,level_only:true,printed_at:'2026-11-15T18:01:00Z'}]},now:{overseas:{label:'No direct overseas feed'}}}}},new Map())
 assert.equal(m.moves[0].price,10);assert.equal(m.moves[0].ext.price,11);assert.equal(m.moves[0].ext.change,null)
 assert.equal(m.moves[0].ext.at,'2026-11-15T18:00:00Z');assert.equal(m.macro.quotes[0].change,null);assert.equal(m.macro.headlines[0].url,'https://example.org/macro')
})
test('S3/S4 actual note.topic and account position times are used; raw account key never becomes a heading',async()=>{
 const {cioContextModel}=await import('../../src/pages/home/homeAdapter.ts')
 const labels=new Map([['synthetic-key','Example account']])
 const c=cioContextModel({advisory_only:true,advice:{ok:true},card:{posture:{value:'Stored posture',as_of:'2026-11-01T01:00:00Z'}},notes:[{topic:'Comparison',text:'synthetic-key',as_of:'2026-11-02T01:00:00Z'}]},labels)
 assert.equal(c.notes[0].title,'Comparison');assert.equal(c.notes[0].text,'Example account')
 assert.equal(c.facts[0].at,'2026-11-01T01:00:00Z')
 assert.equal(cioContextModel({advice:{ok:true},card:{posture:{value:'Hidden'}}},labels).facts.length,0)
 const o=overviewModel({data_as_of:'2026-11-01',data_as_of_account:'synthetic-key',account_labels:{'synthetic-key':'Example account'},portfolio_aggregate:{accounts:[{account:'synthetic-key',total_value:27,position_observation_time:'2026-11-01T01:00:00Z'}]}})
 assert.equal(o.accounts[0].value,27);assert.equal(o.accounts[0].source,'2026-11-01T01:00:00Z');assert.equal(o.oldestAccount,'Example account');assert.doesNotMatch(JSON.stringify(o),/synthetic-key/)
})
test('R5/S5 rendered source labels distinguish deterministic context and CIO prose, using an existing hero class',async()=>{
 const fs=await import('node:fs')
 const page=fs.readFileSync(new URL('../../src/pages/home/HomeTodayPage.tsx',import.meta.url),'utf8')
 assert.match(page,/Desk context built from stored numbers/);assert.doesNotMatch(page,/CIO interpretation:|className="page-title"/)
 assert.match(page,/className="hero"/)
})
test('R-a served stale product renders as dated last-known, never as current', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  // Exact serving-layer shape: product_route._mark_product_stale keeps the tier (operator 13 Nov 2026 rule).
  const stale = { state: 'stale', stale: true, tier: 'RED', score: -18.5, mode: 'Risk-off',
    as_of: '2026-11-15T16:00:00Z', generated_at: '2026-11-15T16:00:04Z',
    product_stale: { status: 'STALE', greyed: false, age_s: 10800, as_of: '2026-11-15T16:00:00Z', reason: 'stale: age 10800s past stale_after 9000s' },
    _product: { status: 'STALE', greyed: false, age_s: 10800, reason: 'stale: age 10800s past stale_after 9000s' } }
  const s = marketState(envelope({ data: stale }), NOW)
  assert.equal(s.status, 'UNKNOWN')
  assert.equal(s.data, null)
  assert.ok(s.lastGood, 'the served assessment is last-known, not hidden')
  assert.equal(s.lastGood.tier, 'RED'); assert.equal(s.lastGood.score, -18.5); assert.equal(s.lastGood.mode, 'Risk-off')
  assert.equal(s.lastGood.asOf, '2026-11-15T16:00:00Z')
  assert.equal(s.lastGoodAgeSeconds, 10800)
  assert.match(s.reason, /10800s past stale_after 9000s/)
  assert.match(s.reason, /not current/i)
  assert.equal(s.lastGood.reported.greyed, false)
})
test('R-a greyed last-good and a product_stale-less _product reason are carried and labelled', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  const g = marketState(envelope({ data: { state: 'stale', stale: true, tier: 'AMBER', score: 4, mode: 'Neutral', as_of: '2026-11-15T15:00:00Z', _product: { status: 'UNKNOWN', greyed: true, reason: 'past hard expiry 14400s; last good' } } }), NOW)
  assert.equal(g.status, 'UNKNOWN'); assert.equal(g.lastGood.tier, 'AMBER')
  assert.match(g.reason, /greyed/); assert.match(g.reason, /past hard expiry 14400s/)
})
test('R-a a not-current body with no served tier or no producer verdict is not dressed up as last-known', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  const noTier = marketState(envelope({ data: { state: 'evaluated', stale: true, as_of: '2026-11-15T16:00:00Z', _product: { status: 'STALE' } } }), NOW)
  assert.equal(noTier.lastGood, null); assert.match(noTier.reason, /required/)
  const noVerdict = marketState(envelope({ data: { state: 'stale', stale: true, tier: 'RED', as_of: '2026-11-15T16:00:00Z', _product: { status: 'OK' } } }), NOW)
  assert.equal(noVerdict.lastGood, null)
  const unzoned = marketState(envelope({ data: { state: 'stale', stale: true, tier: 'RED', as_of: '2026-11-15T16:00:00', product_stale: { status: 'STALE', reason: 'stale' } } }), NOW)
  assert.equal(unzoned.lastGood.tier, 'RED'); assert.equal(unzoned.lastGoodAgeSeconds, null)
  assert.match(unzoned.reason, /not current/i)
})
test('R-a a current product keeps its OK path: no last-known, no stale wording', async () => {
  const { marketState } = await import('../../src/pages/home/homeAdapter.ts')
  const ok = marketState(envelope({ data: { state: 'evaluated', stale: false, tier: 'GREEN', score: 3, mode: 'Risk-on', as_of: '2026-11-15T18:00:00Z', generated_at: '2026-11-15T18:00:01Z', _product: { status: 'OK' } } }), NOW)
  assert.equal(ok.status, 'OK'); assert.equal(ok.lastGood, null); assert.doesNotMatch(ok.reason, /not current|last stored/i)
})
test('R-a both Home market panels date the last-known block and drop the current-assessment wording', async () => {
  const fs = await import('node:fs')
  for (const f of ['HomeNeedsPage.tsx', 'HomeOutlookPage.tsx']) {
    const src = fs.readFileSync(new URL(`../../src/pages/home/${f}`, import.meta.url), 'utf8')
    assert.match(src, /Last stored assessment · not current/)
    assert.match(src, /lastGood/)
    assert.match(src, /ageLabel\(/)
  }
  assert.doesNotMatch(fs.readFileSync(new URL('../../src/pages/home/HomeNeedsPage.tsx', import.meta.url), 'utf8'), /sub="Current stored nowcast/)
  assert.doesNotMatch(fs.readFileSync(new URL('../../src/pages/home/HomeOutlookPage.tsx', import.meta.url), 'utf8'), /sub="The current stored engine assessment/)
})
