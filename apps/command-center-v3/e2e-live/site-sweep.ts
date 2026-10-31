/**
 * Site sweep: read-only Playwright defect finder for Command Center v3.
 *
 * Visits every route (live nav rail + router source), at mobile 412x915 / 390x844 and desktop 1440x900,
 * clicks every tab / segmented control / chip that switches a view, opens the first row's detail sheet,
 * probes buttons for dead taps (mobile 412 only) and records defects.
 *
 * READ-ONLY by construction:
 *   - every non-GET/HEAD/OPTIONS request is aborted with page.route and recorded as `write_attempted`;
 *   - side-effect GET routes (/v2/morning-brief, /v2/bot-morning-brief, ?refresh=, ?force=) are aborted too;
 *   - buttons whose text/aria matches WRITE_WORDS are never clicked; confirm()/alert() are dismissed.
 *
 * Load protection: one page, one context; portfolio-server MemoryCurrent checked before every route
 * (pause 30s above 1.2 GB, abort above 1.3 GB). Refuses production 04:00–16:15 ET Mon–Fri (§28.8).
 *
 * Run through scripts/site_sweep.sh. Env:
 *   SWEEP_BASE_URL   default http://127.0.0.1:7777
 *   SWEEP_OUT_DIR    output directory (findings.json, summary.md, shots/)
 *   SWEEP_ROUTES     optional comma list of route substrings to restrict the sweep
 *   SWEEP_VIEWPORTS  optional comma list of viewport names (m412,m390,d1440)
 *   SWEEP_NO_ROUTER_ONLY=1  skip routes that exist only in the router source (not on the nav rail)
 */
import { chromium, type Page, type BrowserContext, type Request } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'

// ---------------------------------------------------------------- config
const BASE = (process.env.SWEEP_BASE_URL || 'http://127.0.0.1:7777').replace(/\/$/, '')
const OUT = process.env.SWEEP_OUT_DIR || path.resolve('site-sweep-out', new Date().toISOString().replace(/[:.]/g, '-'))
const SHOTS = path.join(OUT, 'shots')
const ROUTE_FILTER = (process.env.SWEEP_ROUTES || '').split(',').map((s: string) => s.trim()).filter(Boolean)
const VP_FILTER = (process.env.SWEEP_VIEWPORTS || '').split(',').map((s: string) => s.trim()).filter(Boolean)
const SKIP_ROUTER_ONLY = process.env.SWEEP_NO_ROUTER_ONLY === '1'
const APP_SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'src', 'App.tsx')

const VIEWPORTS: Array<{ name: string; width: number; height: number; mobile: boolean }> = [
  { name: 'm412', width: 412, height: 915, mobile: true },
  { name: 'm390', width: 390, height: 844, mobile: true },
  { name: 'd1440', width: 1440, height: 900, mobile: false },
].filter(v => !VP_FILTER.length || VP_FILTER.includes(v.name))

const SLOW_LOAD_MS = 8_000
const SETTLE_CAP_MS = 20_000
const ROUTE_BUDGET_MS = 240_000
const MAX_TABS_PER_PAGE = 24
const MAX_DEAD_PROBES = 30
const MEM_PAUSE = 1.2e9
const MEM_ABORT = 1.3e9

const WRITE_WORDS = /\b(approve|approv|reject|submit|send|resolve|decision|decide|save|delete|archive|ask|apply|run|re-?run|retry|ack|acknowledge|place|order|buy|sell|stop|revoke|grant|promote|rollback|roll back|refresh|reload|confirm|cancel|execute|dismiss|snooze|mute|enable|disable|activate|deactivate|close position|trim|add to|propose|publish|reset|clear|log out|logout|sign out|upload|download|export|copy|generate|create|new|sync|import|edit|update|scan|backfill|reconcile|reauth|re-auth|connect|disconnect|trigger|start|restart|kill|pause|resume|accept|decline|override|remove|watch this|unwatch|pin|unpin|follow|vote)\b/i
const SIDE_EFFECT_URL = /\/v2\/(bot-)?morning-brief|[?&](refresh|force|rerun|run)=(1|true)/i
const SKIP_ROUTES = [/morning-brief/]

type Severity = 'broken' | 'data' | 'layout' | 'density' | 'expected' | 'info'
const KIND_SEVERITY: Record<string, Severity> = {
  page_error: 'broken', console_error: 'broken', http_error: 'broken', request_failed: 'broken',
  route_crash: 'broken', dead_button: 'broken', write_attempted: 'info', stale_bundle: 'broken', slow_load: 'broken',
  literal_bad_value: 'data', money_format: 'data', raw_iso_timestamp: 'data', empty_list_item: 'data',
  empty_bullet: 'data', text_dump: 'data',
  horizontal_overflow: 'layout', small_tap_target: 'layout', offscreen_clip: 'layout',
  placeholder_density: 'density',
  expected_refusal: 'expected', side_effect_blocked: 'info', sweep_error: 'info',
}
const SEVERITY_RANK: Record<Severity, number> = { broken: 0, data: 1, layout: 2, density: 3, info: 4, expected: 5 }

type Finding = {
  route: string; tab: string; viewport: string; kind: string; severity: Severity
  detail: string; samples: string[]; count: number; screenshot: string | null; in_flight?: string; also_in: string[]
}
type StateKey = string
const findings: Finding[] = []
const coverage: Array<{ route: string; viewport: string; tabs: string[]; detail_opened: string | null; load_ms: number; dead_probes: number; source: string }> = []
const startedAt = Date.now()
let aborted: string | null = null

const IN_FLIGHT: Array<[RegExp, string]> = [
  [/^\/v3\/journal/, 'in-flight: TradeInView fix in progress'],
  [/^\/v3\/watch/, 'in-flight: Watch Resolve fix in progress (only Resolve/conflict findings)'],
]

// ---------------------------------------------------------------- guards
function etParts(d = new Date()) {
  const f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
  const p = Object.fromEntries(f.formatToParts(d).map(x => [x.type, x.value]))
  return { wd: p.weekday, hm: Number(p.hour) % 24 * 60 + Number(p.minute) }
}
function isProduction(base: string): boolean {
  return /\/\/(127\.0\.0\.1|localhost|\[::1\]):7777\b/.test(base) || /ms01-openclaw\./.test(base)
}
function marketWindowRefusal(): string | null {
  if (!isProduction(BASE)) return null
  const { wd, hm } = etParts()
  if (['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(wd) && hm >= 4 * 60 && hm < 16 * 60 + 15) {
    return `refusing production sweep ${wd} ${Math.floor(hm / 60)}:${String(hm % 60).padStart(2, '0')} ET (§28.8: 04:00–16:15 ET Mon–Fri); point SWEEP_BASE_URL at a non-production host`
  }
  return null
}
function serverMemory(): number | null {
  try {
    const v = execSync('systemctl --user show portfolio-server.service -p MemoryCurrent --value', { encoding: 'utf8', timeout: 5000 }).trim()
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  } catch { return null }
}
async function memoryGate(): Promise<boolean> {
  // Operator rule: pause 30s above 1.2 GB, abort above 1.3 GB (checked again after the pause).
  if (!isProduction(BASE)) return true
  let m = serverMemory()
  if (m == null || m <= MEM_PAUSE) return true
  if (m <= MEM_ABORT) {
    console.log(`[mem] ${(m / 1e9).toFixed(2)} GB > 1.2 GB — pausing 30s`)
    await new Promise(r => setTimeout(r, 30_000))
    m = serverMemory()
  }
  if (m != null && m > MEM_ABORT) { aborted = `portfolio-server MemoryCurrent ${(m / 1e9).toFixed(2)} GB > 1.3 GB`; return false }
  return true
}

// ---------------------------------------------------------------- route discovery
function routerRoutes(): string[] {
  try {
    const src = fs.readFileSync(APP_SRC, 'utf8')
    const out: string[] = []
    for (const m of src.matchAll(/<Route path="([^"]+)" element=\{(.{0,160})/g)) {
      const p = m[1]
      if (p.includes(':') || p.includes('*') || /<Navigate /.test(m[2])) continue
      out.push('/v3/' + p.replace(/^\//, ''))
    }
    return out
  } catch { return [] }
}
async function navRoutes(page: Page): Promise<string[]> {
  await page.goto(BASE + '/v3', { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.waitForSelector('nav a[href]', { timeout: 15_000 }).catch(() => {})
  const hrefs = await page.$$eval('nav a[href]', as => as.map(a => (a as HTMLAnchorElement).getAttribute('href') || ''))
  return [...new Set(hrefs.filter(h => h.startsWith('/v3')).map(h => h.replace(/\/$/, '') || '/v3'))]
}

// ---------------------------------------------------------------- page state helpers
type NetLog = { inflight: Set<Request>; total: number; lastChange: number; events: Array<{ url: string; status: number | null; failure?: string; method: string; code?: string }>; writes: string[] }
function attachNet(page: Page, net: NetLog, lastClick: { label: string }) {
  page.on('request', r => { net.inflight.add(r); net.total++; net.lastChange = Date.now() })
  page.on('requestfinished', async r => {
    net.inflight.delete(r); net.lastChange = Date.now()
    const resp = await r.response().catch(() => null)
    if (!resp) return
    let code: string | undefined
    if (resp.status() === 403) code = ((await resp.text().catch(() => '')).match(/[A-Z][A-Z_]{6,}/) || [undefined])[0]
    net.events.push({ url: r.url(), status: resp.status(), method: r.method(), code })
  })
  page.on('requestfailed', r => {
    net.inflight.delete(r); net.lastChange = Date.now()
    const failure = r.failure()?.errorText || 'failed'
    net.events.push({ url: r.url(), status: null, failure, method: r.method() })
  })
  void lastClick
}

async function settle(page: Page, net: NetLog, cap = SETTLE_CAP_MS): Promise<number> {
  const t0 = Date.now()
  let lastLen = -1, stableSince = Date.now()
  while (Date.now() - t0 < cap) {
    await page.waitForTimeout(250)
    const { len, loading } = await page.evaluate(() => {
      const t = document.body?.innerText || ''
      return { len: t.length, loading: /\bLoading\b[^\n]{0,40}(…|\.\.\.)|^\s*Loading\s*$/m.test(t) || !!document.querySelector('[aria-busy="true"]') }
    }).catch(() => ({ len: 0, loading: true }))
    if (len !== lastLen) { lastLen = len; stableSince = Date.now() }
    const quiet = net.inflight.size === 0 && Date.now() - net.lastChange > 600
    if (quiet && !loading && Date.now() - stableSince > 600 && len > 0) return Date.now() - t0
  }
  return Date.now() - t0
}

/** In-page detector: returns raw observations for the current DOM state. */
async function inspect(page: Page, mobile: boolean) {
  return page.evaluate(({ mobile }) => {
    const vw = window.innerWidth
    const visible = (el: Element) => {
      const r = (el as HTMLElement).getBoundingClientRect()
      if (r.width === 0 && r.height === 0) return false
      const s = getComputedStyle(el as HTMLElement)
      return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05
    }
    const desc = (el: Element) => {
      const h = el as HTMLElement
      const id = h.id ? '#' + h.id : ''
      const tid = h.getAttribute('data-testid') ? `[data-testid=${h.getAttribute('data-testid')}]` : ''
      const cls = typeof h.className === 'string' && h.className ? '.' + h.className.trim().split(/\s+/).slice(0, 2).join('.') : ''
      const txt = (h.innerText || h.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
      return `${h.tagName.toLowerCase()}${id}${tid}${cls}${txt ? ` "${txt}"` : ''}`
    }
    const root = document.body
    const text = root.innerText || ''
    const main = document.querySelector('main') as HTMLElement | null

    // text-node walk (visible text only)
    const leafTexts: Array<{ t: string; el: Element }> = []
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = (n.nodeValue || '').trim()
      const el = n.parentElement
      if (!t || !el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue
      if (!visible(el)) continue
      leafTexts.push({ t, el })
    }
    const ctx = (t: string, re: RegExp) => { const m = re.exec(t); if (!m) return t.slice(0, 100); const i = Math.max(0, m.index - 40); return t.slice(i, m.index + m[0].length + 40).replace(/\s+/g, ' ') }

    const badLit: string[] = [], money: string[] = [], iso: string[] = []
    const reBad = /\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date|(^|[\s:=(])null($|[\s,.)])/
    const reMoneyNeg = /\$-\d/
    const reMoneyBig = /\$-?\d{5,}(?![\d,])/
    const reIso = /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?/
    let placeholder = 0; const phSamples: string[] = []
    for (const { t, el } of leafTexts) {
      if (el.closest('pre, code, textarea, input')) continue
      if (reBad.test(t)) badLit.push(`${ctx(t, reBad)}  ⟵ ${desc(el)}`)
      if (reMoneyNeg.test(t) || reMoneyBig.test(t)) money.push(`${ctx(t, reMoneyNeg.test(t) ? reMoneyNeg : reMoneyBig)}  ⟵ ${desc(el)}`)
      if (reIso.test(t)) iso.push(`${ctx(t, reIso)}  ⟵ ${desc(el)}`)
      const ph = (t.match(/\bunavailable\b|\bnot recorded\b|\bUNAVAILABLE\b|\bn\/a\b/gi) || []).length + (/^[—–-]$/.test(t) ? 1 : 0)
      if (ph) { placeholder += ph; if (phSamples.length < 8) phSamples.push(`${t.slice(0, 60)} ⟵ ${desc(el.parentElement || el)}`) }
    }

    // empty list items / bullets
    const emptyLi = Array.from(document.querySelectorAll('li')).filter(li => visible(li) && !(li as HTMLElement).innerText.trim() && !li.querySelector('img,svg,input,canvas,button')).map(desc)
    const emptyBullets = text.split('\n').filter(l => /^\s*[•·▪◦‣-]\s*$/.test(l)).length

    // text dumps inside list cards
    const dumps: string[] = []
    for (const el of Array.from(document.querySelectorAll('p, span, div, li, td'))) {
      const h = el as HTMLElement
      if (h.children.length > 3) continue
      const own = Array.from(h.childNodes).filter(n => n.nodeType === 3).map(n => n.nodeValue || '').join('').trim()
      if (own.length <= 400 || !visible(h)) continue
      if (!h.closest('li, tr, [class*="card" i], [class*="row" i], [role="listitem"], article')) continue
      dumps.push(`${own.length} chars: "${own.slice(0, 120).replace(/\s+/g, ' ')}…" ⟵ ${desc(h).slice(0, 80)}`)
    }

    // horizontal overflow (document + the scrolling <main>)
    const docOverflow = document.documentElement.scrollWidth - document.documentElement.clientWidth
    const mainOverflow = main ? main.scrollWidth - main.clientWidth : 0
    const overflowers: string[] = []
    if (docOverflow > 1 || mainOverflow > 1) {
      for (const el of Array.from(document.querySelectorAll('main *, body > div *'))) {
        const r = (el as HTMLElement).getBoundingClientRect()
        if (r.right > vw + 1 && r.width > 0 && r.width <= vw * 3 && visible(el)) {
          let scroller = false
          for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
            const ox = getComputedStyle(a).overflowX
            if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') { scroller = a !== main; if (scroller) break }
          }
          if (!scroller) { overflowers.push(`${desc(el)} right=${Math.round(r.right)}`); if (overflowers.length >= 6) break }
        }
      }
    }

    // mobile: tap targets + off-screen clipping
    const smallTargets: string[] = []; let smallCount = 0
    const clipped: string[] = []; let clipCount = 0
    if (mobile) {
      for (const el of Array.from(document.querySelectorAll('button, a[href], [role="button"], [role="tab"], input[type="checkbox"], input[type="radio"], select'))) {
        if (!visible(el)) continue
        const r = (el as HTMLElement).getBoundingClientRect()
        if (r.width < 32 || r.height < 32) {
          // inline text links inside prose are exempt (WCAG 2.5.8 inline exception)
          if (el.tagName === 'A' && el.parentElement && /^(P|SPAN|LI|TD)$/.test(el.parentElement.tagName) && (el.parentElement.innerText || '').length > (el as HTMLElement).innerText.length + 20) continue
          smallCount++; if (smallTargets.length < 10) smallTargets.push(`${desc(el)} ${Math.round(r.width)}x${Math.round(r.height)}`)
        }
      }
      for (const el of Array.from(document.querySelectorAll('main button, main a, main h1, main h2, main h3, main p, main [class*="card" i]'))) {
        if (!visible(el)) continue
        const r = (el as HTMLElement).getBoundingClientRect()
        if (r.left < -2 || r.right > vw + 2) {
          let inScroller = false
          for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
            const s = getComputedStyle(a)
            if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && a.tagName !== 'MAIN') { inScroller = true; break }
            if (s.position === 'fixed' && /translate/.test(s.transform)) { inScroller = true; break }
          }
          if (inScroller) continue
          clipCount++; if (clipped.length < 8) clipped.push(`${desc(el)} [${Math.round(r.left)}..${Math.round(r.right)}] vw=${vw}`)
        }
      }
    }
    const stale = /newer or different artifact available/i.test(text)
    const crash = /Something went wrong|This route crashed|RouteErrorBoundary|Unexpected Application Error/i.test(text) ? (text.match(/(Something went wrong|This route crashed|Unexpected Application Error)[^\n]{0,160}/i) || [''])[0] : ''
    return { badLit, money, iso, placeholder, phSamples, emptyLi, emptyBullets, dumps, docOverflow, mainOverflow, overflowers, smallTargets, smallCount, clipped, clipCount, stale, crash, textLen: text.length }
  }, { mobile })
}

// ---------------------------------------------------------------- findings
function inFlight(route: string, kind: string, detail: string): string | undefined {
  for (const [re, tag] of IN_FLIGHT) {
    if (!re.test(route)) continue
    if (route.startsWith('/v3/watch') && !/resolve|conflict/i.test(detail + kind)) continue
    return tag
  }
  return undefined
}
const seenState = new Map<string, Finding>()
function add(f: Omit<Finding, 'severity' | 'screenshot' | 'also_in'> & { screenshot?: string | null }) {
  const dk = `${f.route}|${f.viewport}|${f.kind}|${f.samples.slice(0, 5).join('|').replace(/\d+/g, '#')}`
  const prior = seenState.get(dk)
  if (prior && f.tab !== '*') { if (!prior.also_in.includes(f.tab) && prior.tab !== f.tab) prior.also_in.push(f.tab); return prior }
  const severity = KIND_SEVERITY[f.kind] || 'info'
  const finding: Finding = { ...f, severity, screenshot: f.screenshot ?? null, samples: f.samples.slice(0, 10), also_in: [] }
  seenState.set(dk, finding)
  const tag = inFlight(f.route, f.kind, f.detail + ' ' + f.samples.join(' ') + ' ' + f.tab)
  if (tag) finding.in_flight = tag
  findings.push(finding)
  return finding
}

async function recordState(page: Page, route: string, tab: string, vp: typeof VIEWPORTS[number], loadMs: number | null): Promise<Finding[]> {
  const before = findings.length
  const o = await inspect(page, vp.mobile).catch(e => { add({ route, tab, viewport: vp.name, kind: 'sweep_error', detail: `inspect failed: ${String(e).slice(0, 200)}`, samples: [], count: 1 }); return null })
  if (!o) return []
  const base = { route, tab, viewport: vp.name }
  if (loadMs != null && loadMs > SLOW_LOAD_MS) add({ ...base, kind: 'slow_load', detail: `settled after ${(loadMs / 1000).toFixed(1)}s (> ${SLOW_LOAD_MS / 1000}s)`, samples: [], count: 1 })
  if (o.crash) add({ ...base, kind: 'route_crash', detail: o.crash, samples: [o.crash], count: 1 })
  if (o.stale) add({ ...base, kind: 'stale_bundle', detail: 'stale bundle banner: "newer or different artifact available"', samples: [], count: 1 })
  if (o.badLit.length) add({ ...base, kind: 'literal_bad_value', detail: `${o.badLit.length} literal undefined/NaN/null/[object Object]/Invalid Date`, samples: o.badLit, count: o.badLit.length })
  if (o.money.length) add({ ...base, kind: 'money_format', detail: `${o.money.length} badly formatted money values ($-N or unseparated ≥5 digits)`, samples: o.money, count: o.money.length })
  if (o.iso.length) add({ ...base, kind: 'raw_iso_timestamp', detail: `${o.iso.length} raw ISO timestamps shown to the operator`, samples: o.iso, count: o.iso.length })
  if (o.emptyLi.length) add({ ...base, kind: 'empty_list_item', detail: `${o.emptyLi.length} empty <li>`, samples: o.emptyLi, count: o.emptyLi.length })
  if (o.emptyBullets) add({ ...base, kind: 'empty_bullet', detail: `${o.emptyBullets} bullet lines with no text`, samples: [], count: o.emptyBullets })
  if (o.dumps.length) add({ ...base, kind: 'text_dump', detail: `${o.dumps.length} text blocks > 400 chars inside list cards`, samples: o.dumps, count: o.dumps.length })
  if (o.docOverflow > 1 || o.mainOverflow > 1) add({ ...base, kind: 'horizontal_overflow', detail: `page scrolls sideways: document +${o.docOverflow}px, main +${o.mainOverflow}px`, samples: o.overflowers, count: Math.max(o.docOverflow, o.mainOverflow) })
  if (o.smallCount) add({ ...base, kind: 'small_tap_target', detail: `${o.smallCount} tap targets < 32px`, samples: o.smallTargets, count: o.smallCount })
  if (o.clipCount) add({ ...base, kind: 'offscreen_clip', detail: `${o.clipCount} elements clipped off-screen`, samples: o.clipped, count: o.clipCount })
  if (o.placeholder >= 5) add({ ...base, kind: 'placeholder_density', detail: `${o.placeholder} unavailable / not recorded / — placeholders`, samples: o.phSamples, count: o.placeholder })
  return findings.slice(before)
}

let shotSeq = 0
async function shoot(page: Page, route: string, tab: string, vp: string, list: Finding[]) {
  const worth = list.filter(f => !['density', 'info', 'expected'].includes(f.severity))
  if (!worth.length) return
  const name = `${String(++shotSeq).padStart(4, '0')}_${route.replace(/[^a-z0-9]+/gi, '_')}_${tab.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)}_${vp}.jpg`
  const p = path.join(SHOTS, name)
  try {
    await page.screenshot({ path: p, type: 'jpeg', quality: 60, fullPage: true, timeout: 15_000 })
    for (const f of list) f.screenshot = path.relative(OUT, p)
  } catch { /* screenshot best-effort */ }
}

// ---------------------------------------------------------------- tabs, detail, dead buttons
type Cand = { idx: number; label: string; kind: 'tab' | 'button' }
/** Tag candidates in-page with data-sweep-id, return labels. */
async function candidates(page: Page, which: 'tabs' | 'buttons' | 'row'): Promise<Cand[]> {
  return page.evaluate(({ which, writeSrc }) => {
    const WRITE = new RegExp(writeSrc, 'i')
    const visible = (el: Element) => { const r = (el as HTMLElement).getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }
    const label = (el: Element) => ((el as HTMLElement).innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 50)
    document.querySelectorAll('[data-sweep-id]').forEach(e => e.removeAttribute('data-sweep-id'))
    const scope = document.querySelector('main') || document.body
    const out: Array<{ idx: number; label: string; kind: 'tab' | 'button' }> = []
    let i = 0
    const take = (el: Element, kind: 'tab' | 'button') => { el.setAttribute('data-sweep-id', String(i)); out.push({ idx: i++, label: label(el), kind }) }
    const writey = (el: Element) => WRITE.test(label(el)) || WRITE.test(el.getAttribute('aria-label') || '') || WRITE.test(el.getAttribute('title') || '') || !!el.closest('form') // <button> defaults to type=submit, so only a real form counts
    if (which === 'tabs') {
      const seen = new Set<Element>()
      const isTabLike = (el: Element) => el.matches('[role="tab"], [aria-selected], [aria-pressed], [role="tablist"] button')
      const groups: Element[] = []
      scope.querySelectorAll('button, [role="tab"]').forEach(b => {
        const p = b.parentElement; if (!p || groups.includes(p)) return
        const kids = Array.from(p.children)
        const btns = kids.filter(k => k.matches('button, [role="tab"]'))
        if (isTabLike(b) || (btns.length >= 2 && btns.length >= kids.length * 0.7 && btns.every(x => label(x).length > 0 && label(x).length <= 32))) groups.push(p)
      })
      for (const g of groups) for (const b of Array.from(g.children)) {
        if (!b.matches('button, [role="tab"]') || seen.has(b) || !visible(b) || (b as HTMLButtonElement).disabled || writey(b)) continue
        seen.add(b); take(b, 'tab')
      }
    } else if (which === 'buttons') {
      scope.querySelectorAll('button, [role="button"], summary').forEach(b => {
        if (!visible(b) || (b as HTMLButtonElement).disabled || writey(b) || b.closest('nav') || b.matches('[role="tab"], [aria-selected]')) return
        const p = b.parentElement; const sibs = p ? Array.from(p.children).filter(k => k.matches('button')).length : 0
        if (sibs >= 2 && label(b).length <= 32 && p && Array.from(p.children).filter(k => k.matches('button')).length >= p.children.length * 0.7) return // tab group, handled
        take(b, 'button')
      })
    } else {
      // first clickable row/card in a list
      const rows = Array.from(scope.querySelectorAll('li, tr, [role="row"], [role="listitem"], article, [class*="card" i], [class*="row" i]'))
      for (const r of rows) {
        if (!visible(r) || r.closest('nav') || r.querySelector('table')) continue
        const s = getComputedStyle(r as HTMLElement)
        const clickable = s.cursor === 'pointer' || r.getAttribute('role') === 'button' || r.hasAttribute('tabindex')
        const txt = label(r)
        if (!clickable || txt.length < 4 || WRITE.test(txt.slice(0, 20))) continue
        take(r, 'button'); break
      }
    }
    return out
  }, { which, writeSrc: WRITE_WORDS.source })
}

async function domSignature(page: Page): Promise<string> {
  return page.evaluate(() => {
    const t = document.body.innerText || ''
    return `${location.pathname}${location.search}|${t.length}|${document.querySelectorAll('*').length}|${t.slice(0, 200)}|${t.slice(-200)}`
  }).catch(() => 'ERR')
}

async function clickSweep(page: Page, idx: number): Promise<boolean> {
  const loc = page.locator(`[data-sweep-id="${idx}"]`).first()
  try { await loc.scrollIntoViewIfNeeded({ timeout: 3000 }); await loc.click({ timeout: 4000 }); return true } catch { return false }
}

async function backToBase(page: Page, url: string, net: NetLog) {
  await page.keyboard.press('Escape').catch(() => {})
  const back = page.locator('main button, main a, [role="dialog"] button').filter({ hasText: /^\s*(←|‹|<)?\s*Back\b|^\s*(×|✕|Close)\s*$/ }).first()
  if (await back.isVisible({ timeout: 300 }).catch(() => false)) await back.click({ timeout: 2000 }).catch(() => {})
  if (page.url() !== url) { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => {}); await settle(page, net, 12_000) }
}

// ---------------------------------------------------------------- per route
async function sweepRoute(ctx: BrowserContext, route: string, vp: typeof VIEWPORTS[number], source: string) {
  const page = await ctx.newPage()
  await page.setViewportSize({ width: vp.width, height: vp.height })
  const net: NetLog = { inflight: new Set(), total: 0, lastChange: Date.now(), events: [], writes: [] }
  const lastClick = { label: '(page load)' }
  let currentTab = 'default'
  attachNet(page, net, lastClick)
  const consoleErrs: Array<{ tab: string; text: string }> = []
  const pageErrs: Array<{ tab: string; text: string }> = []
  page.on('console', m => { if (m.type() === 'error') consoleErrs.push({ tab: currentTab, text: m.text().slice(0, 300) }) })
  page.on('pageerror', e => pageErrs.push({ tab: currentTab, text: String(e.message || e).slice(0, 300) }))
  page.on('dialog', d => { d.dismiss().catch(() => {}) })
  const writes: Array<{ tab: string; by: string; req: string }> = []
  const sideEffects: string[] = []
  await page.route('**/*', async r => {
    const req = r.request()
    const m = req.method()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(m)) { writes.push({ tab: currentTab, by: lastClick.label, req: `${m} ${req.url().replace(BASE, '')}` }); return r.abort('blockedbyclient') }
    if (SIDE_EFFECT_URL.test(req.url())) { sideEffects.push(req.url().replace(BASE, '')); return r.abort('blockedbyclient') }
    return r.continue()
  })
  const url = BASE + route
  const t0 = Date.now()
  const cov = { route, viewport: vp.name, tabs: [] as string[], detail_opened: null as string | null, load_ms: 0, dead_probes: 0, source }
  coverage.push(cov)
  const routeDeadline = t0 + ROUTE_BUDGET_MS
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    const loadMs = (Date.now() - t0) + await settle(page, net)
    cov.load_ms = loadMs
    const f0 = await recordState(page, route, 'default', vp, loadMs)
    await shoot(page, route, 'default', vp.name, f0)

    // tabs (one level; each tab state inspected)
    const tabs = (await candidates(page, 'tabs')).slice(0, MAX_TABS_PER_PAGE)
    if (process.env.SWEEP_DEBUG) console.log('[debug] tabs', JSON.stringify(tabs.map(t => t.label)))
    const seenLabels = new Set<string>()
    for (const t of tabs) {
      if (Date.now() > routeDeadline) { add({ route, tab: t.label, viewport: vp.name, kind: 'sweep_error', detail: 'route time budget exhausted before all tabs were visited', samples: [], count: 1 }); break }
      if (seenLabels.has(t.label)) continue
      seenLabels.add(t.label)
      const findTab = async () => {
        await candidates(page, 'tabs') // re-tag (DOM may have re-rendered)
        const fresh = await page.locator('[data-sweep-id]').evaluateAll(els => els.map(e => ({ idx: Number(e.getAttribute('data-sweep-id')), label: ((e as HTMLElement).innerText || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 50) })))
        return fresh.find(x => x.label === t.label)
      }
      let hit = await findTab()
      if (!hit) { // the previous tab switched the view away: return to the route's default view and retry once
        await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {}); await settle(page, net, 12_000)
        hit = await findTab()
      }
      if (!hit) continue
      currentTab = t.label; lastClick.label = `tab "${t.label}"`
      if (!await clickSweep(page, hit.idx)) continue
      const ms = await settle(page, net, 15_000)
      if (new URL(page.url()).pathname !== new URL(url).pathname) { // a link to another route: swept on its own
        await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {}); await settle(page, net, 12_000); continue
      }
      cov.tabs.push(t.label)
      const ft = await recordState(page, route, t.label, vp, ms > SLOW_LOAD_MS ? ms : null)
      await shoot(page, route, t.label, vp.name, ft)
      if (new URL(page.url()).pathname !== new URL(url).pathname) { await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {}); await settle(page, net, 12_000) }
    }
    if (tabs.length) { currentTab = 'default'; await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {}); await settle(page, net, 12_000) }

    // first row detail sheet
    const row = await candidates(page, 'row')
    if (row.length && Date.now() < routeDeadline) {
      currentTab = `detail: ${row[0].label.slice(0, 30)}`; lastClick.label = `row "${row[0].label.slice(0, 30)}"`
      const before = await domSignature(page)
      if (await clickSweep(page, row[0].idx)) {
        await settle(page, net, 10_000)
        if (await domSignature(page) !== before) {
          cov.detail_opened = row[0].label.slice(0, 60)
          const fd = await recordState(page, route, currentTab, vp, null)
          await shoot(page, route, 'detail', vp.name, fd)
        }
        await backToBase(page, url, net)
      }
    }

    // dead buttons: mobile primary viewport only
    if (vp.name === 'm412' && Date.now() < routeDeadline) {
      currentTab = 'default'
      await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {}); await settle(page, net, 12_000)
      const btns = (await candidates(page, 'buttons')).slice(0, MAX_DEAD_PROBES)
      const dead: string[] = []
      const probed = new Set<string>()
      for (const b of btns) {
        if (Date.now() > routeDeadline) break
        if (!b.label || probed.has(b.label)) continue
        probed.add(b.label)
        await candidates(page, 'buttons')
        const fresh = await page.locator('[data-sweep-id]').evaluateAll(els => els.map(e => ({ idx: Number(e.getAttribute('data-sweep-id')), label: ((e as HTMLElement).innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 50) })))
        const hit = fresh.find(x => x.label === b.label)
        if (!hit) continue
        lastClick.label = `button "${b.label}"`
        const sig0 = await domSignature(page)
        const req0 = net.total
        await page.evaluate(() => { (window as any).__sweepMut = 0; const mo = new MutationObserver(ms => { (window as any).__sweepMut += ms.length }); mo.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true }); (window as any).__sweepMO = mo })
        const clicked = await clickSweep(page, hit.idx)
        if (!clicked) continue
        cov.dead_probes++
        await page.waitForTimeout(900)
        const mut = await page.evaluate(() => { const n = (window as any).__sweepMut; (window as any).__sweepMO?.disconnect(); return n }).catch(() => 1)
        const sig1 = await domSignature(page)
        if (mut === 0 && sig0 === sig1 && net.total === req0 && page.url() === url) dead.push(`"${b.label}"`)
        if (page.url() !== url || sig0 !== sig1) await backToBase(page, url, net)
      }
      if (dead.length) add({ route, tab: 'default', viewport: vp.name, kind: 'dead_button', detail: `${dead.length} buttons did nothing when tapped (no navigation, DOM change or request)`, samples: dead, count: dead.length })
    }
  } catch (e) {
    add({ route, tab: currentTab, viewport: vp.name, kind: 'sweep_error', detail: `sweep exception: ${String(e).slice(0, 240)}`, samples: [], count: 1 })
  }

  // network / console / write findings (aggregated per route+viewport+tab)
  const httpBad = new Map<string, { tab: string; n: number; status: string; code?: string }>()
  for (const ev of net.events) {
    const u = ev.url.replace(BASE, '')
    if ((ev.failure || '').startsWith('net::ERR_BLOCKED_BY_CLIENT')) continue // our own write/side-effect aborts
    if (ev.status != null && ev.status < 400) continue
    if (ev.status == null && /ERR_ABORTED/.test(ev.failure || '')) continue // navigation cancels in-flight fetches
    const key = `${ev.method} ${u.split('?')[0]} ${ev.status ?? ev.failure}`
    const cur = httpBad.get(key) || { tab: '', n: 0, status: String(ev.status ?? ev.failure), code: ev.code }
    cur.n++; httpBad.set(key, cur)
  }
  for (const [key, v] of httpBad) {
    // Ask-the-CIO routes refuse automated callers by design (403 AGENT_CALLER_REFUSED)
    const refused = v.status === '403' && /AGENT_CALLER/.test(v.code || '')
    add({ route, tab: '*', viewport: vp.name, kind: refused ? 'expected_refusal' : (/^\d+$/.test(v.status) ? 'http_error' : 'request_failed'), detail: `${key}${v.code ? ` ${v.code}` : ''}`, samples: [`${v.n}× ${key}${v.code ? ` ${v.code}` : ''}`], count: v.n })
  }
  const byTab = <T extends { tab: string; text: string }>(xs: T[]) => { const m = new Map<string, Set<string>>(); for (const x of xs) { if (!m.has(x.tab)) m.set(x.tab, new Set()); m.get(x.tab)!.add(x.text) } return m }
  for (const [tab, set] of byTab(pageErrs)) add({ route, tab, viewport: vp.name, kind: 'page_error', detail: `${set.size} uncaught exception(s)`, samples: [...set], count: set.size })
  for (const [tab, set] of byTab(consoleErrs.filter(c => !/Failed to load resource|ERR_BLOCKED_BY_CLIENT/.test(c.text)))) add({ route, tab, viewport: vp.name, kind: 'console_error', detail: `${set.size} console error(s)`, samples: [...set], count: set.size })
  for (const w of writes) add({ route, tab: w.tab, viewport: vp.name, kind: 'write_attempted', detail: `write attempted by ${w.by} — aborted`, samples: [w.req], count: 1 })
  if (sideEffects.length) add({ route, tab: '*', viewport: vp.name, kind: 'side_effect_blocked', detail: 'side-effect GET aborted', samples: [...new Set(sideEffects)], count: sideEffects.length })
  await page.close().catch(() => {})
  console.log(`[sweep] ${route} ${vp.name} ${((Date.now() - t0) / 1000).toFixed(0)}s tabs=${cov.tabs.length} detail=${cov.detail_opened ? 'y' : 'n'} probes=${cov.dead_probes}`)
}

// ---------------------------------------------------------------- report
function writeReport(routes: Array<{ route: string; source: string }>) {
  // findings that hit (nearly) every route are site-wide chrome; collapse them for the summary
  const byKindSample = new Map<string, Set<string>>()
  for (const f of findings) {
    const s = `${f.kind}|${(f.samples[0] || f.detail).replace(/\d+/g, '#').slice(0, 120)}`
    if (!byKindSample.has(s)) byKindSample.set(s, new Set())
    byKindSample.get(s)!.add(f.route)
  }
  const siteWide = new Set([...byKindSample].filter(([, r]) => r.size >= Math.max(5, routes.length * 0.6)).map(([k]) => k))
  const sig = (f: Finding) => `${f.kind}|${(f.samples[0] || f.detail).replace(/\d+/g, '#').slice(0, 120)}`
  const elapsed = (Date.now() - startedAt) / 1000
  const counts: Record<string, number> = {}
  for (const f of findings) counts[f.kind] = (counts[f.kind] || 0) + 1
  const json = {
    base_url: BASE, started_at: new Date(startedAt).toISOString(), elapsed_s: Math.round(elapsed), aborted,
    routes: routes.length, viewports: VIEWPORTS.map(v => v.name), states_visited: coverage.reduce((n, c) => n + 1 + c.tabs.length + (c.detail_opened ? 1 : 0), 0),
    tabs_visited: coverage.reduce((n, c) => n + c.tabs.length, 0), coverage, counts_by_kind: counts,
    site_wide_signatures: [...siteWide], findings,
  }
  fs.writeFileSync(path.join(OUT, 'findings.json'), JSON.stringify(json, null, 2))

  const L: string[] = []
  L.push(`# Site sweep — ${BASE}/v3`, '', `- started ${json.started_at}, ${Math.round(elapsed / 60)} min, ${routes.length} routes × ${VIEWPORTS.length} viewports, ${json.tabs_visited} tab states, ${coverage.filter(c => c.detail_opened).length} detail sheets`)
  if (aborted) L.push(`- **ABORTED:** ${aborted}`)
  L.push(`- findings by kind: ${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(', ')}`, '')
  if (siteWide.size) {
    L.push('## Site-wide (appear on most pages — fix once)', '')
    for (const s of siteWide) { const ex = findings.find(f => sig(f) === s)!; L.push(`- **${ex.severity}/${ex.kind}** on ${byKindSample.get(s)!.size} routes — ${ex.detail}${ex.samples[0] ? ` · e.g. \`${ex.samples[0].slice(0, 160)}\`` : ''}`) }
    L.push('')
  }
  const density = findings.filter(f => f.kind === 'placeholder_density').sort((a, b) => b.count - a.count).slice(0, 10)
  const pages = new Map<string, Finding[]>()
  for (const f of findings) { if (siteWide.has(sig(f)) || f.kind === 'placeholder_density') continue; if (!pages.has(f.route)) pages.set(f.route, []); pages.get(f.route)!.push(f) }
  const pageScore = (fs_: Finding[]) => Math.min(...fs_.map(f => SEVERITY_RANK[f.severity]))
  L.push('## By page (worst severity first)', '')
  for (const [route, fs_] of [...pages].sort((a, b) => pageScore(a[1]) - pageScore(b[1]) || b[1].length - a[1].length)) {
    L.push(`### ${route}${fs_.some(f => f.in_flight) ? ' — _in-flight_' : ''}`, '')
    // merge the same defect seen at several viewports / tabs into one line
    const merged = new Map<string, { f: Finding; vps: Set<string>; tabs: Set<string> }>()
    for (const f of fs_) {
      const k = `${f.kind}|${(f.samples[0] || f.detail).replace(/\d+/g, '#').slice(0, 140)}`
      const m = merged.get(k) || { f, vps: new Set<string>(), tabs: new Set<string>() }
      m.vps.add(f.viewport); m.tabs.add(f.tab); f.also_in.forEach(t => m.tabs.add(t)); merged.set(k, m)
    }
    for (const { f, vps, tabs } of [...merged.values()].sort((a, b) => SEVERITY_RANK[a.f.severity] - SEVERITY_RANK[b.f.severity] || b.f.count - a.f.count)) {
      const tl = [...tabs]; const tabTxt = tl.length > 3 ? `${tl.slice(0, 3).join(', ')} +${tl.length - 3}` : tl.join(', ')
      L.push(`- **${f.severity}/${f.kind}** [${[...vps].join(',')} · ${tabTxt}] ${f.detail}${f.in_flight ? ` _(${f.in_flight})_` : ''}${f.screenshot ? ` — ${f.screenshot}` : ''}`)
      for (const s of f.samples.slice(0, 3)) L.push(`  - \`${s.replace(/`/g, "'").slice(0, 200)}\``)
    }
    L.push('')
  }
  L.push('## Placeholder density (top offenders, not errors)', '')
  for (const f of density) L.push(`- ${f.route} [${f.viewport} · ${f.tab}] ${f.count} placeholders`)
  L.push('', '## Coverage', '', '| route | source | viewport | load s | tabs | detail | probes |', '|---|---|---|---|---|---|---|')
  for (const c of coverage) L.push(`| ${c.route} | ${c.source} | ${c.viewport} | ${(c.load_ms / 1000).toFixed(1)} | ${c.tabs.length} | ${c.detail_opened ? 'yes' : '—'} | ${c.dead_probes} |`)
  fs.writeFileSync(path.join(OUT, 'summary.md'), L.join('\n') + '\n')
}

// ---------------------------------------------------------------- main
async function main() {
  const refusal = marketWindowRefusal()
  if (refusal) { console.error(refusal); process.exit(3) }
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ deviceScaleFactor: 1, serviceWorkers: 'block' })
  ctx.on('page', async p => { if (await p.opener()) p.close().catch(() => {}) }) // popups/target=_blank never stay open
  const probe = await ctx.newPage()
  await probe.setViewportSize({ width: 1440, height: 900 })
  const nav = await navRoutes(probe)
  await probe.close()
  const routes: Array<{ route: string; source: string }> = nav.map(r => ({ route: r, source: 'nav' }))
  if (!SKIP_ROUTER_ONLY) for (const r of routerRoutes()) if (!routes.some(x => x.route === r)) routes.push({ route: r, source: 'router-only' })
  const todo = routes.filter(r => !SKIP_ROUTES.some(re => re.test(r.route)) && (!ROUTE_FILTER.length || ROUTE_FILTER.some((f: string) => r.route.includes(f))))
  console.log(`[sweep] ${todo.length} routes (${nav.length} nav) × ${VIEWPORTS.length} viewports → ${OUT}`)
  const onSig = () => { aborted = aborted || 'interrupted'; writeReport(todo); process.exit(130) }
  process.on('SIGINT', onSig); process.on('SIGTERM', onSig)
  outer: for (const r of todo) {
    // router-only routes are secondary: primary mobile viewport only
    const vps = r.source === 'nav' ? VIEWPORTS : VIEWPORTS.filter(v => v.name === 'm412').concat(VIEWPORTS.length && !VIEWPORTS.some(v => v.name === 'm412') ? [VIEWPORTS[0]] : [])
    for (const vp of vps) {
      if (!await memoryGate()) { console.error(`[sweep] ABORT: ${aborted}`); break outer }
      await sweepRoute(ctx, r.route, vp, r.source)
      writeReport(todo) // incremental: a crash keeps what was found
    }
  }
  await browser.close()
  writeReport(todo)
  console.log(`[sweep] done in ${((Date.now() - startedAt) / 60000).toFixed(1)} min; ${findings.length} findings → ${OUT}/summary.md`)
  if (aborted) process.exit(2) // partial sweep: never report success
}
main().catch(e => { console.error(e); try { writeReport([]) } catch { /* */ } process.exit(1) })
