import { LIST_LIMIT, curationUrl, dismissedSet, gradeCuration, gradeList, gradeProspects, pagingOf, pagingText, prospectsUrl, rowView } from './watchListsV002.ts'

declare const process: { exit(code?: number): never }
const fail = (m: string): never => { console.error('FAIL: ' + m); process.exit(1) }
const assert = {
  equal: (a: unknown, b: unknown) => { if (a !== b) fail(`${JSON.stringify(a)} !== ${JSON.stringify(b)}`) },
  ok: (v: unknown, m?: string) => { if (!v) fail(m || 'not ok') },
  match: (s: string, re: RegExp) => { if (!re.test(s)) fail(`${JSON.stringify(s)} !~ ${re}`) },
  deepEqual: (a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${JSON.stringify(a)} != ${JSON.stringify(b)}`) },
}
let passed = 0
const t = (name: string, fn: () => void) => { fn(); passed += 1; void name }
const NOW = Date.parse('2026-11-13T15:00:00Z')
const iso = (agoS: number) => new Date(NOW - agoS * 1000).toISOString()

t('fresh composed list is OK with its age', () => {
  const g = gradeList(iso(30), 'composed_at', NOW, { maxAgeS: 900 })
  assert.equal(g.state, 'OK'); assert.match(g.label, /^OK · <2 min old$/)
})
t('no as_of is UNKNOWN, never green', () => {
  for (const v of [undefined, null, '', 'not a date', 12]) assert.equal(gradeList(v, 'x', NOW).state, 'UNKNOWN')
})
t('as_of in the future is UNKNOWN', () => { assert.equal(gradeList(iso(-3600), 'x', NOW).state, 'UNKNOWN') })
t('older than the limit is STALE with the age', () => {
  const g = gradeList(iso(3 * 3600), 'composed_at', NOW, { maxAgeS: 900 })
  assert.equal(g.state, 'STALE'); assert.match(g.label, /3 h old/)
})
t('a served last-good body (_swr) is as old as the body', () => {
  const g = gradeList(iso(10), 'composed_at', NOW, { maxAgeS: 900, swr: { age_s: 4000, stale: true } })
  assert.equal(g.state, 'STALE'); assert.equal(g.ageS, 4000)
})
t('swr stale flag alone demotes', () => {
  assert.equal(gradeList(iso(10), 'composed_at', NOW, { maxAgeS: 900, swr: { age_s: 20, stale: true } }).state, 'STALE')
})
t('suggestions use the ranking limit (36 h), mine the composed limit', () => {
  const body = { my_watchlist: { as_of: iso(7200), as_of_basis: 'composed_at' }, suggests: { as_of: iso(7200), as_of_basis: 'ranking_projection' } }
  assert.equal(gradeCuration(body, 'mine', NOW).state, 'STALE')
  assert.equal(gradeCuration(body, 'suggests', NOW).state, 'OK')
})
t('missing section / body is UNKNOWN', () => {
  assert.equal(gradeCuration(null, 'mine', NOW).state, 'UNKNOWN')
  assert.equal(gradeCuration({ my_watchlist: {} }, 'mine', NOW).state, 'UNKNOWN')
})
t('prospects grade from generated_at', () => {
  assert.equal(gradeProspects({ generated_at: iso(20) }, NOW).state, 'OK')
  assert.equal(gradeProspects({}, NOW).state, 'UNKNOWN')
})
t('paging reads server pagination and never invents a total', () => {
  const p = pagingOf({ rows: [1, 2], pagination: { total: 60, returned: 25, next_offset: 25, has_more: true } })
  assert.deepEqual(p, { total: 60, returned: 25, nextOffset: 25, hasMore: true })
  assert.equal(pagingText(p, 0), '1–25 of 60')
  assert.equal(pagingOf({ rows: [1, 2, 3] }).total, null)
  assert.match(pagingText(pagingOf({ rows: [1, 2, 3] })), /total unknown/)
  assert.equal(pagingText({ total: 0, returned: 0, nextOffset: null, hasMore: false }), 'none')
})
t('urls ask for the list shape, 25 rows and the offset', () => {
  assert.equal(curationUrl('mine', 25), '/api/v3/data-broker/watch-curation?view=mine&shape=list&limit=25&offset=25')
  assert.equal(LIST_LIMIT, 25)
  assert.match(prospectsUrl('forming', -5), /lane=forming&limit=25&offset=0$/)
})
t('rowView projects a list row and rejects one with no symbol', () => {
  const r = rowView({ symbol: ' axti ', company: 'AXT', stage: 'forming', conviction: 72, starred: true, position_state: 'formerly_held', why: 'w', next_action: { label: 'Set alert' } })
  assert.deepEqual(r && { s: r.symbol, h: r.held, c: r.conviction, n: r.nextAction, d: r.detailHref }, { s: 'AXTI', h: 'Formerly held', c: 72, n: 'Set alert', d: '/watch/intelligence/AXTI' })
  assert.equal(rowView({ stage: 'x' }), null); assert.equal(rowView(null), null)
})
t('a suggestion shows the server reason; a dismissed name is marked', () => {
  const r = rowView({ symbol: 'ZZ', suggestion: { reason: 'rank 3' }, why: 'other' }, new Set(['ZZ']))
  assert.equal(r?.why, 'rank 3'); assert.equal(r?.dismissed, true)
})
t('dismissedSet keeps a read error visible', () => {
  const d = dismissedSet({ suggests: { dismissed: [{ symbol: 'a' }], dismissed_status: 'error:OperationalError' } })
  assert.ok(d.symbols.has('A')); assert.equal(d.status, 'error:OperationalError')
  assert.equal(dismissedSet(null).status, 'unknown')
})

console.log(`${passed} passed, 0 failed`)
