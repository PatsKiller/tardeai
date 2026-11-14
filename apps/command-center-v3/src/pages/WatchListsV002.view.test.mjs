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
const { gradeList, rowView, pagingOf } = model
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
console.log('16 scenarios passed')
