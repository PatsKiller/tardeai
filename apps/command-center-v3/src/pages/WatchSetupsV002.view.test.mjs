// LQ-20261107-2993c: Watch v002 Setups/Sectors/Discover/Alerts rendering. UNKNOWN/STALE are visible, an unread list is never
// an empty list, alerts show the evaluator's certified count and a disarm control. Synthetic fixtures only.
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

const model = await import(compile(join(app, 'src/lib/watchSetupsV002.ts')))
const page = await import(compile(join(app, 'src/pages/WatchSetupsV002.tsx')))
const { gradeStamp, certifiedOf, alertRows, poolRows, sectorRows, findRows, discoveryGap, gradeAlerts, gradePullback, pullbackRows, pullbackProvenance } = model
const { WatchSetupsV002View } = page

const NOW = Date.parse('2031-03-07T15:00:00Z')
const iso = s => new Date(NOW - s * 1000).toISOString()
const noop = () => {}
const base = (o = {}) => ({
  tab: 'setups', grade: gradeStamp(iso(60), 'strategy_watchpool.entered_at', NOW, 3600), loading: false, error: null, message: '',
  offset: 0, total: 60, hasMore: true,
  pool: poolRows({ rows: [{ symbol: 'AAA', strategy_id: 's1', current_status: 'ACTIVE', entered_at: iso(100) }] }),
  sectors: sectorRows({ sectors: [{ sector: 'Tech', count: 3, sample: ['A', 'B'] }] }),
  finds: findRows({ items: [{ symbol: 'FFF', reason: 'breakout' }] }),
  alerts: alertRows({ alerts: [{ id: 7, symbol: 'AXTI', condition_type: 'rsi_below', threshold: 30, active: true }, { id: 8, symbol: 'ZZZ', condition_type: 'rsi_above', threshold: 70, active: false }] }),
  gap: null, certified: null, pullback: [], pullbackInfo: null, onPage: noop, onDisarm: noop, onRetry: noop, ...o,
})
const html = p => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WatchSetupsV002View, p)))
const asof = h => (h.match(/data-testid="setups-asof"[^>]*>/) || [''])[0]

// 1. setups: OK, row + detail link, paging
{
  const h = html(base())
  assert.match(asof(h), /data-state="OK"/)
  assert.ok(h.includes('data-testid="setup-AAA"') && h.includes('href="/watch/intelligence/AAA"'))
  assert.match(h, /1–1 of 60/)
}
// 2. stale and unknown are visible
{
  assert.match(asof(html(base({ grade: gradeStamp(iso(7200), 'b', NOW, 3600) }))), /data-state="STALE"/)
  assert.match(asof(html(base({ grade: gradeStamp(null, null, NOW, 3600) }))), /data-state="UNKNOWN"/)
}
// 3. unread is not empty
{
  const h = html(base({ grade: null, pool: [], error: 'HTTP 503' }))
  assert.match(asof(h), /data-state="UNKNOWN"/)
  assert.ok(h.includes('setups-error') && h.includes('Retry'))
  assert.ok(!h.includes('setups-empty') && !h.includes('No setups'))
}
// 4. loading
assert.match(asof(html(base({ grade: null, loading: true }))), /data-state="LOADING"/)
// 5. genuinely empty
assert.ok(html(base({ pool: [], total: 0 })).includes('No setups in the watchpool.'))
// 6. sectors + discover rows
assert.ok(html(base({ tab: 'sectors' })).includes('data-testid="sector-Tech"'))
assert.ok(html(base({ tab: 'discover' })).includes('data-testid="find-FFF"'))
// 7. alerts: certified line, mismatch flag, disarm only on armed rows
{
  const certified = certifiedOf({ active_count: 1, evaluator: { certified: { armed: 3, runs_24h: 20, fired_24h: 0 } } })
  const h = html(base({ tab: 'alerts', certified }))
  assert.match(h, /data-testid="alerts-certified" data-mismatch="1"/)
  assert.ok(h.includes('data-testid="alert-disarm-7"') && !h.includes('alert-disarm-8'))
  assert.ok(!h.includes('setups-paging'), 'paging is for setups only')
  const none = html(base({ tab: 'alerts', certified: certifiedOf({ evaluator: { certified: null } }) }))
  assert.match(none, /No certified count/)
}
// 8. Next disabled without more pages
assert.match(html(base({ hasMore: false })), /<button[^>]*disabled[^>]*>Next/)
// 9. R6: toned chips (STALE is not styled like OK), ET times, no inline styles
{
  assert.match(html(base()), /v010-pill ok/)
  assert.match(html(base({ grade: gradeStamp(iso(7200), 'b', NOW, 3600) })), /v010-pill warn/)
  assert.match(html(base({ grade: gradeStamp(null, null, NOW, 3600) })), /v010-pill bad/)
  const h = html(base({ pool: poolRows({ rows: [{ symbol: 'AAA', entered_at: '2026-11-12T18:20:00Z' }] }) }))
  assert.match(h, /entered Nov 12, 1:20 PM ET/); assert.ok(!h.includes('2026-11-12T18'))
  assert.ok(!/style="/.test(html(base({ tab: 'alerts' }))), 'no inline styles')
  const a = html(base({ tab: 'alerts', alerts: alertRows({ alerts: [{ id: 1, symbol: 'AXTI', condition_type: 'rsi_below', threshold: 30, active: true, last_fired_at: '2026-11-12T18:20:00Z' }] }) }))
  assert.match(a, /fired Nov 12, 1:20 PM ET/)
}
// 10. R1: a crashing evaluator renders STALE (toned), never OK
{
  const body = { evaluator: { readable: true, last_run_at: iso(60), last_ok_at: iso(3 * 86400), last_rc: 1, last_error: 'db down' } }
  const h = html(base({ tab: 'alerts', grade: gradeAlerts(body, NOW) }))
  assert.match(asof(h), /data-state="STALE"/); assert.match(h, /v010-pill warn/); assert.match(h, /failed \(rc 1: db down\)/)
}
// 11. R2: an unknown armed count renders as unknown (warn), never "armed 0"
{
  const certified = certifiedOf({ active_count: 3, evaluator: { certified: { armed: null, runs_24h: 2, ok_runs_24h: 2, fired_24h: 0, as_of: iso(60) } } }, NOW)
  const h = html(base({ tab: 'alerts', certified }))
  assert.match(h, /data-testid="alerts-certified"[^>]*data-unknown="1"/); assert.match(h, /armed count unknown/); assert.ok(!/armed 0/.test(h))
}
// 12. R3: Discover shows the dead feed as a labelled gap beside a pins-clock grade; the gap is only on Discover
{
  const gap = discoveryGap({ feeds: { watch_candidate_events: { gap: { kind: 'no_producer', last_as_of: '2026-07-16T17:00:00Z' } } } })
  const h = html(base({ tab: 'discover', gap }))
  assert.match(h, /data-testid="discover-feed-gap"[^>]*>Discovery feed: no producer; last event Jul 16, 1:00 PM ET/)
  assert.ok(!html(base({ tab: 'sectors', gap })).includes('discover-feed-gap'))
  assert.ok(html(base({ tab: 'discover', finds: [] })).includes('No saved screener finds.'))
}
// 13. R4: a tab switch remounts the tab (a body from another tab is never graded), and the page shows LOADING first
{
  const src = readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8')
  assert.match(src, /<WatchSetupsTab key=\{tab\} /, 'tab host must be keyed by tab')
  for (const t of ['alerts', 'discover', 'sectors', 'setups']) {
    const h = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [`/watch-setups?tab=${t}`] }, React.createElement(page.default)))
    assert.match(asof(h), /data-state="LOADING"/, `${t} first paint is LOADING, with no body`)
    assert.ok(!/data-testid="(alert|find|sector|setup)-/.test(h) && !h.includes('watch-setups-empty'))
  }
}
// 14. Disarm never claims a stored change the POST cannot prove
{
  const src = readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8')
  assert.ok(!/alert disarmed\./.test(src), 'no "alert disarmed." claim')
  assert.match(src, /Disarm sent for/)
}
// 15. W-04: the shared sub-nav renders on Setups too and marks the tab the URL asks for
{
  const h = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/watch-setups?tab=alerts'] },
    React.createElement(page.default)))
  const full = k => (h.match(new RegExp(`<(?:a|span)[^>]*data-testid="watch-subnav-${k}"[^>]*>`)) || [''])[0]
  assert.match(full('alerts'), /^<span/); assert.match(full('alerts'), /aria-current="page"/)
  assert.match(full('setups'), /^<a/); assert.match(full('setups'), /href="\/watch-setups"/)
  assert.match(full('overview'), /^<a/); assert.match(full('overview'), /href="\/watch"/)
  // every tab is in-page now: none of them points at the classic hub
  const nav = (h.match(/<nav[^>]*data-testid="watch-subnav"[^>]*>[\s\S]*?<\/nav>/) || [''])[0]
  assert.ok(nav && !nav.includes('/watch-classic'), 'no tab points at the classic hub')
  assert.match(nav, /href="\/watch-setups\?tab=pullback"/)
}
// 16. W-04 in-page: Pullback/MACD draws its own candidates (trigger, watch, held near stop, why-not) and the scan's
//     provenance; no scan on record is UNKNOWN, never "no candidates".
{
  const pb = pullbackRows({ candidates: [
    { symbol: 'TGT', tier: 'trigger', price: 101.5, pullback_pct: 4.2, macd_prox_pct: 0.8, entry: 101, stop: 97, target1: 112, rr: 2.75, score: 84,
      proposal_live: true, proposal_status: 'PENDING', held: { near_stop: true, reason: 'held' }, held_conflict: true, first_seen_at: iso(3600) },
    { symbol: 'WCH', tier: 'watch', score: 61, why_not: 'histogram still falling', proposal_live: null },
  ] })
  const info = pullbackProvenance({ candidates: [], trigger_count: 1, trigger_live_count: 1, trigger_stale_count: 0, watch_count: 1, held_count: 1,
    dismissed_in_cooldown: 2, scan_provenance: { universe: 'S&P 500 uptrend pullbacks', screened: 498 }, generated_at: iso(1800),
    hit_stats: { window_days: 90, triggers: 12, target1_first: 5, evaluated: 9, median_days: 6 } })
  const h = html(base({ tab: 'pullback', grade: gradePullback({ generated_at: iso(1800) }, NOW), pullback: pb, pullbackInfo: info }))
  assert.match(h, /data-testid="pullback-rows"/)
  assert.match(h, /data-testid="pullback-TGT" data-tier="trigger" data-held-conflict="1"/)
  assert.match(h, /HELD · near stop/); assert.match(h, /in queue/)
  assert.match(h, /data-testid="pullback-WCH" data-tier="watch" data-held-conflict="0"/)
  assert.match(h, /why not a trigger: histogram still falling/)
  assert.match(h, /data-testid="pullback-provenance"[\s\S]*S&amp;P 500 uptrend pullbacks · 498 screened · 1 trigger \(1 with a live proposal\) · 1 watch · 1 held · 2 in dismissal cooldown · last scan /)
  assert.match(h, /90-day record: 5\/12 reached target 1 first, median 6 d/)
  // a scan that never ran: UNKNOWN with the reason, and no invented "no candidates"
  const hn = html(base({ tab: 'pullback', grade: gradePullback({}, NOW), pullback: [], pullbackInfo: null }))
  assert.match(hn, /data-testid="pullback-no-scan"/)
  assert.ok(!hn.includes('No pullback candidates from the last scan'))
  // a scan whose body omits its counts must not read as "0 triggers"
  const hp = html(base({ tab: 'pullback', grade: gradePullback({ generated_at: iso(1800) }, NOW), pullback: [], pullbackInfo: pullbackProvenance({ generated_at: iso(1800) }) }))
  assert.match(hp, /scan counts not reported/)
  assert.ok(!/0 triggers/.test(hp), 'an unstated count is not drawn as 0')
  // a scan that ran and found nothing says exactly that
  const he = html(base({ tab: 'pullback', grade: gradePullback({ generated_at: iso(1800) }, NOW), pullback: [], pullbackInfo: info }))
  assert.ok(he.includes('No pullback candidates from the last scan') && !he.includes('pullback-no-scan'))
}
console.log('16 scenarios passed')
