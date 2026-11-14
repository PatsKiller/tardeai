// LQ-20261113-3046: Combined Home A04 (schedulers row = server gate) + A07 (account / P&L definitions on the face).
// node src/lib/homeA04A07.test.mjs  (synthetic fixtures only)
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')

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


const lib = await import(compile(join(app, 'src/lib/homeV010.ts')))
const { buildModel, API } = lib
const dn = await import(compile(join(app, 'src/lib/homeDoNow.ts')))

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const gate = (id, state, extra = {}) => ({ id, label: id, required: false, state, source_id: `src_${id}`, as_of: '2031-03-07T14:58:00Z', age_s: 120, threshold_s: 1800, reason: null, needs_backend: false, ...extra })
const model = gates => buildModel({ ...CLEAR, status: ok(API.status, { schema: 'HomeStatus@v1', verdict: 'UNKNOWN',
  trade_ready: { verdict: 'UNKNOWN', cause: 'synthetic', computed_at: '2031-03-07T14:59:30Z' }, gates, blockers: [], unknown_inputs: [] }) }, NOW)
const row = m => m.status.find(r => r.id === 'row-schedulers')
const read = p => readFileSync(join(app, p), 'utf8')

let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }

await test('A04: a WARN schedulers gate shows WARN with the server reason, not "not measured"', () => {
  const r = row(model([gate('schedulers', 'WARN', { reason: '34 LATE, 5 STALE, 1 FAILING of 414 lanes' })]))
  assert.equal(r.state, 'WARN')
  assert.match(r.cause, /34 LATE, 5 STALE, 1 FAILING/)
  assert.doesNotMatch(r.value, /not measured/)
  assert.match(r.value, /lane health as of/)
})
await test('A04: an OK schedulers gate shows OK with its age', () => {
  const r = row(model([gate('schedulers', 'OK')]))
  assert.equal(r.state, 'OK')
  assert.match(r.value, /2 m old/)
})
await test('A04: an UNKNOWN schedulers gate stays UNKNOWN and keeps its reason and source', () => {
  const r = row(model([gate('schedulers', 'UNKNOWN', { reason: 'lane_health_current unreadable' })]))
  assert.equal(r.state, 'UNKNOWN')
  assert.equal(r.cause, 'lane_health_current unreadable')
  assert.equal(r.source, 'src_schedulers')
  assert.equal(r.value, 'not measured', 'an unread gate never prints a lane-health time')
})
await test('A04: a TIMED OUT schedulers gate reads as timed out, not as a measurement', () => {
  const r = row(model([gate('schedulers', 'TIMED_OUT')]))
  assert.equal(r.state, 'TIMED OUT')
  assert.equal(r.value, 'no answer after 30 s')
})
await test('A04: no schedulers gate at all is UNKNOWN and says so (never invents OK)', () => {
  const r = row(model([gate('portfolio', 'OK')]))
  assert.equal(r.state, 'UNKNOWN')
  assert.match(r.source, /no schedulers gate/)
})
await test('A04: the row and the Why gate list agree about the one source', () => {
  const m = model([gate('schedulers', 'WARN', { reason: 'x' })])
  const inp = m.why.inputs.filter(i => /schedulers/i.test(i.name))
  assert.ok(inp.length >= 1)
  assert.ok(inp.every(i => i.state === 'WARN'), JSON.stringify(inp))
})
await test('A07: accountsCaption counts listed accounts, names unknown-value ones, and prints the true rounding bound', () => {
  const v = k => ({ key: k, value: 100.49, oneRead: true })
  const c = dn.accountsCaption([{ key: 'all', value: 502.45, oneRead: true }, v('a'), v('b'), v('c'), v('d'), v('e')])
  assert.match(c, /^5 accounts listed\. /)
  assert.doesNotMatch(c, /cash-only/)
  assert.match(c, /every account in the book and, separately, those holding positions/)  // LQ-3076: one account definition
  assert.doesNotMatch(c, /only accounts holding positions/)
  assert.match(c, /up to \$3\./)   // 0.5 x (5 + 1): five rows of 100.49 show 500 against 502.45 shown as 502 (gap 2 <= 3)
  assert.match(dn.accountsCaption([{ key: 'all', oneRead: true }, v('a')]), /up to \$1\./)
  assert.match(dn.accountsCaption([v('a'), v('b')]), /up to \$1\.5\./)
  const u = dn.accountsCaption([v('a'), { key: 'b', value: null, oneRead: true }, v('c')])
  assert.match(u, /3 accounts listed, 1 with no value in the holdings store \(not in the sum\)/)
  assert.match(u, /up to \$1\.5\./)   // 2 valued rows + total
  assert.equal(dn.accountsCaption([{ key: 'all' }]), null)
  assert.match(dn.accountsCaption([v('x')]), /^1 account listed\./)
})
await test('A07: the rounding bound is claimed only for rows that share a payload with the total (review 3056 F1)', () => {
  const caption = (perf, overview) => dn.accountsCaption(dn.accountRows(perf, overview))
  const oneRead = { portfolio_value: 1, portfolio_total: { value: 3001, by_account: { schwab_roth: { value: 1000.2 }, schwab_rollover_ira: { value: 2000.2 } } } }
  const perf = { accounts: { schwab_roth: { current_value: 1000.2 }, schwab_rollover_ira: { current_value: 2000.2 } } }
  assert.match(caption(perf, oneRead), /up to \$1\.5\./)                                  // one payload: bound printed
  const probe = caption(perf, { portfolio_value: 3500 })                                  // reviewer's probe: rows 3,000 vs All 3,500
  assert.doesNotMatch(probe, /up to \$/)
  assert.match(probe, /different reads, so they may not add up/)
  assert.match(caption(null, { portfolio_value: 1, today_by_account: { a_b: { value: 5, change: 1 } } }), /different reads/)  // today_by_account fallback
  assert.match(caption(perf, { portfolio_total: { value: 3001, by_account: {} } }), /different reads/)  // contract present but no by_account rows
  const unknownMixed = caption({ accounts: { a_b: { current_value: null } } }, { portfolio_value: 9 })
  assert.match(unknownMixed, /1 with no value \(not in the sum\)/)                        // no "holdings store" claim off the one-read branch
  // one row off the shared read is enough to withdraw the claim
  assert.match(dn.accountsCaption([{ key: 'all', value: 9, oneRead: true }, { key: 'a', value: 5, oneRead: true }, { key: 'b', value: 4 }]), /different reads/)
  assert.ok(dn.accountRows(perf, oneRead).every(r => r.oneRead === true))
  assert.ok(dn.accountRows(perf, { portfolio_value: 3500 }).every(r => r.oneRead !== true))
})
await test('A07: the Accounts caption component renders the text, and nothing when no account is listed', async () => {
  const React = (await import(pathToFileURL(require.resolve('react')).href)).default
  const { renderToStaticMarkup } = await import(pathToFileURL(require.resolve('react-dom/server')).href)
  const { AccountsCaption } = await import(compile(join(app, 'src/components/home/AccountsCaption.tsx')))
  const html = renderToStaticMarkup(React.createElement(AccountsCaption, { rows: [{ key: 'all', value: 9, oneRead: true }, { key: 'a', value: 5, oneRead: true }, { key: 'b', value: null, oneRead: true }] }))
  assert.match(html, /data-testid="home-accounts-caption"/)
  assert.match(html, /2 accounts listed, 1 with no value/)
  assert.equal(renderToStaticMarkup(React.createElement(AccountsCaption, { rows: [{ key: 'all', value: 9 }] })), '')
})
await test('A07: HomeDoNow renders the caption component ungated, and the Book line names both account counts (LQ-3076)', () => {
  assert.match(read('src/components/home/CioCardV5.tsx'), /bookAccountsText\(card\.book\)/)
  assert.doesNotMatch(read('src/components/home/CioCardV5.tsx'), /accounts holding positions/)
  const page = read('src/pages/HomeDoNow.tsx')
  assert.match(page, /import \{ AccountsCaption \} from '\.\.\/components\/home\/AccountsCaption'/)
  assert.match(page, /^\s*<AccountsCaption rows=\{accounts\} \/>\s*$/m)  // a bare line: `{false && <AccountsCaption…/>}` does not match
})
await test('A04: a failed / loading status read puts its own cause on the Schedulers row (review F3)', () => {
  for (const [rd, state, cause] of [
    [{ state: 'TIMED OUT', data: null, error: 'timeout', at: null, source: API.status }, 'TIMED OUT', /timed out/],
    [{ state: 'LOADING', data: null, error: null, at: null, source: API.status }, 'LOADING', /reading/],
    [{ state: 'ERROR', data: null, error: 'boom', at: null, source: API.status }, 'UNKNOWN', /boom/],
  ]) {
    const r = row(buildModel({ ...CLEAR, status: rd }, NOW))
    assert.equal(r.state, state)
    assert.match(r.cause, cause)
    assert.equal(r.source, '/api/v2/home/status')
    assert.notEqual(r.needsBackend, true)   // a failed read is not a missing endpoint (review 3056 F3 / S1)
  }
  // The status route is not deployed (HTTP 404): that one IS a backend gap, and the row says so.
  const nb = row(buildModel({ ...CLEAR, status: { state: 'ERROR', data: null, error: 'HTTP 404', at: null, source: API.status } }, NOW))
  assert.equal(nb.needsBackend, true)
  assert.match(nb.cause, /not deployed/)
})
await test('A07: REALIZED and TRADING name their populations on the tile face, quiet provenance or not', () => {
  const s = read('src/components/MetricStrip.tsx')
  assert.match(s, /asOfNote: `day \+ swing only/)
  assert.match(s, /`all closed\$\{showQuietProvenance && realizedCount[\s\S]{0,60}\} · incl long-term trims`\]/)
  assert.match(s, /asOfNote: \[realizedScopeText,/)  // the missing-basis note stays on the face
})
console.log(`${n} passed`)
