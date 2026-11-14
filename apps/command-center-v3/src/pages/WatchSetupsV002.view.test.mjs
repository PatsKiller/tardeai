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
const disc = await import(compile(join(app, 'src/lib/watchDiscoverV002.ts')))
const recent = await import(compile(join(app, 'src/pages/WatchDiscoverRecentV002.tsx')))
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
// 14. Disarm never claims a stored change the POST cannot prove (the message lives in the lib's disarmAlert)
{
  const src = readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8')
  const libSrc = readFileSync(join(app, 'src/lib/watchSetupsV002.ts'), 'utf8')
  assert.ok(!/alert disarmed\./.test(src + libSrc), 'no "alert disarmed." claim')
  assert.match(libSrc, /Disarm sent for/)
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
// 17. S7/WR-03+WR-02+WR-01: the Sectors context is auditable — absolute ET, named producer, the limit, momentum UNKNOWN
//     (never derived from counts) and a raw-label note; sample symbols are real links to symbol detail.
{
  const body = { sectors: [{ sector: 'Healthcare', count: 483, sample: ['AARD', 'ABBV'] }], as_of: iso(420), as_of_basis: 'incubator_universe.updated_at' }
  const ctx = model.sectorContext(body, NOW)
  assert.equal(ctx.producer, 'incubator universe refresh')
  assert.match(ctx.asOfText, /ET$/)
  const h = html(base({ tab: 'sectors', sectors: sectorRows(body), sectorCtx: ctx }))
  assert.match(h, /data-testid="sectors-source">incubator universe refresh · updated .* ET · limit 36 h/)
  assert.match(h, /data-testid="sectors-momentum">Sector strength: UNKNOWN — No sector momentum\/strength projection exists in this build\./)
  assert.match(h, /data-testid="sectors-label-note">Counts are per raw provider sector label/)
  assert.match(h, /data-testid="sector-Healthcare"[\s\S]*href="\/watch\/intelligence\/AARD"/)
  // an absent stamp: no invented time, the context still names the producer and the limit
  const none = model.sectorContext({ sectors: [] }, NOW)
  assert.equal(none.asOfText, null)
  assert.ok(!html(base({ tab: 'sectors', sectorCtx: none })).includes('updated '))
}
// 18. S7/WR-07: a row's pill is the DEFINITION's state, and the evaluator is its own source card. An armed definition
//     under an unknown evaluator can never read as monitoring assurance.
{
  const evSrc = model.evaluatorSource({ evaluator: { readable: true, last_run_at: null, last_ok_at: null, last_rc: null } }, NOW)
  const h = html(base({ tab: 'alerts', evaluatorSrc: evSrc }))
  assert.match(h, /definition armed/)
  // WR-09 made Active the default side, so the disarmed definition's pill is checked on History — the same row and the
  // same label string; the assertion's intent (the pill is the definition's state, both ways) is unchanged.
  const hist = html(base({ tab: 'alerts', evaluatorSrc: evSrc, alertView: { filter: 'history', q: '', page: 1 } }))
  assert.match(hist, /definition disarmed/)
  assert.ok(!/>armed</.test(h + hist), 'no bare "armed" pill')
  assert.match(h, /data-testid="alerts-evaluator" data-state="UNKNOWN">Evaluator UNKNOWN: watch_alerts_eval\.py · every 20 min, 09:00–16:00 ET, Mon–Fri · no successful run on record\. Row state below is the alert definition/)
  const ok = model.evaluatorSource({ evaluator: { readable: true, last_ok_at: iso(300), last_rc: 0 } }, NOW)
  assert.equal(ok.state, 'OK'); assert.match(ok.record, /last successful run /)
}
// 19. S7/WR-08: the alert symbol opens symbol detail (a real next step), and disarm stays the only mutation.
{
  const h = html(base({ tab: 'alerts' }))
  assert.match(h, /<a[^>]*href="\/watch\/intelligence\/AXTI"[^>]*>AXTI<\/a>/)
  assert.match(h, /data-testid="alert-disarm-7"/)
  // a row with no symbol never fabricates a link
  const noSym = html(base({ tab: 'alerts', alerts: alertRows({ alerts: [{ id: 9, directive_id: 'D9', active: true }] }) }))
  assert.ok(!/watch\/intelligence\/D9/.test(noSym) && noSym.includes('>D9<'))
}
// 20. S7/WR-10: signal and proposal are separate named facts; a dead proposal is drawn BEFORE the plan numbers and the
//     plan numbers are labelled as scan assumptions.
{
  assert.equal(model.proposalState(false, 'REJECTED').key, 'rejected')
  assert.equal(model.proposalState(false, 'EXPIRED').key, 'expired')
  assert.equal(model.proposalState(false, 'PENDING').key, 'stale')
  assert.equal(model.proposalState(null, null).key, 'missing')
  assert.equal(model.proposalState(true, 'PENDING').blocking, false)
  assert.equal(model.signalText('trigger'), 'Signal: triggered')
  const rows = pullbackRows({ candidates: [
    { symbol: 'VLO', tier: 'trigger', entry: 100, stop: 90, target1: 120, proposal_live: false, proposal_status: 'REJECTED' },
    { symbol: 'NOP', tier: 'trigger', entry: 50, proposal_live: null },
    { symbol: 'LIVE', tier: 'watch', proposal_live: true, proposal_status: 'PENDING' },
  ] })
  const h = html(base({ tab: 'pullback', grade: gradePullback({ generated_at: iso(1800) }, NOW), pullback: rows }))
  assert.match(h, /data-testid="pullback-signal-VLO">Signal: triggered</)
  const rejected = (h.match(/data-testid="pullback-proposal-VLO"[^>]*>[^<]*/) || [''])[0]
  assert.match(rejected, /data-proposal="rejected"[^>]*>Proposal: rejected — no live proposal/)
  assert.ok(h.indexOf('data-testid="pullback-proposal-VLO"') < h.indexOf('scan plan entry 100'), 'blocking state precedes the plan numbers')
  assert.match(h, /Proposal: none — no live proposal/)
  assert.match(h, /data-testid="pullback-signal-LIVE">Signal: watch</)
  assert.match(h, /Proposal: in queue/)
  assert.match(h, /scan plan entry 100 · stop 90 · target 120 \(assumptions as of the last scan\)/)
  assert.ok(!/place order|buy now|submit order/i.test(h), 'no order affordance')
}
// 21. S7/WR-11: the scan stamp never stands in for monitor, quote or per-candidate evaluation — all three render UNKNOWN.
{
  const info = pullbackProvenance({ generated_at: iso(1800), scan_provenance: { universe: 'S&P 500', screened: 10 } })
  assert.equal(info.monitor, null); assert.equal(info.quote, null); assert.equal(info.candidateEvaluated, null)
  const h = html(base({ tab: 'pullback', grade: gradePullback({ generated_at: iso(1800) }, NOW), pullback: pullbackRows({ candidates: [{ symbol: 'AAA' }] }), pullbackInfo: info }))
  assert.match(h, /· monitor UNKNOWN \(no monitor stamp in this read\)/)
  assert.match(h, /· quote UNKNOWN \(no quote time in this read\)/)
  assert.match(h, /· candidate last evaluated UNKNOWN \(first seen is not last evaluated\)/)
}
// 22. S7/WR-05: Discover renders two sources with two clocks and two independent states; a dead feed cannot grade pins.
{
  const body = { items: [{ symbol: 'FFF', reason: 'breakout' }], pins_as_of: iso(3600), pins_as_of_basis: 'screener_find_pins',
    feeds: { watch_candidate_events: { gap: { kind: 'no_producer', last_as_of: '2026-07-16T17:00:00Z' } } } }
  const cards = model.discoverCards(body, NOW, 1) // the same call the page host makes, with the same defaults
  const h = html(base({ tab: 'discover', finds: findRows(body), cards }))
  const feed = (h.match(/data-testid="discover-card-feed"[^>]*>[\s\S]*?<\/span>/) || [''])[0]
  const pins = (h.match(/data-testid="discover-card-pins"[^>]*>[\s\S]*?<\/span>/) || [''])[0]
  assert.match(feed, /data-state="UNKNOWN"[\s\S]*Discovery feed<\/strong>: UNKNOWN — no producer; last event Jul 16, 1:00 PM ET/)
  assert.match(pins, /data-state="OK"[\s\S]*Saved screener finds<\/strong>: OK — 1 find · pins as of /)
  // a fresh body with no feed block is not a fresh feed: the feed clock is missing, not OK
  const noFeed = model.discoverCards({ pins_as_of: iso(60) }, NOW, 0)
  assert.equal(noFeed[0].state, 'UNKNOWN'); assert.match(noFeed[0].detail, /missing/)
}
// 23. S7/WR-X3 journey: the disarm ACTION (not the render) — accepted is not stored; a failure keeps state and names it;
//     the component refetches only on an accepted POST.
{
  const ok = await model.disarmAlert(7, 'AXTI', async () => ({ ok: true, status: 200, body: { ok: true } }))
  assert.equal(ok.ok, true)
  assert.match(ok.message, /^Disarm sent for AXTI\. Check the row below: it reads "definition disarmed" once the change is stored\.$/)
  const refused = await model.disarmAlert(7, 'AXTI', async () => ({ ok: false, status: 503, body: { ok: false, error: 'db down' } }))
  assert.equal(refused.ok, false); assert.match(refused.message, /^Failed: db down/)
  const thrown = await model.disarmAlert(7, 'AXTI', async () => { throw new Error('network') })
  assert.equal(thrown.ok, false); assert.match(thrown.message, /^Failed: network/)
  const src = readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8')
  assert.match(src, /if \(out\.ok\) refetch\(\)/, 'readback only after an accepted POST')
}
// 24. S7/WR-04/WR-05 journey: discoveries carry their source, reason and captured time; the add is proven by a membership
//     READBACK, never by the POST's accepted answer; a readback that omits the symbol is UNKNOWN, not "not in My List".
{
  const body = { ok: true, data: [
    { symbol: 'XYZ', source_key: 'finviz', source_confidence: 0.8, reason: 'breakout volume', created_at: iso(600), degraded: false, normalized_payload: {} },
    { source_key: 'hermes', symbol: '', created_at: iso(60) },
  ] }
  const rows = disc.discoveryRows(body)
  assert.deepEqual(rows, [{ symbol: 'XYZ', source: 'finviz', reason: 'breakout volume', at: iso(600), degraded: false }])
  const clock = disc.discoveryClock(rows, NOW)
  assert.equal(clock.state, 'OK'); assert.match(clock.asOfText, /ET$/)
  assert.equal(disc.discoveryClock([], NOW).state, 'UNKNOWN', 'no window is not a green read')
  assert.equal(disc.discoveryRows({ data: [{ symbol: 'old', created_at: iso(60 * 3600) }] }).length, 1)
  assert.equal(disc.discoveryClock(disc.discoveryRows({ data: [{ symbol: 'OLD', created_at: iso(40 * 3600) }] }), NOW).state, 'STALE')
  // Schedule-aware grading (lead 09:40 item 1): the producer is the premarket step candidate_discovery_orchestrator,
  // weekdays 05:45 ET — no weekend run. NOW is Friday 2031-03-07 10:00 ET.
  assert.ok(clock.nextText && /ET$/.test(clock.nextText), 'the clock always names the next scheduled run')
  const friRow = disc.discoveryRows({ data: [{ symbol: 'FRI', created_at: '2031-03-07T10:51:00Z' }] }) // Fri 05:51 ET
  assert.equal(disc.discoveryClock(friRow, NOW).state, 'OK', "a row from this morning's run is OK")
  assert.equal(disc.discoveryClock(friRow, Date.parse('2031-03-08T15:00:00Z')).state, 'OK', 'Saturday: no run was due, so age is not staleness')
  assert.equal(disc.discoveryClock(friRow, Date.parse('2031-03-09T22:00:00Z')).state, 'OK', 'Sunday evening: still OK before Monday 05:45')
  const miss = disc.discoveryClock(friRow, Date.parse('2031-03-10T15:00:00Z')) // Monday 11:00 ET — Monday's run is overdue
  assert.equal(miss.state, 'STALE', 'a missed weekday run is STALE, not a calm age')
  assert.match(miss.recovery ?? '', /logs\/candidate_discovery\.log.*candidate_discovery_orchestrator/)
  assert.match(miss.nextText ?? '', /Mar 11/, 'the stale clock names the next run')
  assert.equal(disc.discoveryClock(friRow, Date.parse('2031-03-10T09:50:00Z')).state, 'OK', 'inside the run window the prior run is graded')
  const ok = await disc.addToMyList('XYZ', async b => {
    assert.deepEqual(b, { symbol: 'XYZ', strategy_type: 'discovery', source: 'discovery' })
    return { ok: true, status: 200, body: { ok: true, data: { symbol: 'XYZ', added: true } } }
  })
  assert.equal(ok.ok, true); assert.match(ok.message, /readback below decides/)
  const bad = await disc.addToMyList('XYZ', async () => ({ ok: false, status: 500, body: { ok: false, error: 'db down' } }))
  assert.equal(bad.ok, false); assert.match(bad.message, /^Failed: db down/)
  assert.equal(disc.isInMyList({ symbols: [{ symbol: 'XYZ', in_ai_watchlist: true }] }, 'xyz'), true)
  assert.equal(disc.isInMyList({ symbols: [{ symbol: 'XYZ', in_ai_watchlist: false }] }, 'XYZ'), false)
  assert.equal(disc.isInMyList({ symbols: [] }, 'XYZ'), null)
  assert.equal(disc.isInMyList(null, 'XYZ'), null)
}
// 25. S7/WR-04: the Recent discoveries panel renders loading, empty, error and populated distinctly; an empty successful
//     read says so, a read failure says it failed, and only a readback-confirmed membership hides the Add control.
{
  const V = recent.WatchDiscoverRecentV002View
  const clock = disc.discoveryClock([], NOW)
  const h = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows: [], clock, loading: false, error: null, message: '', member: {}, onAdd: noop })))
  assert.match(h, /data-testid="discover-recent-clock" data-state="UNKNOWN"><strong>Recent discoveries<\/strong>: no window · candidate-discovery events/)
  assert.match(h, /data-testid="discover-recent-empty">No discovery events in the returned window\. That is an empty successful read, not unread data\./)
  const loads = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows: [], clock, loading: true, error: null, message: '', member: {}, onAdd: noop })))
  assert.ok(loads.includes('Loading…') && !loads.includes('discover-recent-empty'), 'loading is not empty')
  const err = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows: [], clock, loading: false, error: 'HTTP 503', message: '', member: {}, onAdd: noop })))
  assert.match(err, /data-testid="discover-recent-error">Discoveries could not be read: HTTP 503/)
  // STALE names the missed run and its recovery action (lead 09:40 item 1); OK/UNKNOWN do not.
  const staleRows = disc.discoveryRows({ data: [{ symbol: 'OLD', created_at: iso(40 * 3600) }] })
  const stale = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows: staleRows, clock: disc.discoveryClock(staleRows, NOW), loading: false, error: null, message: '', member: {}, onAdd: noop })))
  assert.match(stale, /data-testid="discover-recent-clock" data-state="STALE"/)
  assert.match(stale, /data-testid="discover-recent-recovery" role="alert">A scheduled run produced no discoveries\. [^<]*candidate_discovery_orchestrator/)
  const okRows = disc.discoveryRows({ data: [{ symbol: 'XYZ', created_at: iso(300) }] })
  const okH = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows: okRows, clock: disc.discoveryClock(okRows, NOW), loading: false, error: null, message: '', member: {}, onAdd: noop })))
  assert.ok(!okH.includes('discover-recent-recovery'), 'an OK read names no recovery')
  assert.match(okH, /next run [^<]*ET/)
  const rows = disc.discoveryRows({ data: [{ symbol: 'XYZ', source_key: 'finviz', reason: 'breakout', created_at: iso(300), degraded: true }] })
  const okClock = disc.discoveryClock(rows, NOW)
  const rowH = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows, clock: okClock, loading: false, error: null, message: '', member: {}, onAdd: noop })))
  assert.match(rowH, /data-testid="discovery-XYZ"[\s\S]*href="\/watch\/intelligence\/XYZ"[\s\S]*finviz[\s\S]*breakout[\s\S]*degraded source/)
  assert.match(rowH, /data-testid="discovery-add-XYZ"/)
  const inList = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows, clock: okClock, loading: false, error: null, message: '', member: { XYZ: true }, onAdd: noop })))
  assert.ok(inList.includes('in My List') && !inList.includes('discovery-add-XYZ'), 'a readback-confirmed row has no Add button')
  // Review F1: an unread membership is a THIRD state, labelled — the Add button never speaks for it.
  assert.match(rowH, /data-testid="discovery-membership-XYZ" data-membership="unread">membership not checked/)
  const unread = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows, clock: okClock, loading: false, error: null, message: '', member: {}, onAdd: noop })))
  assert.match(unread, /data-membership="unread">membership not checked/)
  const unknown = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows, clock: okClock, loading: false, error: null, message: '', member: { XYZ: null }, onAdd: noop })))
  assert.match(unknown, /data-membership="unknown">membership UNKNOWN — the readback did not include this symbol/)
  assert.match(unknown, /data-testid="discovery-add-XYZ"/, 'UNKNOWN keeps the control, it does not claim "in list"')
  // Review F2: `false` is reachable (the readback is read unfiltered), and a known membership is labelled nothing.
  const notIn = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(V, { rows, clock: okClock, loading: false, error: null, message: '', member: { XYZ: false }, onAdd: noop })))
  assert.match(notIn, /data-testid="discovery-add-XYZ"/)
  assert.ok(!notIn.includes('membership UNKNOWN') && !notIn.includes('membership not checked'), 'a known membership needs no unknown label')
  // Review F4: no write on read — the only POST in the panel lives inside add().
  const panelSrc = readFileSync(join(app, 'src/pages/WatchDiscoverRecentV002.tsx'), 'utf8')
  assert.equal((panelSrc.match(/method:\s*'POST'/g) || []).length, 1, 'exactly one POST in the panel')
  const postAt = panelSrc.indexOf("method: 'POST'")
  assert.ok(postAt > panelSrc.indexOf('const add = async') && postAt < panelSrc.indexOf('return <WatchDiscoverRecentV002View'),
    'the only POST is inside add(); the read path is GET')
  assert.match(panelSrc, /fetch\(MEMBERSHIP_API, \{ cache: 'no-store' \}\)/, 'the membership read is a GET')
  // Review b2r2 R1: the readback URL is pinned BY VALUE. Reverting it to the source-filtered form (?source=ai_watchlist)
  // would leave every other assertion green, so the value itself is the test.
  assert.equal(disc.MEMBERSHIP_API, '/api/v2/watchlist/symbols?sort=updated', 'the readback must be the unfiltered list')
  assert.ok(!panelSrc.includes('source=ai_watchlist'), 'the readback must not be filtered to the armed subset')
}
// 26. S7/WR-09: the 100-row mixed list splits into current attention and history, the listed totals are the READ's
// counts (and the endpoint's 100-row cap is named, never a census), search narrows, and paging is per side.
{
  const rows = model.alertRows({ alerts: [
    ...Array.from({ length: 18 }, (_, i) => ({ id: 100 + i, symbol: 'AAA', condition_type: 'price_cross_below', threshold: 100 + i, active: true, recurring: true, cooldown_days: 5 })),
    ...Array.from({ length: 82 }, (_, i) => ({ id: 200 + i, symbol: 'BBB', condition_type: i % 2 ? 'rsi_below' : 'price_cross_above', threshold: 200 + i, active: false })),
  ] })
  const act = html(base({ tab: 'alerts', alerts: rows }))
  // Acceptance: listed totals reconcile to 18 active and 82 inactive for this fixture; certified totals stay elsewhere.
  assert.match(act, /data-testid="alerts-totals" data-capped="1">18 armed · 82 disarmed in the 100 definitions read\. The list endpoint returns at most 100 rows and reports no total, so how many more definitions exist beyond this read is UNKNOWN\./)
  assert.match(act, /aria-pressed="true"[^>]*data-testid="alerts-filter-active"/, 'Active is the default side')
  assert.match(act, /aria-pressed="false"[^>]*data-testid="alerts-filter-history"/)
  assert.match(act, /Active \(18\)/); assert.match(act, /History \(82\)/)
  assert.ok(act.includes('data-testid="alert-100"') && !act.includes('data-testid="alert-200"'), 'history is not mixed into Active')
  assert.match(act, /data-testid="alerts-paging">.*?1–18 of 18/)
  const hist = html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'history', q: '', page: 1 } }))
  assert.match(hist, /aria-pressed="true"[^>]*data-testid="alerts-filter-history"/)
  assert.ok(hist.includes('data-testid="alert-200"') && !hist.includes('data-testid="alert-100"'))
  assert.match(hist, /1–20 of 82/)
  assert.match(html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'history', q: '', page: 2 } })), /21–40 of 82/)
  assert.match(html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'history', q: '', page: 99 } })), /81–82 of 82/,
    'an out-of-range page clamps to the last page instead of showing an empty page')
  // search is per side
  // search narrows within the side: 41 of the 82 history rows are rsi_below, paged at 20
  assert.match(html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'history', q: 'rsi', page: 1 } })), /1–20 of 41/)
  const miss = html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'active', q: 'rsi', page: 1 } }))
  assert.match(miss, /data-testid="alerts-empty-filter">No armed definition matches &quot;rsi&quot;\. 82 disarmed definitions are in History\./)
  assert.ok(!miss.includes('data-testid="alert-100"'))
  // a read that is NOT capped says so instead of implying a census
  const short = html(base({ tab: 'alerts', alerts: model.alertRows({ alerts: [{ id: 1, symbol: 'A', condition_type: 'rsi_below', active: true }] }) }))
  assert.match(short, /data-capped="0">1 armed · 0 disarmed in the 1 definition read\. The endpoint returned every definition it holds\./)
}
// 27. S7/WR-09: a row explains its own lifecycle from the fields the evaluator branches on (one-shot is spent by the
// evaluator; a repeating disarm is an API action), last fire is separate from enabled state, ids make identical
// thresholds distinguishable, and duplicates are review context that nothing merges.
{
  const rows = model.alertRows({ alerts: [
    { id: 1, symbol: 'AXTI', condition_type: 'price_cross_below', threshold: 7.47, active: true, recurring: false, created_at: '2026-11-01T15:00:00Z' },
    { id: 2, symbol: 'QQQ', condition_type: 'price_cross_above', threshold: 500, active: true, recurring: true, cooldown_days: 5, last_fired_at: '2026-11-12T15:00:00Z' },
    { id: 3, symbol: 'AXTI', condition_type: 'price_cross_below', threshold: 7.47, active: false, recurring: false, last_fired_at: '2026-10-27T16:00:00Z' },
    { id: 4, symbol: 'SPY', condition_type: 'rsi_above', threshold: 70, active: false, recurring: true, last_fired_at: '2026-11-01T15:00:00Z' },
    { id: 5, symbol: 'V', condition_type: 'price_cross_below', threshold: 300, active: false },
  ] })
  const act = html(base({ tab: 'alerts', alerts: rows }))
  assert.match(act, /data-testid="alert-policy-1">one-shot/)
  assert.match(act, /data-testid="alert-1"[^>]*data-lifecycle="armed-one-shot"/)
  assert.match(act, /data-testid="alert-lifecycle-1">armed · one-shot — One-shot: the evaluator disarms it when it fires, and a definition that has fired never fires again\./)
  assert.match(act, /data-testid="alert-policy-2">repeats · cooldown 5 d/)
  assert.match(act, /data-testid="alert-2"[^>]*data-lifecycle="armed-repeating"/)
  assert.match(act, /data-testid="alert-lifecycle-2">armed · repeating — Repeating: the evaluator leaves it armed after a fire and will not fire it again for about 7 days \(cooldown 5 d × 1\.4 trading-day approximation\), at most once per UTC day\./)
  assert.match(act, /last fired Nov 12, 10:00 AM ET/, 'last fire is its own fact, not the enabled state')
  assert.match(act, /never fired/)
  assert.match(act, /data-testid="alert-id-1">#1</, 'the id is rendered, so identical thresholds differ')
  const his = html(base({ tab: 'alerts', alerts: rows, alertView: { filter: 'history', q: '', page: 1 } }))
  assert.match(his, /data-testid="alert-3"[^>]*data-lifecycle="spent-one-shot"/)
  assert.match(his, /data-testid="alert-lifecycle-3">spent · disarmed by the evaluator — One-shot that fired: the evaluator set it disarmed on the fire, and it will not fire again\./)
  assert.match(his, /data-testid="alert-4"[^>]*data-lifecycle="disarmed-after-fire"/)
  assert.match(his, /Only the alerts API disarms a repeating definition, so this was a disarm action, not the evaluator\./)
  assert.match(his, /data-testid="alert-5"[^>]*data-lifecycle="disarmed-never-fired"/)
  // duplicate context names ids and stays read-only, on both sides
  assert.match(act, /data-testid="alert-dup-AXTI-1">2 definitions share AXTI price_cross_below 7\.47 \(ids 1, 3; 1 armed\) — review context; nothing is merged or deleted\./)
  assert.match(his, /data-testid="alert-dup-AXTI-1"/)
  assert.ok(!/delete|merge\(/i.test(readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8').split('function AlertsPanel')[1].split('const URLS')[0].replace(/nothing is merged or deleted/g, '')), 'the alerts panel has no merge/delete path')
  // grouping: rows are grouped by symbol with a count
  assert.match(his, /data-testid="alert-group-AXTI">AXTI · 1 definition in this view/)
}
// 28. S7/WR-09: filter, search and page are URL state — a reload, Back or a shared link lands on the same view, and the
// default view adds no params. (Pure round-trip + the host's wiring.)
{
  const from = q => model.alertViewFrom(new URLSearchParams(q))
  assert.deepEqual(from('tab=alerts&filter=history&q=ax&alert_page=3'), { filter: 'history', q: 'ax', page: 3 })
  assert.deepEqual(from('tab=alerts'), { filter: 'active', q: '', page: 1 })
  assert.deepEqual(from('filter=ALL&alert_page=-4'), { filter: 'active', q: '', page: 1 }, 'an unknown filter is not History')
  assert.deepEqual(model.alertViewQuery({ filter: 'active', q: '', page: 1 }), {}, 'the default view adds no params')
  assert.deepEqual(model.alertViewQuery({ filter: 'history', q: 'ax', page: 3 }), { filter: 'history', q: 'ax', alert_page: '3' })
  const src = readFileSync(join(app, 'src/pages/WatchSetupsV002.tsx'), 'utf8')
  assert.match(src, /const alertView = alertViewFrom\(sp\)/)
  assert.match(src, /for \(const k of \['filter', 'q', 'alert_page'\]\) next\.delete\(k\)/, 'stale params are cleared, not merely overwritten')
  assert.match(src, /setSp\(next, \{ replace: true \}\)/)
  assert.match(src, /alertView=\{alertView\} onAlertView=\{onAlertView\}/, 'the URL view reaches the tab host')
}
console.log('28 scenarios passed')
