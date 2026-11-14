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
// active lane's cap overflow is named — a lane the payload does not carry is never invented on the page
{
  const body = { generated_at: iso(20), lanes: [
    { id: 'actionable', label: 'Actionable', count: 3, as_of: iso(60), items: [] },
    { id: 'forming', label: 'Forming', count: 12, as_of: iso(60), overflow: ['CCC', 'DDD'], items: [] },
    { id: 'reentry', label: 'Re-entry', count: null, as_of: iso(60), items: [] },
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
  const sug = clocksOf({ generated_at: iso(20), suggests: { as_of: iso(3600), as_of_basis: 'ranking_projection' }, ranking: { as_of: iso(3600) } }, 'suggests', null, NOW)
  assert.deepEqual(sug.map(c => c.id), ['composed_at', 'source_as_of', 'ranking_as_of'])
  assert.equal(sug[1].label, 'Ranking projection', 'the basis string names the producer side')
  const pro = clocksOf({ generated_at: iso(20), lanes: [{ id: 'forming', as_of: iso(600) }, { id: 'actionable', as_of: iso(30) }] }, 'prospects', 'forming', NOW)
  assert.deepEqual(pro.map(c => [c.id, c.ageS]), [['composed_at', 20], ['source_as_of', 600]], 'the SELECTED lane is the source clock')
  assert.deepEqual(clocksOf({}, 'mine', null, NOW), [], 'a body with no timestamps claims no clock')
  const h = html(base({ clocks: mine }))
  assert.ok(h.includes('data-testid="watch-list-clocks"'))
  assert.match(h, /data-clock="source_as_of"/); assert.ok(h.includes('15 min old'), 'the source age is shown next to its stamp')
  assert.ok(!html(base({ clocks: [] })).includes('watch-list-clocks'), 'no clocks, no block')
}
console.log('27 scenarios passed')
