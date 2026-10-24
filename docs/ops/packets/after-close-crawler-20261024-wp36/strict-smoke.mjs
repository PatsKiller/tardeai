// WP-36 bounded after-close observer. No profiles, cookies, credentials, clicks or writer APIs.
import http from 'node:http'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { performance } from 'node:perf_hooks'

export const LIVE_ORIGIN = 'http://127.0.0.1:7777'
export const BUILD_PATH = '/v3/build-meta.json'
// Preserved verbatim from the existing crawler. Owner-held; never bypassed by this packet.
export const HEAVY = /\/api\/(v3\/maturity\/|v2\/hermes\/|v3\/hermes\/|v2\/health\/(remediation|log)|v2\/ui\/prefs\/get\?key=portfolio\.shared-symbol-context|v2\/watchlist\/items\?symbols=)/
const BUSINESS = /^\/api\/.*(broker|orders?|stops?|schwab|alpaca|fidelity|moomoo|execution|positions|portfolio|trading|2fa|reauth|passkey|totp|credential|secret|token|cookie)/i
const ACTION = /^\/api\/.*(?:\/|-)(refresh|sync|run|retry|send|save|delete|archive|apply|execute|buy|sell|trim|promote|confirm|reset|enable|disable|kill|restart|reload|upload|login|logout|authorize|exchange|probe|backfill|rebuild|trigger|dispatch|deploy|rollback)(?:\/|\?|$|-)/i
export const PAGES = [
  '/v3/retirement', '/v3/journal', '/v3/watch', '/v3/watch/discovery', '/v3/watch-legacy',
  '/v3/defense', '/v3/reports', '/v3/rotation', '/v3/rotation?tab=advisor-guide', '/v3/redeploy',
  '/v3/rec-intel', '/v3/advisory', '/v3/cio', '/v3/health', '/v3/communications', '/v3/consumption',
  '/v3/coordination', '/v3/system', '/v3/system/releases', '/v3/system/releases?tab=n8n',
  '/v3/system/ops-controls', '/v3/control-plane', '/v3/control-plane/system', '/v3/control-plane/agents',
  '/v3/control-plane/workflows', '/v3/control-plane/research', '/v3/control-plane/data',
  '/v3/control-plane/identity', '/v3/control-plane/notifications', '/v3/control-plane/learning',
  '/v3/control-plane/maturity', '/v3/control-plane/audit',
]
export class Refused extends Error {
  constructor(code, detail = '') { super(code + (detail ? ': ' + detail : '')); this.code = code }
}
export function afterClose(flag, at = new Date()) {
  if (flag !== '1') throw new Refused('AFTER_CLOSE_FLAG_REQUIRED')
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(at).map(x => [x.type, x.value]))
  const minutes = Number(p.hour) * 60 + Number(p.minute)
  // Conservative on weekday holidays: never infer permission from an unavailable holiday calendar.
  if (!['Sat', 'Sun'].includes(p.weekday) && minutes >= 240 && minutes < 975)
    throw new Refused('MARKET_WINDOW_REFUSED')
}
export function policy(raw, method, headers = {}, origin = LIVE_ORIGIN) {
  let u
  try { u = new URL(raw, origin) } catch { throw new Refused('URL_INVALID') }
  if (u.origin !== origin || u.username || u.password || u.protocol !== 'http:')
    throw new Refused('ORIGIN_REFUSED')
  if (method !== 'GET') throw new Refused('METHOD_REFUSED')
  if (Object.keys(headers).some(x => /^(authorization|proxy-authorization|cookie)$/i.test(x)))
    throw new Refused('CLIENT_CREDENTIALS_REFUSED')
  if ([...u.searchParams.keys()].some(x => /(token|secret|password|cookie|credential|authorization)/i.test(x)))
    throw new Refused('CREDENTIAL_QUERY_REFUSED')
  if ([...u.searchParams.keys()].some(x => /^(force|refresh|sync|run|retry|send|apply|execute|action|write|mutate|reset|backfill|probe)(_|$)/i.test(x)))
    throw new Refused('ACTION_QUERY_REFUSED')
  const target = u.pathname + u.search
  if (HEAVY.test(target) || /^\/api\/(?:v[23]\/hermes|v3\/maturity)(?:\/|\?|$)/.test(target)) throw new Refused('OWNER_HELD_HEAVY_ENDPOINT')
  if (BUSINESS.test(target)) throw new Refused('OWNER_HELD_BUSINESS_OR_AUTH_ENDPOINT')
  if (ACTION.test(target)) throw new Refused('ACTION_URL_REFUSED')
  return u
}
export function rawGet({ url, timeoutMs, maxBytes }) {
  return new Promise((resolve, reject) => {
    let deadline, finished = false
    const finish = value => { if (finished) return; finished = true; clearTimeout(deadline); resolve(value) }
    const fail = error => { if (finished) return; finished = true; clearTimeout(deadline); reject(error) }
    const req = http.request(url, { method: 'GET', headers: {
      accept: '*/*', 'accept-encoding': 'identity', 'user-agent': 'TradeAI-AfterClose-Smoke/1',
    } }, res => {
      const status = res.statusCode || 0
      if (status >= 300) { res.resume(); finish({ status, headers: res.headers, body: Buffer.alloc(0) }); return }
      const chunks = []; let bytes = 0
      res.on('data', c => {
        bytes += c.length
        if (bytes > maxBytes) { req.destroy(new Refused('RESPONSE_SIZE_REFUSED')); return }
        chunks.push(c)
      })
      res.on('end', () => finish({ status, headers: res.headers, body: Buffer.concat(chunks) }))
      res.on('error', fail)
    })
    req.on('error', fail)
    deadline = setTimeout(() => req.destroy(new Refused('REQUEST_TIMEOUT')), timeoutMs)
    req.end()
  })
}
export class StrictTransport {
  constructor({ origin = LIVE_ORIGIN, send = rawGet, clock = () => performance.now(),
    sleep = ms => new Promise(r => setTimeout(r, ms)), guard = () => afterClose(process.env.TRADEAI_LIVE_SMOKE_AFTER_CLOSE),
    gapMs = 1000, timeoutMs = 10000, maxBytes = 8 * 1024 * 1024 } = {}) {
    const u = new URL(origin)
    if (u.hostname !== '127.0.0.1' || u.protocol !== 'http:' || u.username || u.password || u.pathname !== '/')
      throw new Refused('TRANSPORT_ORIGIN_REFUSED')
    if (gapMs < 1000 || !Number.isFinite(gapMs)) throw new Refused('RATE_CONFIG_REFUSED')
    this.origin = origin; this.send = send; this.clock = clock; this.sleep = sleep; this.guard = guard
    this.gapMs = gapMs; this.timeoutMs = timeoutMs; this.maxBytes = maxBytes; this.last = -Infinity
    this.chain = Promise.resolve(); this.pending = 0; this.halted = null; this.events = []; this.expectedSha = null
  }
  stop(code) { this.halted ||= code; throw new Refused(this.halted) }
  get(raw, { method = 'GET', requestHeaders = {}, isActive = () => true } = {}) {
    const u = policy(raw, method, requestHeaders, this.origin)
    this.pending++
    const run = this.chain.then(async () => {
      if (this.halted) throw new Refused(this.halted)
      if (!isActive()) throw new Refused('VIEW_CLOSED')
      try { this.guard() } catch (e) { this.stop(e.code || 'GUARD_REFUSED') }
      const earliest = this.last + this.gapMs
      while (this.clock() < earliest) await this.sleep(Math.max(1, Math.ceil(earliest - this.clock())))
      try { this.guard() } catch (e) { this.stop(e.code || 'GUARD_REFUSED') }
      if (!isActive()) throw new Refused('VIEW_CLOSED')
      if (this.halted) throw new Refused(this.halted)
      this.last = this.clock()
      const ev = { seq: this.events.length + 1, method: 'GET', path: u.pathname + u.search,
        started_monotonic_ms: this.last, at: new Date().toISOString() }
      this.events.push(ev)
      let response
      try { response = await this.send({ url: u, timeoutMs: this.timeoutMs, maxBytes: this.maxBytes }) }
      catch (e) { ev.error_code = e.code || 'TRANSPORT_ERROR'; this.stop(ev.error_code) }
      ev.status = response.status; ev.bytes = response.body.length; ev.elapsed_ms = this.clock() - ev.started_monotonic_ms
      this.last = this.clock() // >= one second after prior completion, not a fractional timer estimate
      if (response.status === 401 || response.status === 403) this.stop('AUTH_REFUSED')
      if (response.status >= 500) this.stop('HTTP_5XX_STOP')
      // No redirects, retries or alternate routes: a 3xx/4xx is a real read boundary.
      if (response.status >= 300) this.stop('HTTP_READ_REFUSED_' + response.status)
      if (response.status < 200) this.stop('HTTP_STATUS_REFUSED')
      return response
    }).finally(() => { this.pending-- })
    this.chain = run.catch(() => {})
    return run
  }
  async identity() {
    const r = await this.get(BUILD_PATH)
    let doc
    try { doc = JSON.parse(r.body.toString('utf8')) } catch { this.stop('BUILD_IDENTITY_UNREADABLE') }
    if (!doc || typeof doc !== 'object') this.stop('BUILD_IDENTITY_UNPROVEN')
    const sha = doc.git_sha || doc.source_sha || doc.source_commit
    if (!/^[0-9a-f]{40}$/.test(sha || '')) this.stop('BUILD_IDENTITY_UNPROVEN')
    if (this.expectedSha && sha !== this.expectedSha) this.stop('SERVED_RELEASE_DRIFT')
    this.expectedSha ||= sha
    return sha
  }
}
export async function routeRead(route, transport, held) {
  const req = route.request()
  try {
    const r = await transport.get(req.url(), { method: req.method(), requestHeaders: await req.allHeaders(),
      isActive: () => { try { return !req.frame().page().isClosed() } catch { return false } } })
    // Never give the browser Set-Cookie, auth challenges or redirects. The direct HTTP transport has no cookie jar.
    const headers = {}
    for (const name of ['content-type', 'content-encoding', 'cache-control'])
      if (r.headers[name]) headers[name] = r.headers[name]
    await route.fulfill({ status: r.status, headers, body: r.body })
  } catch (e) {
    held.push({ path: (() => { try { return new URL(req.url()).pathname } catch { return 'invalid' } })(),
      method: req.method(), code: e.code || 'TRANSPORT_ERROR' })
    if (e.code === 'CLIENT_CREDENTIALS_REFUSED' || e.code === 'CREDENTIAL_QUERY_REFUSED') transport.halted ||= e.code
    await route.abort('blockedbyclient').catch(() => {})
  }
}
export async function installBrowserGuards(ctx, transport, held) {
  if (typeof ctx.routeWebSocket !== 'function') throw new Refused('WEBSOCKET_GUARD_UNAVAILABLE')
  await ctx.routeWebSocket('**/*', ws => { held.push({ code: 'WEBSOCKET_BLOCKED' }); ws.close() })
  await ctx.route('**/*', route => routeRead(route, transport, held))
}
function argsOf(argv) {
  const out = {}
  for (const arg of argv) {
    const m = /^--(out|routes|expected-sha)=(.+)$/.exec(arg)
    if (!m) throw new Refused('ARGUMENT_REFUSED')
    out[m[1]] = m[2]
  }
  if (!out.out) throw new Refused('OUTPUT_REQUIRED')
  out.routes = out.routes ? out.routes.split(',') : PAGES
  if (!out.routes.every(x => PAGES.includes(x))) throw new Refused('PAGE_SCOPE_REFUSED')
  if (out['expected-sha'] && !/^[0-9a-f]{40}$/.test(out['expected-sha'])) throw new Refused('EXPECTED_SHA_INVALID')
  return out
}
export async function main(argv = process.argv.slice(2)) {
  afterClose(process.env.TRADEAI_LIVE_SMOKE_AFTER_CLOSE)
  const args = argsOf(argv); await fs.mkdir(args.out, { recursive: true })
  const t = new StrictTransport(); t.expectedSha = args['expected-sha'] || null
  const report = { schema: 'AfterCloseSmoke@v1', origin: LIVE_ORIGIN, started_at: new Date().toISOString(),
    expected_sha: t.expectedSha, results: [], held: [], requests: t.events, status: 'RUNNING',
    no_credentials: true, no_clicks: true, heavy_guard_preserved: HEAVY.source }
  const save = async () => fs.writeFile(path.join(args.out, 'receipt.json'), JSON.stringify(report, null, 2) + '\n')
  let browser
  try {
    report.expected_sha = await t.identity(); await save()
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')
    const require = createRequire(path.join(root, 'apps/command-center-v3/package.json'))
    const { chromium } = require('playwright'); browser = await chromium.launch({ headless: true })
    for (const width of [1440, 412]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block', acceptDownloads: false })
      await installBrowserGuards(ctx, t, report.held)
      for (const url of args.routes) {
        if (t.halted) throw new Refused(t.halted)
        await t.identity()
        const start = t.events.length, heldStart = report.held.length
        const row = { url, width, status: 'NOT_MEASURED', started_at: new Date().toISOString() }
        report.results.push(row); const page = await ctx.newPage()
        const errors = []; page.on('pageerror', e => errors.push(e.message.slice(0, 200)))
        console.log('START', width, url)
        try {
          await page.goto(LIVE_ORIGIN + url, { waitUntil: 'domcontentloaded', timeout: 120000 })
          // Bounded observation only. No click, form, credential, cookie or automatic retry operation.
          const began = performance.now(); let previous = -1, stable = performance.now()
          while (performance.now() - began < 90000) {
            if (t.halted) throw new Refused(t.halted)
            if (t.events.length - start > 80) throw new Refused('VIEW_REQUEST_BUDGET_STOP')
            if (t.events.length !== previous) { previous = t.events.length; stable = performance.now() }
            if (!t.pending && performance.now() - stable > 2500) break
            await page.waitForTimeout(250)
          }
          if (t.pending) throw new Refused('VIEW_SETTLE_TIMEOUT')
          await t.chain
          if (t.halted) throw new Refused(t.halted)
          await t.identity()
          const facts = await page.evaluate(() => ({ title: document.title,
            width: innerWidth, scroll_width: document.documentElement.scrollWidth,
            loading: /Loading…\s*$/.test(document.body.innerText),
            error_boundary: /Something went wrong|Unexpected Application Error|failed to render/i.test(document.body.innerText),
            text_length: document.body.innerText.length }))
          row.observation = facts; row.page_errors = errors
          row.held = report.held.slice(heldStart)
          row.status = facts.error_boundary || errors.length ? 'FAIL' : facts.loading || row.held.length || facts.scroll_width > width + 1 ? 'WARN' : 'PASS'
          row.shot = width + '-' + url.replace(/[^A-Za-z0-9]+/g, '_') + '.png'
          await page.screenshot({ path: path.join(args.out, row.shot), fullPage: false })
        } catch (e) {
          row.status = 'NOT_MEASURED'; row.cause = e.code || 'BROWSER_TIMEOUT_OR_ERROR'
          t.halted ||= row.cause; throw e
        } finally { await page.close(); await save() }
        console.log(row.status, width, url); await save()
      }
      await ctx.close()
    }
    report.status = 'COMPLETE'
  } catch (e) {
    report.status = 'STOPPED'; report.stop_code = t.halted || e.code || 'HARNESS_ERROR'
    console.log('STOPPED', report.stop_code)
  } finally {
    if (browser) await browser.close()
    report.finished_at = new Date().toISOString(); report.expected_sha = t.expectedSha; await save()
  }
  return report.status === 'COMPLETE' ? 0 : 2
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  process.exitCode = await main()
