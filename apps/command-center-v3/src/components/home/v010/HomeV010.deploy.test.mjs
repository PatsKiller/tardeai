// Home v010 — the Deploy card (campaign Home item 5, with item 1's timing rule).
//
// The card's served identity is the release the server reports it is RUNNING; the poller's last decision is a
// separate, labelled fact. A missing `served` block is UNKNOWN — the poller's sha is never printed as "serving".
// The activation instant is absolute; its age is recomputed at render, so the same body ages when the clock moves.
// Synthetic fixtures only (no real accounts, symbols or values).
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
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
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { buildModel, API } = await import(compile(join(app, 'src/lib/homeV010.ts')))
const { homeDeployView, DEPLOY_SOURCE } = await import(compile(join(app, 'src/lib/homeDeploy.ts')))
const { default: View } = await import(compile(join(app, 'src', 'components', 'home', 'v010', 'HomeV010View.tsx')))

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ACT = '2031-03-07T14:56:00Z'
const SERVED = 'd12fe7ec303385c4398c8eeba7dab6def89c0ccc'
const POLLER = '9c21372aa' + 'b'.repeat(31)
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })

const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const wire = (over = {}) => ({
  schema: 'DeploysStatus@v1', generated_at: '2031-03-07T14:59:00Z',
  served: { sha: SERVED, release: 'synthetic', stamped_at: '2031-03-07T14:55:00Z', activated_at: ACT, is_current: true, error: null },
  latest: { schema: 'DeployOnMainReceipt@v1', as_of: '2031-03-07T14:58:00Z', path: 'poller', outcome: 'deploy_failed', main_sha: POLLER },
  latest_error: null,
  stop: { schema: 'DeployStopStatus@v1', as_of: '2031-03-07T14:59:00Z', latch: { status: 'ABSENT' }, window_run_lock: 'FREE' },
  ...over,
})
const read = (over = {}, state = 'OK', error = null) => ({ state, data: state === 'OK' ? wire(over) : null, error, at: AT, source: DEPLOY_SOURCE })
const render = (r, now = NOW) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model: buildModel(CLEAR, now), nowIso: new Date(now).toISOString(),
    onOpenWhy() {}, onOpenDiag() {}, deploys: r === undefined ? undefined : homeDeployView(r, now) })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const section = html => html.match(/<section[^>]*id="card-deploy"[\s\S]*?<\/section>/)
const cardText = (r, now) => text(section(render(r, now))[0])

let n = 0
function test(name, fn) { fn(); n += 1; console.log(`ok - ${name}`) }

// 1. The card is the SERVED release: its sha, its absolute activation time and the age computed at render.
test('served sha + activation instant + render-computed age; poller labelled separately', () => {
  const t = cardText(read())
  assert.match(t, /Serving d12fe7ec3 · activated \w{3} 9:56 AM ET · 4 m old/)
  assert.match(t, /Deploy STOP STOP clear/)
  assert.match(t, /Poller last decision deploy_failed · main 9c21372aa · \w{3} 9:58 AM ET · not the served release/)
  assert.match(t, /source: \/api\/v2\/ops\/deploys · read \w{3} 9:59 AM ET/)
})

// 2. The age is a function of the render clock, not a stored string.
test('the same body ages when the client clock moves; no stored relative wording', () => {
  const later = cardText(read(), NOW + 3_600_000)
  assert.match(later, /activated \w{3} 9:56 AM ET · 1 h 4 m old/)
  assert.doesNotMatch(later, /just now/i)
})

// 3. No served block: UNKNOWN, and the poller's sha is never printed as "serving".
test('missing served block -> UNKNOWN, never the poller sha as the served version', () => {
  const t = cardText(read({ served: null }))
  assert.match(t, /Serving UNKNOWN — the server did not report the served release/)
  assert.match(t, /The poller(?:&#x27;|')s last decision says nothing about what is running/)
  assert.doesNotMatch(t, /Serving [^·]*9c21372aa/)
})

// 4. A served release that is not CURRENT is called out.
test('is_current false -> "NOT the CURRENT release"', () => {
  const t = cardText(read({ served: { sha: SERVED, activated_at: ACT, is_current: false } }))
  assert.match(t, /Serving d12fe7ec3 · NOT the CURRENT release/)
})

// 5. An unparseable activation time says so instead of looking current.
test('unusable activated_at -> "activation time not published"', () => {
  const t = cardText(read({ served: { sha: SERVED, activated_at: 'yesterday-ish', is_current: true } }))
  assert.match(t, /activation time not published/)
  assert.doesNotMatch(t, /activated \w{3}/)
})

// 6. An unreadable route is drawn as UNAVAILABLE with its reason and a fail-closed STOP.
test('unreadable route -> UNAVAILABLE, STOP fails closed, reason travels', () => {
  const t = cardText(read({}, 'UNKNOWN', 'HTTP 503'))
  assert.match(t, /UNAVAILABLE/)
  assert.match(t, /STOP UNAVAILABLE/)
  assert.match(t, /HTTP 503/)
})

// 7. A poller receipt on the served commit is "same", and one older than the activation is marked.
test('poller same commit / before activation are distinguished', () => {
  const same = cardText(read({ latest: { as_of: '2031-03-07T14:58:00Z', outcome: 'verified', main_sha: SERVED } }))
  assert.match(same, /same commit as the served release/)
  const before = cardText(read({ latest: { as_of: '2031-03-07T14:50:00Z', outcome: 'verified', main_sha: SERVED } }))
  assert.match(before, /before it was activated/)
})

// 8. A page that did not read the route says so; it does not omit the card or imply a clear deploy.
test('no deploy read -> the card says it was not read', () => {
  const t = text(section(render(undefined))[0])
  assert.match(t, /deploy status was not read by this page/)
})

// C1 (review item 5): an absent is_current is "CURRENT unresolved" — not silently current and not "NOT the CURRENT
// release" — and the server's own reason is drawn beside it (C2). The pill names the card's verdict, so the header
// can never read "Deploy OK" above an unresolved body (C3).
test('absent is_current -> CURRENT unresolved with the server reason; the pill is not OK', () => {
  const t = cardText(read({ served: { sha: SERVED, activated_at: ACT } }))
  assert.match(t, /Serving d12fe7ec3 · CURRENT unresolved/)
  assert.doesNotMatch(t, /NOT the CURRENT release|CURRENT unresolved \(/)
  const why = cardText(read({ served: { sha: SERVED, activated_at: ACT, error: 'CURRENT symlink not readable next to this release' } }))
  assert.match(why, /CURRENT unresolved \(CURRENT symlink not readable next to this release\)/)
  const html = section(render(read({ served: { sha: SERVED, activated_at: ACT } })))[0]
  const pill = text(html.match(/data-testid="deploy-state"[^>]*>([\s\S]*?)<\/span>/)[1]).trim()
  assert.equal(pill, 'WARN', 'the header states the card verdict, never OK above an unresolved release')
  assert.doesNotMatch(pill, /OK/)
})

// C1: a served block whose sha is absent still carries the server's reason, and C2's callout never leaks into a
// resolved release.
test('served without a sha prints the server error; CURRENT unresolved is only drawn when unresolved', () => {
  const t = cardText(read({ served: { sha: null, error: 'no BUILD_SHA in d00d-live' } }))
  assert.match(t, /UNKNOWN — the server did not report the served release \(no BUILD_SHA in d00d-live\)/)
  const good = cardText(read())
  assert.doesNotMatch(good, /CURRENT unresolved/)
})

// C1: a poller row that cannot be compared with the served release says so (no receipt, or a receipt with no sha).
test('poller without a comparable sha -> "cannot be compared with the served release"', () => {
  assert.match(cardText(read({ latest: null })), /cannot be compared with the served release/)
  assert.match(cardText(read({ latest: { as_of: '2031-03-07T14:58:00Z', outcome: 'verified' } })), /cannot be compared with the served release/)
})

// r3 C4+C5 (review cc-deepseek-3 of the r2 delta; test supplied by the reviewer, adopted verbatim): the transport
// fact the C3 fix moved to the source line is named, and freshness is part of the card verdict — a stale kept body
// with a resolved `current` release is WARN, never a green OK over its own "transport STALE".
test('a stale body is WARN in the pill and named as transport STALE, never a green OK', () => {
  const html = section(render(read({ generated_at: '2031-03-06T14:59:00Z' })))[0]
  const t = text(html)
  assert.match(t, /transport STALE/)
  const pill = text(html.match(/data-testid="deploy-state"[^>]*>([\s\S]*?)<\/span>/)[1]).trim()
  assert.equal(pill, 'WARN', 'freshness is part of the card verdict')
  assert.doesNotMatch(pill, /OK/)
  assert.doesNotMatch(cardText(read()), /transport /)
})

console.log(`HomeV010.deploy: ${n} passed`)
