// LQ-20261107-2993b: Watch v002 list tabs rendering. A list without an as_of reads UNKNOWN, a stale one STALE with its age;
// an unread list is never an empty list; star/dismiss/restore/detail controls exist. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (existsSync(target) && statSync(target).isDirectory()) target = ['index.ts', 'index.tsx'].map(s => join(target, s)).find(existsSync)
    else if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const model = await import(compile(join(app, 'src/lib/watchListsV002.ts')))
const page = await import(compile(join(app, 'src/pages/WatchListsV002.tsx')))
const { clocksOf, gradeList, rowView, pagingOf } = model
const { WatchListsV002View } = page

const NOW = Date.parse('2031-03-07T15:00:00Z')
const iso = s => new Date(NOW - s * 1000).toISOString()
const noop = () => {}
const base = (o = {}) => ({
  tab: 'mine', grade: gradeList(iso(30), 'composed_at', NOW, { maxAgeS: 900 }),
  rows: [rowView({ symbol: 'AAA', stage: 'forming', conviction: 71, starred: true, why: 'w1' }), rowView({ symbol: 'BBB', stage: 'actionable', conviction: null, starred: false })],
  paging: pagingOf({ rows: [1, 2], pagination: { total: 60, returned: 25, next_offset: 25, has_more: true } }), offset: 0,
  loading: false, error: null, gap: null, message: '', dismissedStatus: 'ok', dismissedItems: [],
  onTab: noop, onStar: noop, onDismiss: noop, onRestore: noop, onPage: noop, onRetry: noop, ...o,
})
const html = p => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WatchListsV002View, p)))
const asof = h => (h.match(/data-testid="watch-list-asof"[^>]*>/) || [''])[0]

// 1. fresh list: OK, rows, star + detail link, paging text
{
  const h = html(base())
  assert.match(asof(h), /data-state="OK"/)
  assert.ok(h.includes('data-testid="watch-star-AAA"') && h.includes('aria-pressed="true"'))
  assert.ok(h.includes('href="/watch/intelligence/BBB"'))
  assert.match(h, /1–25 of 60/); assert.match(h, /no score/)
  assert.ok(!h.includes('watch-dismiss-'), 'no dismiss on My List')
}
// 2. no as_of -> UNKNOWN; stale -> STALE with age
{
  assert.match(asof(html(base({ grade: gradeList(undefined, null, NOW) }))), /data-state="UNKNOWN"/)
  const h = html(base({ grade: gradeList(iso(3 * 3600), 'composed_at', NOW, { maxAgeS: 900 }) }))
  assert.match(asof(h), /data-state="STALE"/); assert.match(h, /3 h old/)
}
// 3. unread list is not an empty list; error is shown with Retry
{
  const h = html(base({ grade: null, rows: [], paging: pagingOf(null), error: 'HTTP 503' }))
  assert.match(asof(h), /data-state="UNKNOWN"/)
  assert.ok(h.includes('watch-list-error') && h.includes('Retry'))
  assert.ok(!h.includes('No names in this list'), 'unread must not read as empty')
  assert.ok(!h.includes('watch-list-empty'))
}
// 4. loading
assert.match(asof(html(base({ grade: null, rows: [], loading: true }))), /data-state="LOADING"/)
// 5. genuinely empty list says so
assert.ok(html(base({ rows: [], paging: pagingOf({ rows: [], pagination: { total: 0, returned: 0, next_offset: null, has_more: false } }) })).includes('No names in this list.'))
// 6. suggestions: dismiss button, dismissed section with restore, a dismissed-read error stays visible
{
  const h = html(base({ tab: 'suggests', dismissedStatus: 'error:OperationalError', dismissedItems: [{ symbol: 'ZZZ', reason: 'meh', until: '2031-04-06T00:00:00Z' }] }))
  assert.ok(h.includes('data-testid="watch-dismiss-AAA"'))
  assert.ok(h.includes('data-testid="watch-dismissed-ZZZ"') && h.includes('data-testid="watch-restore-ZZZ"') && h.includes('until 2031-04-06'))
  assert.ok(h.includes('watch-dismissed-unknown'))
}
// 7. prospects: no star, no dismiss
{
  const h = html(base({ tab: 'prospects' }))
  assert.ok(!h.includes('watch-star-') && !h.includes('watch-dismiss-'))
}
// 8. Next disabled without more pages
assert.match(html(base({ paging: pagingOf({ rows: [1], pagination: { total: 1, returned: 1, next_offset: null, has_more: false } }) })), /<button[^>]*disabled[^>]*>Next/)
// 9. R4: an unreadable body (UNKNOWN grade / gap / null total) with no rows says so + Retry, never 'Nothing on this page' / 'No names'
for (const o of [
  { grade: gradeList(undefined, null, NOW), rows: [], paging: pagingOf(null) },
  { rows: [], gap: 'payload over budget', paging: pagingOf({ rows: [], pagination: { total: 0, returned: 0, next_offset: null, has_more: false } }) },
  { rows: [], paging: pagingOf({ rows: [] }) },
]) {
  const h = html(base(o))
  assert.ok(h.includes('data-testid="watch-list-unreadable"') && h.includes('Retry'), 'unreadable shows Retry')
  assert.ok(!h.includes('Nothing on this page') && !h.includes('No names in this list') && !h.includes('watch-list-empty'))
}
assert.ok(html(base({ rows: [], gap: 'payload over budget', paging: pagingOf(null) })).includes('payload over budget'))
// page beyond the end of a readable list keeps the honest line
assert.ok(html(base({ rows: [], offset: 50, paging: pagingOf({ rows: [], pagination: { total: 60, returned: 0, next_offset: null, has_more: false } }) })).includes('Nothing on this page.'))
// 10. R5: toned chip per state, v010 root, no inline styles
{
  const tone = st => html(base({ grade: gradeList(st === 'OK' ? iso(30) : st === 'STALE' ? iso(3 * 3600) : undefined, st === 'UNKNOWN' ? null : 'composed_at', NOW, { maxAgeS: 900 }) }))
  assert.match(tone('OK'), /v010-pill ok/); assert.match(tone('STALE'), /v010-pill warn/); assert.match(tone('UNKNOWN'), /v010-pill bad/)
  const h = html(base())
  assert.ok(h.includes('class="v010 wl2"') && !h.includes('style='), 'v010 root, classes not inline styles')
}
// 11. a missing dismissed_status on Suggestions is flagged, not silently trusted
assert.ok(html(base({ tab: 'suggests', dismissedStatus: 'unknown' })).includes('watch-dismissed-unknown'))
// 12. N2: gapOf (the page's own reading of a server-declared gap) and its wiring
const { gapOf } = page
assert.equal(gapOf({}, { payload_gap: 'over budget' }), 'over budget', 'section payload_gap')
assert.equal(gapOf({ payload_gap: { reason: 'garbled' } }, {}), 'garbled', 'body payload_gap (object reason)')
assert.equal(gapOf({ payload_gap: { code: 'x_code' } }, null), 'x_code')
assert.ok(/unavailable/.test(gapOf({ status: 'unavailable' }, {}) || ''), 'status unavailable')
assert.equal(gapOf({ status: 'ok' }, { rows: [] }), null, 'no gap')
assert.equal(gapOf(null, undefined), null)
// UNKNOWN-only: grade UNKNOWN, total 0, no gap, no rows -> unreadable, not "No names in this list."
{
  const h = html(base({ grade: gradeList(undefined, null, NOW), rows: [], gap: null, paging: pagingOf({ rows: [], pagination: { total: 0, returned: 0, next_offset: null, has_more: false } }) }))
  assert.ok(h.includes('watch-list-unreadable') && !h.includes('No names in this list'), 'UNKNOWN-only reads unreadable')
}
// a readable, truly empty list keeps the honest empty line
assert.ok(html(base({ rows: [], paging: pagingOf({ rows: [], pagination: { total: 0, returned: 0, next_offset: null, has_more: false } }) })).includes('No names in this list.'))
const src = f => readFileSync(join(app, 'src', f), 'utf8')
const listsSrc = src('pages/WatchListsV002.tsx')
assert.ok(/gap=\{gapOf\(body, section\)\}/.test(listsSrc), 'page passes gap={gapOf(body, section)}')
// 13. N4: the dismissed warning is not shown while loading, or when the body has no suggests section (a retained body from another tab)
assert.ok(!html(base({ tab: 'suggests', loading: true, grade: null, rows: [], dismissedStatus: 'unknown' })).includes('watch-dismissed-unknown'))
assert.ok(!html(base({ tab: 'suggests', dismissedStatus: 'absent' })).includes('watch-dismissed-unknown'))
assert.ok(/dismissedStatus=\{body\?\.suggests \? dis\.status : 'absent'\}/.test(listsSrc), 'page marks a missing suggests section absent')
assert.ok(/<WatchListsTab key=\{tab\}/.test(listsSrc), 'a tab switch remounts the list (useApi keeps the last body)')
// 14. N1/N3 (release-3 ruling 2026-11-14T10:18Z reverses N1 for the bare path): the re-entry banner mounts on bare /watch
// again (UI removal needs an approved mockup; tests/test_reentry_cross_surface_v6.py pins it) and still follows
// /watch-classic and /watch/*; the flagged-names link lands on /watch-classic
const bridge = src('components/SharedIntelligenceBridge.tsx')
assert.ok(/showWatch = location\.pathname === '\/watch' \|\|/.test(bridge), 'bridge mounts on bare /watch')
assert.ok(/showWatch = [^\n]*'\/watch-classic'/.test(bridge) && /startsWith\('\/watch\/'\)/.test(bridge), 'bridge also follows /watch-classic and /watch/*')
assert.ok(/to="\/watch-classic">See flagged names on Watch/.test(src('pages/ConflictRules.tsx')), 'flagged-names link goes to /watch-classic')
// 15. A3: the /watch -> /watch-classic redirect replaces history, so Back does not bounce
assert.ok(/<Navigate replace to=|<Navigate to=\{[^}]*\} replace|<Navigate[^>]*\breplace\b/.test(src('pages/WatchV002.tsx')), 'redirect uses replace')
// 16. W-04: the shared sub-nav renders on the Lists page too and marks the list the URL asks for, not a fixed tab
{
  const at = (path, p) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [path] }, React.createElement(WatchListsV002View, p)))
  const h = at('/watch-lists?list=prospects', base({ tab: 'prospects' }))
  const full = k => (h.match(new RegExp(`<(?:a|span)[^>]*data-testid="watch-subnav-${k}"[^>]*>`)) || [''])[0]
  assert.match(full('prospects'), /^<span/); assert.match(full('prospects'), /aria-current="page"/)
  assert.match(full('mine'), /^<a/); assert.match(full('mine'), /href="\/watch-lists\?list=mine"/)
  assert.match(full('setups'), /^<a/); assert.match(full('setups'), /href="\/watch-setups"/)
  assert.match(full('sectors'), /^<a/); assert.match(full('sectors'), /href="\/watch-setups\?tab=sectors"/)
  assert.match(full('pullback'), /^<a/); assert.match(full('pullback'), /href="\/watch-setups\?tab=pullback"/)
  const nav = (h.match(/<nav[^>]*data-testid="watch-subnav"[^>]*>[\s\S]*?<\/nav>/) || [''])[0]
  assert.ok(nav && !nav.includes('/watch-classic'), 'no tab points at the classic hub')
}
// 17. WL-12/WL-23: every tab has a heading and a purpose line (the list pages had no h1 at all)
{
  assert.match(html(base()), /<h1 class="v010-h1">My List<\/h1>/)
  assert.ok(html(base()).includes('Every name you monitor'))
  assert.match(html(base({ tab: 'suggests' })), /<h1 class="v010-h1">Suggestions<\/h1>/)
  assert.match(html(base({ tab: 'prospects' })), /<h1 class="v010-h1">Prospects<\/h1>/)
}
// 18. WL-18: prospects lanes are the SERVER's (id/label/count, server order), the URL lane is the active tab, and the
// active lane's cap overflow is named — a lane the payload does not carry is never invented on the page.
// The lane shape is the REAL one (`{id,label,count,overflow,items}`): review F2 found an earlier fixture carrying a
// per-lane `as_of` the server never sends, which made the page look like it read a source clock it cannot have.
{
  const body = { generated_at: iso(20), lanes: [
    { id: 'actionable', label: 'Actionable', count: 3, items: [] },
    { id: 'forming', label: 'Forming', count: 12, overflow: ['CCC', 'DDD'], items: [] },
    { id: 'reentry', label: 'Re-entry', count: null, items: [] },
  ] }
  const lanes = model.laneTabs(body, 'forming')
  assert.deepEqual(lanes.map(l => l.id), ['actionable', 'forming', 'reentry'], 'server lanes, in server order')
  assert.ok(lanes[1].active && !lanes[0].active, 'exactly the URL lane is active')
  assert.equal(lanes[2].count, null, 'a lane without a count stays unknown, not 0')
  assert.deepEqual(model.laneOverflow(body, 'forming'), ['CCC', 'DDD'])
  assert.deepEqual(model.laneOverflow(body, 'actionable'), [])
  const h = html(base({ tab: 'prospects', lane: 'forming', lanes, overflow: model.laneOverflow(body, 'forming') }))
  assert.ok(h.includes('role="tablist"') && h.includes('data-testid="watch-lanes"'))
  assert.match((h.match(/<button[^>]*data-testid="watch-lane-forming"[^>]*>/) || [''])[0], /data-active="1"/)
  assert.match((h.match(/<button[^>]*data-testid="watch-lane-actionable"[^>]*>/) || [''])[0], /data-active="0"/)
  assert.ok(h.includes('count unknown'), 'a null count says unknown')
  assert.ok(h.includes('watch-lane-overflow') && h.includes('CCC') && h.includes('DDD'), 'cap overflow is named')
  assert.ok(!h.includes('watch-lane-expired'), 'a lane the server did not send is not invented')
}
// 19. WL-12: the search filters the rows already on the page, says so, and offers Clear on no match
{
  const h = html(base({ query: 'aa' }))
  assert.ok(h.includes('watch-row-AAA') && !h.includes('watch-row-BBB'), 'symbol filter')
  assert.match(h, /1 of 2 on this page match/)
  assert.match(h, /on this page only/, 'the filter is labelled as page-scoped, not a server search')
  const co = html(base({ query: 'widget', rows: [rowView({ symbol: 'AAA', company: 'Widget Co' }), rowView({ symbol: 'BBB' })] }))
  assert.ok(co.includes('watch-row-AAA') && !co.includes('watch-row-BBB'), 'company filter')
  const none = html(base({ query: 'zzz' }))
  assert.ok(none.includes('watch-list-no-match') && !none.includes('watch-row-AAA') && none.includes('>Clear<'), 'no match is stated, not an empty list')
  assert.ok(!none.includes('No names in this list'), 'a filter miss is not an empty list')
}
// 20. WL-09/WL-20: next_action is labelled guidance next to a link to the symbol — never rendered as a command that
// the page cannot execute
{
  const h = html(base({ rows: [rowView({ symbol: 'AAA', next_action: { label: 'Review the setup' } })] }))
  assert.match(h, /data-guidance="1"/)
  assert.ok(h.includes('open the symbol for actions') && h.includes('Review the setup'))
  assert.ok(!/data-guidance="1"[^<]*<button/.test(h), 'guidance text carries no button')
  assert.ok(h.includes('href="/watch/intelligence/AAA"'))
}
// 21. WL-17/WL-27: a command in flight disables only its own row's control; every other control stays live
{
  const h = html(base({ tab: 'suggests', busy: 'AAA:dismiss', rows: [rowView({ symbol: 'AAA' }), rowView({ symbol: 'BBB' })] }))
  const btn = s => (h.match(new RegExp(`<button[^>]*data-testid="watch-dismiss-${s}"[^>]*>`)) || [''])[0]
  assert.match(btn('AAA'), /disabled/)
  assert.ok(!/disabled/.test(btn('BBB')), 'the other row is not blocked')
  const m = html(base({ busy: 'AAA:star' }))
  const star = s => (m.match(new RegExp(`<button[^>]*data-testid="watch-star-${s}"[^>]*>`)) || [''])[0]
  assert.match(star('AAA'), /disabled/)
  assert.ok(!/disabled/.test(star('BBB')))
  const r = html(base({ tab: 'suggests', busy: 'ZZZ:restore', dismissedItems: [{ symbol: 'ZZZ', reason: null, until: null }] }))
  assert.match((r.match(/<button[^>]*data-testid="watch-restore-ZZZ"[^>]*>/) || [''])[0], /disabled/)
}
// 22. WL-23/WL-29: the URL is the whole view state — list/stage/offset/q parse, a lane change drops the cursor, and
// clearing the filter deletes the key instead of leaving `q=`
{
  assert.deepEqual(page.listQuery(new URLSearchParams('list=prospects&stage=reentry&offset=50&q=aa')), { tab: 'prospects', lane: 'reentry', offset: 50, query: 'aa' })
  assert.deepEqual(page.listQuery(new URLSearchParams('')), { tab: 'mine', lane: null, offset: 0, query: '' })
  assert.deepEqual(page.listQuery(new URLSearchParams('list=bogus&offset=-4')), { tab: 'mine', lane: null, offset: 0, query: '' }, 'unknown tab falls back, bad offset clamps')
  assert.equal(page.listQuery(new URLSearchParams('list=prospects')).lane, 'actionable', 'the default lane is the server default')
  assert.equal(page.listQuery(new URLSearchParams('list=mine&stage=reentry')).lane, null, 'stage is Prospects-only')
  const sp = new URLSearchParams('list=prospects&stage=forming&offset=25&q=aa')
  assert.equal(page.listParams(sp, { offset: 0 }).toString(), 'list=prospects&stage=forming&q=aa', 'a lane/page change drops the stale cursor')
  assert.equal(page.listParams(sp, { query: '' }).toString(), 'list=prospects&stage=forming&offset=25', 'clearing q deletes it')
  assert.equal(page.listParams(sp, { offset: 50 }).toString(), 'list=prospects&stage=forming&offset=50&q=aa', 'paging keeps the filter')
  assert.equal(page.listParams(sp, { stage: 'reentry', offset: 0 }).toString(), 'list=prospects&stage=reentry&q=aa', 'a lane change keeps the filter')
}
// 23. the route component itself renders a deep link (SSR: effects do not run, so no server call) with the tab the URL
// asks for, and it reads that state once through listQuery
{
  const el = React.createElement(MemoryRouter, { initialEntries: ['/watch-lists?list=prospects&stage=reentry&offset=25'] }, React.createElement(page.default))
  const h = renderToStaticMarkup(el)
  assert.ok(h.includes('data-testid="watch-lists-v002"'), 'the route renders')
  assert.match(h, /<h1 class="v010-h1">Prospects<\/h1>/, 'list=prospects selects the Prospects tab')
  assert.ok(listsSrc.includes('const q = listQuery(sp)'), 'the route derives its state from the URL once')
  assert.ok(/onLane=\{l => go\(\{ offset: 0, stage: l \}\)\}/.test(listsSrc), 'a lane change resets the cursor')
}
// 24. WL-13: conviction and universe rank are two different numbers — both are labelled, a missing one is said, and
// neither is synthesised from the other
{
  const out = s => (html(base({ rows: [rowView(s)] })).match(/data-testid="watch-conviction-AAA"[^>]*>([^<]*)</) || [null, ''])[1]
  assert.equal(out({ symbol: 'AAA', conviction: 84.4, universe_rank: 12 }), 'conviction 84 · universe rank #12')
  assert.equal(out({ symbol: 'AAA', conviction: null, universe_rank: 5 }), 'no score · universe rank #5', 'rank without a conviction score')
  assert.equal(out({ symbol: 'AAA', conviction: 61 }), 'conviction 61', 'no rank supplied => no rank claimed')
  assert.equal(out({ symbol: 'AAA' }), 'no score')
  assert.equal(model.rankingLegend({ ranking: { label: 'Full universe rank — the curator order' } }), 'Full universe rank — the curator order')
  assert.equal(model.rankingLegend({}), null)
  const h = html(base({ tab: 'suggests', legend: 'Full universe rank — the curator order' }))
  assert.ok(h.includes('watch-ranking-legend') && h.includes('two different numbers'), 'the legend names the distinction once')
  assert.ok(!html(base({ tab: 'mine', legend: 'x' })).includes('watch-ranking-legend'), 'the legend is Suggestions-only')
}
// 25. WL-08/WL-25: membership provenance comes from the row's own reasons; the star is a pin, not the only route in
{
  const row = rowView({
    symbol: 'AAA', starred: true,
    membership: [{ kind: 'starred', label: 'Starred by you', at: iso(3600) }, { kind: 'personal_watchlist', label: 'Your personal watchlist', at: iso(86400) }],
  })
  assert.deepEqual(model.otherMembership(row).map(m => m.kind), ['personal_watchlist'], 'the star is not repeated as a second reason')
  const h = html(base({ rows: [row] }))
  assert.ok(h.includes('data-testid="watch-member-AAA-personal_watchlist"'), 'the non-star source is badged')
  assert.ok(!h.includes('watch-member-AAA-starred'), 'the star is the control, not a badge')
  assert.match(h, /Starred \(your pin\)\. Also listed via Your personal watchlist — unstarring keeps it on this list/, 'the pin/membership split is stated')
  const plain = rowView({ symbol: 'BBB', membership: [{ kind: 'directive', label: 'Your watch directive' }] })
  assert.match(html(base({ rows: [plain] })), /Also listed via Your watch directive/, 'a name never starred is still explained')
  const labelLess = rowView({ symbol: 'CCC', membership: [{ kind: 'operator_added' }] })
  assert.equal(model.otherMembership(labelLess)[0].label, 'operator added', 'a server reason without a label falls back to the kind, not to invented copy')
  const exp = rowView({ symbol: 'DDD', expiry_suggestion: { reason: 'signal expired 2 d ago', suggest: 'review' } })
  const he = html(base({ rows: [exp] }))
  assert.ok(he.includes('watch-expiry-DDD') && he.includes('review, not removed'), 'an expired signal on a name that is yours asks for a review')
  assert.ok(he.includes('signal expired 2 d ago'), 'the server reason is carried as the tooltip')
}
// 26. WL-25: an unreadable membership source means the list may be missing names — it says so instead of reading complete
{
  const body = { my_watchlist: { sources: { starred: { status: 'ok', count: 3 }, directive: { status: 'error', error: 'OperationalError', count: 0 } } } }
  assert.deepEqual(model.membershipSources(body), [{ kind: 'starred', status: 'ok', count: 3 }, { kind: 'directive', status: 'error', count: 0 }])
  assert.deepEqual(model.membershipSources({}), [])
  const bad = html(base({ sources: model.membershipSources(body) }))
  assert.match(bad, /role="alert"/); assert.ok(bad.includes('this list is not complete'))
  const good = html(base({ sources: model.membershipSources({ my_watchlist: { sources: { starred: { status: 'ok', count: 3 } } } }) }))
  assert.ok(!good.includes('not complete') && good.includes('not only the star'), 'a readable list says where names come from')
  assert.ok(!html(base({ tab: 'suggests', sources: [{ kind: 'starred', status: 'error', count: 0 }] })).includes('watch-membership-sources'), 'the strip is My List only')
}
// 27. WL-10/WL-16/WL-26: the body's clocks are rendered side by side with their own ages; an absent clock is omitted,
// never replaced with render time
{
  const mine = clocksOf({ generated_at: iso(20), my_watchlist: { as_of: iso(900), as_of_basis: 'composed_at' } }, 'mine', null, NOW)
  assert.deepEqual(mine.map(c => [c.id, c.label, c.ageS]), [['composed_at', 'Page composed', 20], ['source_as_of', 'List source', 900]])
  // The LIVE suggests shape: the section clock and the ranking clock are the SAME projection stamp, and the section's
  // basis says so — so the ranking clock is printed ONCE (review r5c F1 saw the same stamp twice under one label).
  const stamp = iso(3600)
  const sug = clocksOf({ generated_at: iso(20), suggests: { as_of: stamp, as_of_basis: 'ranking_projection' }, ranking: { as_of: stamp } }, 'suggests', null, NOW)
  assert.deepEqual(sug.map(c => [c.id, c.label, c.ageS]), [['composed_at', 'Page composed', 20], ['source_as_of', 'Ranking projection', 3600]])
  // Without a section clock the ranking clock still stands alone; a non-ranking section clock is its own clock.
  const rankOnly = clocksOf({ generated_at: iso(20), suggests: {}, ranking: { as_of: iso(3600) } }, 'suggests', null, NOW)
  assert.deepEqual(rankOnly.map(c => [c.id, c.ageS]), [['composed_at', 20], ['ranking_as_of', 3600]])
  const listSrc = clocksOf({ generated_at: iso(20), suggests: { as_of: iso(900), as_of_basis: 'composed_at' }, ranking: { as_of: iso(3600) } }, 'suggests', null, NOW)
  assert.deepEqual(listSrc.map(c => [c.id, c.label]), [['composed_at', 'Page composed'], ['source_as_of', 'List source'], ['ranking_as_of', 'Ranking projection']],
    'a list clock that is not the ranking projection keeps both clocks, distinctly labelled')
  // Prospects, REAL lane shape (no `as_of`): the payload carries no per-lane source clock, so the block claims only
  // the composition clock and invents nothing. This is the shape the server actually sends — review F2's requested
  // fixture, replacing one that carried a field the server has never sent.
  const real = clocksOf({ generated_at: iso(20), lanes: [{ id: 'forming', count: 2, items: [] }, { id: 'actionable', count: 1, items: [] }] }, 'prospects', 'forming', NOW)
  assert.deepEqual(real.map(c => [c.id, c.ageS]), [['composed_at', 20]], 'the real lane shape yields the composition clock and NO lane clock')
  // Forward contract only (NEEDS BACKEND): IF a lane ever carries its own `as_of`, it is used and labelled as the
  // source clock. Kept as a contract test, explicitly not as evidence of today's payload.
  const fwd = clocksOf({ generated_at: iso(20), lanes: [{ id: 'forming', as_of: iso(600) }, { id: 'actionable', as_of: iso(30) }] }, 'prospects', 'forming', NOW)
  assert.deepEqual(fwd.map(c => [c.id, c.ageS]), [['composed_at', 20], ['source_as_of', 600]], 'a lane `as_of`, when the server sends one, is the SELECTED lane\'s source clock')
  assert.deepEqual(clocksOf({}, 'mine', null, NOW), [], 'a body with no timestamps claims no clock')
  const h = html(base({ clocks: mine }))
  assert.ok(h.includes('data-testid="watch-list-clocks"'))
  assert.match(h, /data-clock="source_as_of"/); assert.ok(h.includes('15 min old'), 'the source age is shown next to its stamp')
  assert.ok(!html(base({ clocks: [] })).includes('watch-list-clocks'), 'no clocks, no block')
}
// 28. WL-20: Add to My List is offered on Prospects only for a name the SERVER says is not yours and whose lane the CIO
// currently calls actionable; an `expired`/`manage` row gets no button, and a page without the command renders none
{
  const add = s => rowView({ symbol: s.symbol, ...s })
  assert.equal(model.canAddToMine(add({ symbol: 'AAA', mine: false, stage: 'actionable' })), true)
  assert.equal(model.canAddToMine(add({ symbol: 'AAA', mine: true, stage: 'actionable' })), false, 'already yours => nothing to add')
  assert.equal(model.canAddToMine(add({ symbol: 'AAA', mine: false, stage: 'Expired' })), false, 'an expired lane is not a new idea')
  assert.equal(model.canAddToMine(add({ symbol: 'AAA', mine: false, stage: 'manage' })), false)
  const onAdd = noop
  const h = html(base({ tab: 'prospects', rows: [add({ symbol: 'AAA', mine: false, stage: 'forming' }), add({ symbol: 'BBB', mine: true, stage: 'forming' }), add({ symbol: 'CCC', mine: false, stage: 'manage' })], onAdd }))
  const btn = s => (h.match(new RegExp(`<button[^>]*data-testid="watch-add-${s}"[^>]*>[^<]*<`)) || [''])[0]
  assert.match(btn('AAA'), />Add to My List</, 'an actionable non-yours prospect can be adopted')
  assert.equal(btn('BBB'), '', 'a name the server says is yours gets no Add')
  assert.equal(btn('CCC'), '', 'a lane that is not actionable gets no Add')
  assert.ok(!html(base({ tab: 'prospects', rows: [add({ symbol: 'AAA', mine: false, stage: 'forming' })] })).includes('watch-add-AAA'), 'no command wired => no button (never a dead control)')
  assert.ok(!html(base({ tab: 'suggests', rows: [add({ symbol: 'AAA', mine: false, stage: 'actionable' })], onAdd })).includes('watch-add-AAA'), 'Prospects only')
  assert.ok(/onAdd=\{r => void act\(`\$\{r\.symbol\}:add`, async \(\) => \{ const res = await mineAction\(r\.symbol, 'add', undefined, 'watch\.v002'\)/.test(listsSrc), 'the Add control uses the existing membership command')
}
// 29. WL-21: the Yours pill is the server's `mine`, not the star — a starred name the server does not report as yours
// gets no pill, and a name yours through another source does
{
  const h = html(base({ rows: [rowView({ symbol: 'AAA', mine: true, starred: false }), rowView({ symbol: 'BBB', mine: false, starred: true }), rowView({ symbol: 'CCC', mine: false })] }))
  assert.ok(h.includes('data-testid="watch-yours-AAA"'), 'server says yours => pill, even without the star')
  assert.match((h.match(/data-testid="watch-yours-AAA"[^>]*>([^<]*)</) || [null, ''])[1], /Yours/)
  assert.ok(!h.includes('watch-yours-BBB'), 'the star is not the membership answer')
  assert.ok(!h.includes('watch-yours-CCC'))
  assert.equal(rowView({ symbol: 'AAA', mine: 'yes' }).mine, false, 'only a real boolean true counts as yours')
}
// 30. WL-17/WL-20: an Add in flight disables only that row's Add and says it is working; a later click cannot race it
{
  const rows = [rowView({ symbol: 'AAA', stage: 'actionable' }), rowView({ symbol: 'BBB', stage: 'actionable' })]
  const h = html(base({ tab: 'prospects', rows, onAdd: noop, busy: 'AAA:add' }))
  const btn = s => (h.match(new RegExp(`<button[^>]*data-testid="watch-add-${s}"[^>]*>[^<]*<`)) || [''])[0]
  assert.match(btn('AAA'), /disabled/); assert.match(btn('AAA'), /Adding…/)
  assert.ok(!/disabled/.test(btn('BBB')), 'the other row stays live')
  assert.ok(/if \(busy\) return/.test(listsSrc), 'one command at a time')
}
// 31. J2-failure: a command that fails is stated as a failure on the list and the list is NOT refetched as if it worked
{
  const h = html(base({ message: 'Failed: HTTP 503 — the command was refused' }))
  assert.match(h, /data-testid="watch-list-message"[^>]*role="status"/)
  assert.ok(h.includes('Failed: HTTP 503'), 'the server reason reaches the operator')
  assert.ok(/try \{ setMessage\(await fn\(\)\); refetch\(\) \} catch \(e\) \{ setMessage\(`Failed: /.test(listsSrc), 'refetch runs on success only; a failure is reported, not read back as success')
}
// 32. WL-11: the monitoring fields the read does NOT carry are named once — a blank column may not read as a clean row.
// The list is derived from the body, so a field the server starts sending disappears from the disclosure on its own.
{
  const mine = { my_watchlist: { rows: [{ symbol: 'AAA' }] } }
  assert.deepEqual(model.absentRowFields(mine, 'mine').map(f => f.id), ['quote', 'entry', 'alert'], 'all three are named when the body carries none')
  assert.deepEqual(model.absentRowFields({ my_watchlist: { rows: [{ symbol: 'AAA', last_price: 12.5 }] } }, 'mine').map(f => f.id), ['entry', 'alert'], 'a field that IS sent is not called absent')
  assert.deepEqual(model.absentRowFields({ my_watchlist: { rows: [] } }, 'mine'), [], 'nothing read => no column claim')
  const pro = { lanes: [{ id: 'forming', items: [{ symbol: 'AAA', last_price: 1, entry_level: 2, alert_state: 'armed' }] }] }
  assert.deepEqual(model.absentRowFields(pro, 'prospects'), [], 'prospects rows are checked too')
  assert.equal(model.joinLabels(['a', 'b', 'c']), 'a, b and c')
  assert.equal(model.joinLabels(['a']), 'a')

  const h = html(base({ absent: model.absentRowFields(mine, 'mine') }))
  assert.match(h, /data-testid="watch-row-absent" data-absent="quote,entry,alert"/)
  assert.ok(h.includes('last price and quote age') && h.includes('alert condition and armed/fired/paused state'), 'the disclosure names the fields')
  assert.ok(h.includes('treat') && h.includes('not as a monitoring verdict'), 'and says what the row is not')
  assert.ok(!html(base({ absent: [] })).includes('watch-row-absent'), 'no disclosure when the read carries the fields')
}
// 33. WL-22: a prospects row that states no condition says the condition is unavailable — never "setup confirmed"
{
  const h = html(base({ tab: 'prospects', rows: [rowView({ symbol: 'AAA', stage: 'forming' }), rowView({ symbol: 'BBB', stage: 'forming', why: 'needs a close above 42' })] }))
  assert.match(h, /data-testid="watch-condition-AAA"[^>]*data-unavailable="1"/)
  assert.ok(h.includes('does not prove the setup is confirmed'))
  assert.ok(!h.includes('watch-condition-BBB'), 'a stated condition is shown, not replaced')
  assert.ok(h.includes('needs a close above 42'))
  assert.ok(!html(base({ rows: [rowView({ symbol: 'AAA' })] })).includes('watch-condition-AAA'), 'My List rows are not setup rows')
}
// 34. WL-12: a search that could not be read says exactly that — never "no match", and never a guessed ticker
{
  const err = html(base({ search: { q: 'AAPL', submitted: 'AAPL', loading: false, error: 'HTTP 503', hits: [], gap: null } }))
  assert.match(err, /data-testid="watch-add-error"[^>]*role="alert"/)
  assert.ok(err.includes('Symbol search could not be read: HTTP 503'), 'the read failure is stated with its own reason')
  assert.ok(err.includes('No ticker is guessed from what you typed'))
  assert.ok(!err.includes('watch-add-none'), 'a failed read is not "nothing matched"')
  assert.ok(!err.includes('watch-hit-'), 'a failed read offers no rows to add')
  assert.ok(!html(base({ search: { q: 'AA', submitted: '', loading: false, error: null, hits: [], gap: null } })).includes('watch-add-error'), 'no failure claimed before any read')
}
// 35. WL-12: the hits are the SERVER's rows; a name already on My List gets no Add (duplicate-safe); a body we cannot read is
// a gap, not an empty result
{
  const hits = model.searchHits({ schema: 'WatchSymbolSearch@v1', results: [
    { symbol: 'aapl', name: ' Apple Inc ', identity_status: 'RESOLVED', in_registry: true, on_my_list: false, match: 'ticker' },
    { symbol: 'APLE', in_registry: false, on_my_list: true, match: 'name' },
    { symbol: '   ' },
    { name: 'no ticker' },
  ] })
  assert.deepEqual(hits.map(h => h.symbol), ['AAPL', 'APLE'], 'rows with no ticker are dropped, symbols are normalised')
  assert.equal(hits[0].name, 'Apple Inc'); assert.equal(hits[0].identityStatus, 'RESOLVED'); assert.equal(hits[0].inRegistry, true)
  assert.equal(hits[1].name, null); assert.equal(hits[1].inRegistry, false); assert.equal(hits[1].onMyList, true)
  assert.equal(model.searchHits({ results: 'nope' }).length, 0)

  const h = html(base({ search: { q: 'appl', submitted: 'appl', loading: false, error: null, hits, gap: null } }))
  assert.match(h, /data-testid="watch-add-for">Results for “appl”/, 'the shown rows are labelled with the query they answer')
  assert.ok(h.includes('data-testid="watch-hit-add-AAPL"'), 'a name not on My List can be added')
  assert.ok(!h.includes('watch-hit-onlist-AAPL'))
  assert.ok(h.includes('data-testid="watch-hit-onlist-APLE"'), 'the server says yours => said so')
  assert.ok(!h.includes('watch-hit-add-APLE'), 'and no Add is offered for it — no duplicate path')
  assert.ok(h.includes('not in the registry'), 'a row outside the registry is labelled, not hidden')

  const none = html(base({ search: { q: 'zzz', submitted: 'zzz', loading: false, error: null, hits: [], gap: null } }))
  assert.ok(none.includes('watch-add-none') && none.includes('No ticker or company matches “zzz”'), 'a real empty result says no match')

  assert.equal(model.searchGap({ ok: false, reason: 'provider budget' }), 'provider budget')
  assert.equal(model.searchGap({ schema: 'WatchSymbolSearch@v2', results: [] }), 'unexpected schema WatchSymbolSearch@v2')
  assert.equal(model.searchGap({ schema: 'WatchSymbolSearch@v1' }), 'the search body carries no results list')
  assert.equal(model.searchGap({ schema: 'WatchSymbolSearch@v1', results: [] }), null, 'an empty list on a valid body is not a gap')
  assert.equal(model.searchGap(null), null, 'not read yet is not a gap')
  const gap = html(base({ search: { q: 'qq', submitted: 'qq', loading: false, error: null, hits: [], gap: 'unexpected schema WatchSymbolSearch@v2' } }))
  assert.match(gap, /data-testid="watch-add-gap"[^>]*role="alert"/)
  assert.ok(!gap.includes('watch-add-none'), 'an unreadable body is not "nothing matched"')
}
// 36. WL-12: nothing is read below the minimum query, the box is My List only, and the write is proven by a readback
{
  const btn = h => (h.match(/<button[^>]*data-testid="watch-add-search"[^>]*>[^<]*</) || [''])[0]
  assert.match(btn(html(base({ search: { q: 'A', submitted: '', loading: false, error: null, hits: [], gap: null } }))), /disabled/,
    'one character is not a search')
  const two = btn(html(base({ search: { q: 'AP', submitted: '', loading: false, error: null, hits: [], gap: null } })))
  assert.ok(!/disabled/.test(two), 'two characters is')
  assert.match(btn(html(base({ search: { q: 'AAPL', submitted: 'AAPL', loading: true, error: null, hits: [], gap: null } }))), /Searching…/)
  assert.ok(!html(base({ search: { q: 'AAPL', submitted: 'AAPL', loading: true, error: null, hits: [], gap: null } })).includes('watch-add-hits'),
    'no stale rows while a new search is in flight')
  const box = { q: 'AAPL', submitted: 'AAPL', loading: false, error: null, hits: [], gap: null }
  assert.ok(html(base({ search: box })).includes('data-testid="watch-add-symbol"'), 'the box exists on My List')
  assert.ok(!html(base({ tab: 'suggests', search: box })).includes('watch-add-symbol'), 'and only on My List')
  assert.ok(!html(base()).includes('watch-add-symbol'), 'no search state wired => no dead box')

  assert.ok(/const read = await readOnce<unknown>\(symbolSearchUrl\(q\)\)/.test(listsSrc), 'one bounded read per submitted query')
  assert.ok(/if \(token !== searchToken\.current\) return/.test(listsSrc), 'a slow earlier answer cannot overwrite a newer query')
  assert.ok(/if \(q\.length < SEARCH_MIN_CHARS\)/.test(listsSrc), 'a query below the minimum issues no read')
  assert.ok(/await runSearch\(hit\.symbol\)/.test(listsSrc), 'the add is followed by a readback of the same search')
  assert.ok(/mineAction\(hit\.symbol, 'add', undefined, 'watch\.v002'\)/.test(listsSrc), 'and uses the existing membership command')
}
// 37. WL-14: a Suggestions row states the reason it was selected, or says the read does not carry one — a rank and a
// stage are not a rationale, and a bare row reads as "obviously useful"
{
  const h = html(base({ tab: 'suggests', rows: [
    rowView({ symbol: 'AAA', stage: 'forming', conviction: 86 }),
    rowView({ symbol: 'BBB', stage: 'forming', why: 'rank 2 of the full universe, not on My List' }),
  ] }))
  assert.match(h, /data-testid="watch-rationale-AAA" data-unavailable="1"/)
  assert.ok(h.includes('Selection reason not stated in this read'))
  assert.ok(h.includes('says why the name is useful now'))
  assert.match(h, /data-testid="watch-rationale-BBB" data-unavailable="0"/)
  assert.ok(h.includes('rank 2 of the full universe, not on My List'), 'a stated reason is shown, not replaced')
  assert.equal((h.match(/Selection reason not stated in this read/g) || []).length, 1,
    'the unavailable sentence belongs to the one row without a reason')
  const mine = html(base({ rows: [rowView({ symbol: 'AAA' })] }))
  assert.ok(!mine.includes('watch-rationale-AAA'), 'My List rows make no rationale claim')
  assert.ok(!mine.includes('Selection reason not stated in this read'))
  assert.ok(/data-testid=\{p\.tab === 'suggests' \? `watch-rationale-\$\{r\.symbol\}` : undefined\}/.test(listsSrc),
    'the label is attached only where the rule applies')
}
// 38. WL-15: a dismissal says what it does and how to undo it, and the undo is offered next to its own result (never a
// dead control), issuing the same restore command
{
  const dis = [{ symbol: 'ZZZ', reason: 'overlaps a held name', until: '2031-04-06T00:00:00Z' }]
  const h = html(base({ tab: 'suggests', dismissedItems: dis }))
  assert.ok(h.includes('data-testid="watch-dismissed-policy"'), 'the history explains itself')
  assert.ok(h.includes('Restoring makes it eligible again') && h.includes('does not guarantee'), 'restore is not a promise of ranking')
  assert.ok(h.includes('until 2031-04-06'), 'the expiry is the stored date')
  assert.ok(!h.includes('watch-undo'), 'no undo offer before anything was dismissed here')

  const u = html(base({ tab: 'suggests', undo: { symbol: 'AAPL' }, onUndo: noop }))
  assert.match(u, /data-testid="watch-undo"/)
  assert.ok(u.includes('watch-undo-btn') && u.includes('Undo — restore AAPL'), 'the undo names the name it restores')
  assert.ok(!html(base({ tab: 'suggests', undo: { symbol: 'AAPL' } })).includes('watch-undo'), 'no handler => no dead control')
  const busyBtn = (html(base({ tab: 'suggests', undo: { symbol: 'AAPL' }, onUndo: noop, busy: 'AAPL:restore' })).match(/<button[^>]*watch-undo-btn[^>]*>/) || [''])[0]
  assert.match(busyBtn, /disabled/, 'the undo cannot race its own command')

  assert.ok(/setUndo\(r\.symbol\); return `\$\{r\.symbol\} dismissed for 30 days\.`/.test(listsSrc), 'a dismiss offers the undo')
  assert.ok(/setUndo\(u => \(u === r\.symbol \? null : u\)\)/.test(listsSrc), 'a restore clears the offer for that name')
  assert.ok(/const sym = undo; if \(!sym\) return; void act\(`\$\{sym\}:restore`, async \(\) => \{ await post\('\/api\/v3\/watch\/commands\/suggest-restore', \{ symbol: sym \}\); setUndo\(null\)/.test(listsSrc),
    'the undo is the same restore command, and the offer clears only after it succeeds')
}
// 39. WL-19 — review condition C1 (cc-deepseek-9, finding F2): the prospects grade is proven on the payload the server
// actually sends. A real lane carries no `as_of`, so the grade is the composition clock and says so; a sixteen-hour-old
// composition is STALE, because a fresh wrapper must not certify it. The `source_as_of` branch is asserted as a
// forward contract, not as today's behaviour — and the threshold it inherits is named so it is not inherited silently.
{
  const lane = [{ id: 'forming', label: 'Forming', count: 2, items: [] }]   // the real shape: no as_of
  const fresh = model.gradeProspects({ generated_at: iso(20), lanes: lane }, NOW, 'forming')
  assert.equal(fresh.basis, 'composed_at', 'the real lane shape grades the composition clock and names it')
  assert.equal(fresh.state, 'OK')
  const old = model.gradeProspects({ generated_at: iso(16 * 3600), lanes: lane }, NOW, 'forming')
  assert.equal(old.state, 'STALE', 'a sixteen-hour-old composition is STALE: the wrapper cannot certify it')
  assert.equal(old.basis, 'composed_at')
  const none = model.gradeProspects({ lanes: lane }, NOW, 'forming')
  assert.equal(none.state, 'UNKNOWN', 'no generated_at is UNKNOWN, never fresh')
  // forward contract ONLY (NEEDS BACKEND): the server sends no lane `as_of` today
  const fwd = model.gradeProspects({ generated_at: iso(20), lanes: [{ id: 'forming', as_of: iso(600) }] }, NOW, 'forming')
  assert.equal(fwd.basis, 'source_as_of', 'a lane `as_of`, if the server ever sends one, is the source clock')
  assert.equal(fwd.ageS, 600, 'and its age is measured from that clock, not the composition')
  // the known limitation, encoded so it cannot be inherited silently: that source clock is still graded against the
  // 15-minute COMPOSITION timeout, so a legitimately older source reads STALE. A per-source threshold is NEEDS BACKEND.
  const older = model.gradeProspects({ generated_at: iso(20), lanes: [{ id: 'forming', as_of: iso(2 * 3600) }] }, NOW, 'forming')
  assert.equal(older.state, 'STALE', 'until a per-source threshold exists, an older source clock reads STALE — F2 notes this')
}
// 40. r5c-journeys F1 (SEV-3, cc-opus-3): a Suggestions row showed TWO different numbers under the word "conviction" —
// the row's own "conviction 68 · universe rank #2" and the suggestion's reason "#2 · conviction 86" (live ANRO). They are
// two sources: the row's conviction is the canonical CIO record (`conviction_source: cio_truth`), the reason quotes the
// ranking projection's. Each number is now named by its source; when the two agree the server's wording is left alone.
{
  const anro = { symbol: 'ANRO', conviction: 68.14, conviction_source: 'cio_truth', universe_rank: 2, suggestion: { reason: '#2 · conviction 86' } }
  const row = rowView(anro)
  assert.equal(row.convictionSource, 'cio_truth')
  assert.equal(model.convictionText(row), 'conviction 68 · CIO record · universe rank #2', 'the row number is named by its source')
  assert.equal(row.why, '#2 · ranking-projection conviction 86', 'the reason number is named by ITS source, not left as a second "conviction"')
  const h = html(base({ tab: 'suggests', rows: [row] }))
  assert.ok(h.includes('conviction 68 · CIO record · universe rank #2'))
  assert.ok(h.includes('#2 · ranking-projection conviction 86'))
  assert.equal((h.match(/conviction \d+/g) || []).length, 2, 'both numbers are still stated — named, never silently dropped')
  // Agreement: no second label is invented for one value.
  const same = rowView({ symbol: 'INDV', conviction: 85.4, conviction_source: 'cio_truth', universe_rank: 3, suggestion: { reason: '#3 · conviction 85' } })
  assert.equal(same.why, '#3 · conviction 85', 'equal numbers under two sources need no relabel')
  // No record number to compare against: the server's wording stands (nothing to disambiguate).
  const only = rowView({ symbol: 'EVI', conviction: null, suggestion: { reason: '#4 · conviction 85' } })
  assert.equal(only.why, '#4 · conviction 85')
  assert.equal(model.convictionText(only), 'no score', 'a row without a conviction never borrows the projection number')
  // A source the page has not met is shown verbatim, not guessed.
  assert.equal(model.convictionSourceLabel('something_new'), 'something_new')
  assert.equal(model.convictionSourceLabel('cio_opportunity_projection'), 'curator projection')
  assert.equal(model.convictionSourceLabel(null), null)
  // The LIVE curation body (shape read from :7777 at 16:5xZ): as_of and ranking.as_of are one stamp under basis
  // ranking_projection -> exactly TWO clocks, and "Ranking projection" appears once in the rendered strip.
  const body = { generated_at: iso(20), suggests: { as_of: iso(7200), as_of_basis: 'ranking_projection' }, ranking: { as_of: iso(7200) } }
  const clocks = clocksOf(body, 'suggests', null, NOW)
  assert.equal(clocks.filter(c => c.label === 'Ranking projection').length, 1, 'the ranking clock is printed once')
  const hc = html(base({ tab: 'suggests', clocks }))
  assert.equal((hc.match(/Ranking projection/g) || []).length, 1)
}
// 41. WL-29 — review condition C2 (cc-deepseek-9): each list's count names its population, and a read that repeats a
// symbol is deduped and says so. Counts come only from the body; a field the body omits is left out, never estimated.
{
  const mine = { my_watchlist: { count: 111, unfiltered_count: 111, filters: {} } }
  assert.match(model.populationText('mine', mine), /every membership source.*: 111 names\. No position filters are applied\./)
  const filtered = { my_watchlist: { count: 4, unfiltered_count: 111, filters: { held: true } } }
  assert.match(model.populationText('mine', filtered), /Filtered by held; 111 names before filters\./)
  assert.equal(model.populationText('mine', { my_watchlist: {} }), null, 'no count in the body => no population claim')
  const sug = { suggests: { eligible: 1625, ranked: 1723, universe_note: 'Eligible names from the ranked research universe; Prospects shows a capped stage view.' } }
  const sp = model.populationText('suggests', sug)
  assert.match(sp, /Eligible names from the ranked research universe/)
  assert.match(sp, /1625 of 1723 ranked names are eligible today/)
  assert.match(sp, /excluded here by the server/, 'the cross-list exclusion (mine/held/dismissed) is stated, not assumed')
  const lane = { lane: 'forming', lanes: [{ id: 'forming', label: 'Setup forming', count: 158 }, { id: 'expired', label: 'Expired', count: 59 }] }
  assert.equal(model.populationText('prospects', lane, 'forming'), 'Counts the names the prospect collection currently holds in lane “Setup forming”: 158.')
  assert.equal(model.populationText('prospects', { lanes: [{ id: 'forming' }] }, 'forming'), null, 'a lane with no count says nothing')
  // Dedupe: the same symbol twice renders once and is announced.
  const rows = [rowView({ symbol: 'AAA' }), rowView({ symbol: 'BBB' }), rowView({ symbol: 'AAA', conviction: 90 })]
  const d = model.dedupeRows(rows)
  assert.deepEqual(d.rows.map(r => r.symbol), ['AAA', 'BBB'], 'the first occurrence wins; the duplicate does not render')
  assert.equal(d.repeated, 1)
  assert.ok(html(base({ population: sp, repeated: 1 })).includes('This read carried one name more than once'))
  assert.ok(html(base({ population: sp, repeated: 2 })).includes('2 names more than once'))
  assert.ok(!html(base({})).includes('watch-dedupe'), 'no repeats => no note (never a standing warning)')
  const hp = html(base({ population: sp }))
  assert.ok(hp.includes('data-testid="watch-population"') && hp.includes('1625 of 1723 ranked'), 'the population sentence renders')
  assert.ok(!html(base({ population: null })).includes('watch-population'), 'no population => no empty note')
}
console.log('41 scenarios passed')
