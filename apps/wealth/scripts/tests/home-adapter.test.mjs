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
test('T2 protection list takes typed, account-scoped items only; incidents and approvals are history', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const b = prioritiesModel({ items: [
    { kind: 'INCIDENT', title: 'Unprotected Position', why: 'PR merge digest — 8 ready', since: '2026-11-01T15:00:32-05:00', stale: true },
    { kind: 'INCIDENT', title: 'Orphaned Stop', why: 'Research lane RAW-store health', since: '2026-09-17T06:20:37-04:00', stale: true },
    { kind: 'INCIDENT', title: 'Orphaned Stop', why: 'inode follow-up', since: '2026-11-13T09:00:07-04:00', stale: false },
    { kind: 'APPROVALS', title: '2 approvals waiting', why: '1 urgent (expire inside 2 h)' },
    { kind: 'STOP', title: 'Add Stop · TEST · synthetic_key_a', why: 'Stop below cost basis', since: '2026-11-15T12:00:00Z' },
  ] }, new Map([['synthetic_key_a', 'Example retirement']]))
  assert.equal(b.protection.length, 1)
  assert.equal(b.protection[0].kind, 'STOP')
  assert.equal(b.protection[0].title, 'Protection review 1')
  assert.equal(b.protection[0].scope, 'TEST')
  assert.equal(b.protection[0].label, '')
  // The raw account key never reaches the page, not even through the title or the scope.
  assert.doesNotMatch(JSON.stringify(b.protection), /synthetic_key_a/)
  assert.equal(b.history.length, 4)
  assert.deepEqual([...new Set(b.history.map(i => i.kind))].sort(), ['APPROVALS', 'INCIDENT'])
  assert.doesNotMatch(JSON.stringify(b.protection), /Unprotected Position|Orphaned Stop|approvals waiting/)
  // The producer's category survives as a quoted source, never as the desk's own claim.
  assert.equal(b.history[0].label, 'Recorded incident · source category: ')
  assert.equal(b.history[0].title, 'Unprotected Position')
  assert.equal(b.history[0].why, 'PR merge digest — 8 ready')
  assert.equal(b.history[3].label, 'Recorded approval request · source category: ')
  assert.equal(b.history[2].stale, false)
  assert.equal(b.history[2].staleLabel, 'Producer reports not stale')
  assert.doesNotMatch(JSON.stringify(b.history), /stop gap|is unprotected|requires protection|active protection/i)
})
test('T2 an old incident keeps its age and stale clock, is never marked resolved, and gains no protection wording', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const b = prioritiesModel({ items: [{ kind: 'INCIDENT', title: 'Data Integrity', why: 'plausibility', since: '2026-09-16T06:20:37-04:00' }] }, new Map())
  assert.equal(b.protection.length, 0)
  assert.equal(b.history.length, 1)
  assert.equal(b.history[0].status, '')
  assert.equal(b.history[0].statusLabel, 'Status Unknown')
  assert.equal(b.history[0].stale, null)
  assert.equal(b.history[0].staleLabel, 'Freshness not served')
  assert.equal(b.history[0].since, '2026-09-16T06:20:37-04:00')
  assert.doesNotMatch(JSON.stringify(b), /resolved/i)
})
test('T2 an all-incident feed leaves protection explicitly empty and keeps every row in history', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const items = Array.from({ length: 17 }, (_, i) => ({ kind: 'INCIDENT', title: i % 2 ? 'Orphaned Stop' : 'Unprotected Position', why: `row ${i}`, since: '2026-10-01T00:00:00Z' }))
  const b = prioritiesModel({ items }, new Map())
  assert.equal(b.protection.length, 0)
  assert.equal(b.history.length, 17)
})
test('T2 a stop item with no derivable symbol stays visible as history, never as protection', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const b = prioritiesModel({ items: [{ kind: 'STOP', title: 'Raise Stop', why: 'no scope served' }, { kind: '', title: 'Unknown kind' }] }, new Map())
  assert.equal(b.protection.length, 0)
  assert.equal(b.history.length, 2)
  assert.equal(b.history[0].label, 'Recorded stop item · source category: ')
  assert.equal(b.history[1].label, 'Recorded item (kind unrecorded) · source category: ')
})
test('T2 the protection panel states the empty case and files incidents under history', async () => {
  const fs = await import('node:fs')
  const page = fs.readFileSync(new URL('../../src/pages/home/HomeTodayPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /No account-scoped protection items served/)
  assert.match(page, /Recorded incidents and items/)
  assert.match(page, /items\.protection\.map/)
  assert.match(page, /items\.history\.map/)
  assert.doesNotMatch(page, /protection-card exception/)
  assert.doesNotMatch(page, /items\.map\(/) // the unfiltered list is gone
})
test('T2 a nonzero amount below one dollar never prints as $0', async () => {
  const { money } = await import('../../src/pages/home/homeAdapter.ts')
  assert.equal(money(-0.37), '-<$1')
  assert.equal(money(0.004), '<$1')
  assert.equal(money(0), '$0')
  assert.equal(money(null), 'Unknown')
  assert.notEqual(money(-12.6), '$0')
})
// --- AK1-AK7: a raw account key never reaches the page (lead P1, 2026-11-15) ---------------------
// Synthetic keys only (the repository is public): a three-segment lowercase account-key shape whose
// short last segment is deliberately outside the opaque-identifier regex, so the map or the backstop
// must do the work, never luck.
test('AK1 a key the overview map never named is withheld from incident free text', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const key = 'synthetic_broker_ira'
  const b = prioritiesModel({ items: [{ kind: 'INCIDENT', title: 'Unprotected Position', why: `cause references ${key}`, since: '2026-11-01T15:00:32-05:00' }] }, new Map())
  assert.equal(b.history.length, 1)
  assert.match(b.history[0].why, /\[account withheld\]/)
  assert.doesNotMatch(JSON.stringify(b), new RegExp(key))
})
test('AK2 a key named by the item\'s own account fields is replaced with the served label', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const key = 'synthetic_broker_retirement'
  const b = prioritiesModel({ items: [{ kind: 'INCIDENT', title: 'Data Integrity', why: `stop row ${key} unread`, since: '2026-11-13T09:00:07-04:00', account: key, account_label: 'Example retirement' }] }, new Map())
  assert.equal(b.history[0].why, 'stop row Example retirement unread')
  assert.doesNotMatch(JSON.stringify(b), new RegExp(key))
})
test('AK3 a STOP title that cannot yield a symbol still drops its account segment', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const key = 'synthetic_broker_ira'
  const b = prioritiesModel({ items: [{ kind: 'STOP', title: `Add Stop · SYN/CLS · ${key}`, why: 'Stop below cost basis', since: '2026-11-15T12:00:00Z' }] }, new Map())
  assert.equal(b.protection.length, 0)
  assert.equal(b.history.length, 1)
  assert.equal(b.history[0].title, 'Add Stop · SYN/CLS')
  assert.doesNotMatch(JSON.stringify(b), new RegExp(key))
})
test('AK4 every free-text field on the protection card passes through safeText, since included', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const key = 'synthetic_broker_ira'
  const b = prioritiesModel({ items: [{ kind: 'STOP', title: 'Add Stop · TEST · synthetic_key_a', why: `reason ${key}`, since: `first seen ${key}`, owner: `risk ${key}`, stale: false }] }, new Map([['synthetic_key_a', 'Example retirement']]))
  assert.equal(b.protection.length, 1)
  assert.equal(b.protection[0].scope, 'TEST')
  assert.doesNotMatch(JSON.stringify(b.protection), new RegExp(key))
})
test('AK5 ordinary two-segment snake_case identifiers are not account-shaped and survive', async () => {
  const { prioritiesModel } = await import('../../src/pages/home/homeAdapter.ts')
  const b = prioritiesModel({ items: [{ kind: 'INCIDENT', title: 'Orphaned Stop', why: 'position_unprotected and data_integrity rows', since: '2026-11-13T09:00:07-04:00' }] }, new Map())
  assert.equal(b.history[0].why, 'position_unprotected and data_integrity rows')
})
test('AK6 a key served only by the priorities read is withheld from the stored brief too', async () => {
  const key = 'synthetic_broker_ira'
  const result = homeToday({
    overview: envelope({ data: {} }),
    snapshot: envelope({ data: { snapshot: { cio_brief: { summary: { text: `brief mentions ${key}` } } } } }),
    priorities: envelope({ data: { items: [{ kind: 'INCIDENT', title: 'Data Integrity', why: `cause ${key}` }] } }),
  }, NOW)
  assert.doesNotMatch(JSON.stringify(result.snapshot.data), new RegExp(key))
  assert.doesNotMatch(JSON.stringify(result.priorities.data), new RegExp(key))
})
test('AK7 safeText withholds the multi-segment key shape and keeps short code tokens', async () => {
  const { safeText } = await import('../../src/pages/home/homeAdapter.ts')
  assert.equal(safeText('row synthetic_broker_ira unread'), 'row [account withheld] unread')
  assert.equal(safeText('position_unprotected'), 'position_unprotected')
  assert.equal(safeText('SCHEDULED JOBS 12345678'), 'SCHEDULED JOBS 12345678')
})
