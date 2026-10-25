/**
 * Design capture: read-only screenshots of every registered page and tab at 1440 / 412 / 390 (design/README.md, v000
 * "as built" baseline and the post-release / nightly live checks). Patterns from e2e-live/site-sweep.ts.
 *
 * Tabs are named default, t01, t02 … (labels can carry tickers and counts); labels stay in the private index.json.
 * PRIVATE OUTPUT ONLY. Screenshots of the live site show real holdings and the repository is public: images go to
 *   $DESIGN_CAPTURE_STORE/pages/<page>/<version>/capture/<page>-<tab>-<width>.png   (dirs 0700, files 0600)
 * and the manifest (paths relative to the page folder + sha256) to $DESIGN_CAPTURE_MANIFEST. Nothing is written
 * inside the repository; scripts/design_capture_ingest.py copies only fingerprints into design/.
 *
 * READ-ONLY by construction: every non-GET/HEAD/OPTIONS request is aborted; side-effect GETs (morning brief,
 * ?refresh= / force= / run= / rerun=) are aborted; dialogs are dismissed; only tab-like controls whose label is not a
 * write word are clicked. One page, one context. Before every page the guard
 * (scripts/lib/design_capture_guard.py) must report portfolio-server MemoryCurrent < 1.2 GB (wait 30 s, at most 4
 * tries; abort at 1.3 GB or when unreadable). Production is refused 04:00-16:15 ET Mon-Fri (§28.8).
 *
 * Pages that need a signed-in reader: a page whose API calls answer 401/403 is recorded as needs_reader and its
 * screenshots are not offered as a baseline. The read-only agent reader identity is pluggable without code here:
 *   DESIGN_CAPTURE_STORAGE_STATE  Playwright storage-state JSON prepared by the reader tooling (never by this script)
 * This script never reads credentials, ~/.config/tradeai or any .env file.
 *
 * Env (read literally): DESIGN_CAPTURE_BASE_URL (default http://127.0.0.1:7777), DESIGN_CAPTURE_STORE,
 * DESIGN_CAPTURE_MANIFEST, DESIGN_CAPTURE_VERSION (default v000), DESIGN_CAPTURE_PAGES (comma page ids),
 * DESIGN_CAPTURE_WIDTHS (comma: 1440,412,390), DESIGN_CAPTURE_STORAGE_STATE, DESIGN_CAPTURE_GUARD (python guard path).
 * Run through scripts/design_capture.sh.
 */
import { chromium, type Page, type BrowserContext } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'

const BASE = (process.env.DESIGN_CAPTURE_BASE_URL || 'http://127.0.0.1:7777').replace(/\/$/, '')
const STORE = process.env.DESIGN_CAPTURE_STORE || ''
const MANIFEST = process.env.DESIGN_CAPTURE_MANIFEST || ''
const VERSION = process.env.DESIGN_CAPTURE_VERSION || 'v000'
const PAGE_FILTER = (process.env.DESIGN_CAPTURE_PAGES || '').split(',').map(s => s.trim()).filter(Boolean)
const WIDTH_FILTER = (process.env.DESIGN_CAPTURE_WIDTHS || '').split(',').map(s => Number(s.trim())).filter(Boolean)
const STORAGE_STATE = process.env.DESIGN_CAPTURE_STORAGE_STATE || ''
const GUARD = process.env.DESIGN_CAPTURE_GUARD || ''
const APP = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const REGISTRY = path.resolve(APP, '..', '..', 'design', 'registry.json')

const VIEWPORTS = [
  { width: 1440, height: 900, mobile: false },
  { width: 412, height: 915, mobile: true },
  { width: 390, height: 844, mobile: true },
].filter(v => !WIDTH_FILTER.length || WIDTH_FILTER.includes(v.width))
const MAX_TABS = 16
const SETTLE_CAP_MS = 20_000
const WRITE_WORDS = /\b(approve|approv|reject|submit|send|resolve|decision|decide|save|delete|archive|ask|apply|run|re-?run|retry|ack|acknowledge|place|order|buy|sell|stop|revoke|grant|promote|rollback|roll back|refresh|reload|confirm|cancel|execute|dismiss|snooze|mute|enable|disable|activate|deactivate|close position|trim|add to|propose|publish|reset|clear|log out|logout|sign out|upload|download|export|copy|generate|create|new|sync|import|edit|update|scan|backfill|reconcile|reauth|re-auth|connect|disconnect|trigger|start|restart|kill|pause|resume|accept|decline|override|remove|watch this|unwatch|pin|unpin|follow|vote)\b/i
// Shell-wide calls every page makes (the Ask the CIO bar's tracked asks). Their refusal is the shell, not the page:
// recorded as shell_refusals and shown in the screenshot, but it does not make the page needs_reader.
const SHELL_ENDPOINTS = ['/api/v2/cio/asks/tracked', ...(process.env.DESIGN_CAPTURE_SHELL_ENDPOINTS || '').split(',').map(s => s.trim()).filter(Boolean)]
const SIDE_EFFECT_URL = /\/v2\/(bot-)?morning-brief|[?&](refresh|force|rerun|run)=(1|true)/i

type Shot = { path: string; sha256: string; bytes: number; role: 'capture'; width: number; tab: string; label: string }
type PageResult = { page: string; route: string; shots: Shot[]; tabs: string[]; needs_reader: boolean; auth_refusals: string[]; shell_refusals: string[];
  blocked_writes: string[]; blocked_side_effects: string[]; errors: string[]; memory: Array<{ at: string; bytes: number | null; verdict: string }> }
const results: PageResult[] = []
const startedAt = new Date().toISOString()
let aborted: string | null = null

function fail(msg: string, code: number): never { console.error(`[design-capture] ${msg}`); process.exit(code) }
function guard(check: 'window' | 'memory'): { code: number; out: { verdict?: string; memory_bytes?: number | null; reason?: string | null } } {
  try {
    const out = execFileSync('python3', [GUARD, check, '--base', BASE], { encoding: 'utf8', timeout: 15_000 })
    return { code: 0, out: JSON.parse(out) }
  } catch (e) {
    const err = e as { status?: number; stdout?: string }
    let out = {}
    try { out = JSON.parse(err.stdout || '{}') } catch { /* unreadable */ }
    return { code: err.status ?? 4, out }
  }
}
async function memoryGate(r: PageResult): Promise<boolean> {
  for (let attempt = 0; attempt < 4; attempt++) {
    const { code, out } = guard('memory')
    r.memory.push({ at: new Date().toISOString(), bytes: out.memory_bytes ?? null, verdict: out.verdict || String(code) })
    if (code === 0) return true
    if (code !== 3) { aborted = out.reason || 'memory guard abort'; return false }
    console.log(`[design-capture] ${out.reason}`)
    await new Promise(res => setTimeout(res, 30_000))
  }
  aborted = 'portfolio-server memory stayed >= 1.2 GB for 2 minutes'
  return false
}


async function settle(page: Page, inflight: { n: number; last: number }, cap = SETTLE_CAP_MS) {
  const t0 = Date.now()
  let lastLen = -1, stable = Date.now()
  while (Date.now() - t0 < cap) {
    await page.waitForTimeout(250)
    const { len, loading } = await page.evaluate(() => {
      const t = document.body?.innerText || ''
      return { len: t.length, loading: /\bLoading\b[^\n]{0,40}(…|\.\.\.)|^\s*Loading\s*$/m.test(t) || !!document.querySelector('[aria-busy="true"]') }
    }).catch(() => ({ len: 0, loading: true }))
    if (len !== lastLen) { lastLen = len; stable = Date.now() }
    if (inflight.n === 0 && Date.now() - inflight.last > 600 && !loading && Date.now() - stable > 600 && len > 0) return
  }
}

/** Tag tab-like controls (role=tab, aria-selected/pressed, uniform button groups) that are not write actions. */
async function tabCandidates(page: Page): Promise<string[]> {
  return page.evaluate(({ writeSrc, max }) => {
    const WRITE = new RegExp(writeSrc, 'i')
    const visible = (el: Element) => { const r = (el as HTMLElement).getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }
    const label = (el: Element) => ((el as HTMLElement).innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 50)
    document.querySelectorAll('[data-capture-tab]').forEach(e => e.removeAttribute('data-capture-tab'))
    const scope = document.querySelector('main') || document.body
    const groups: Element[] = []
    scope.querySelectorAll('button, [role="tab"]').forEach(b => {
      const p = b.parentElement; if (!p || groups.includes(p)) return
      const kids = Array.from(p.children), btns = kids.filter(k => k.matches('button, [role="tab"]'))
      const tabLike = b.matches('[role="tab"], [aria-selected], [aria-pressed], [role="tablist"] button')
      if (tabLike || (btns.length >= 2 && btns.length >= kids.length * 0.7 && btns.every(x => label(x).length > 0 && label(x).length <= 32))) groups.push(p)
    })
    const out: string[] = []
    for (const g of groups) for (const b of Array.from(g.children)) {
      if (out.length >= max) break
      if (!b.matches('button, [role="tab"]') || !visible(b) || (b as HTMLButtonElement).disabled || b.closest('form')) continue
      const l = label(b)
      if (!l || WRITE.test(l) || out.includes(l)) continue
      b.setAttribute('data-capture-tab', l)
      out.push(l)
    }
    return out
  }, { writeSrc: WRITE_WORDS.source, max: MAX_TABS })
}

function writePrivate(file: string, data: Buffer) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
  fs.writeFileSync(file, data, { mode: 0o600 })
  fs.chmodSync(file, 0o600)
}

/** Tab labels can carry tickers and counts (e.g. a symbol chip, "Held 9"), so file names and the committed status use
 *  only a stable index (default, t01, t02, …); the label -> index map stays in the private capture/index.json. */
function tabKey(r: PageResult, tab: string): string {
  if (tab === 'default') return 'default'
  let i = r.tabs.indexOf(tab)
  if (i < 0) { r.tabs.push(tab); i = r.tabs.length - 1 }
  return 't' + String(i + 1).padStart(2, '0')
}

async function shoot(page: Page, r: PageResult, tab: string, width: number) {
  const key = tabKey(r, tab)
  const rel = `${VERSION}/capture/${r.page}-${key}-${width}.png`
  const buf = await page.screenshot({ type: 'png', fullPage: false, timeout: 15_000 })
  writePrivate(path.join(STORE, 'pages', r.page, rel), buf)
  r.shots.push({ path: rel, sha256: crypto.createHash('sha256').update(buf).digest('hex'), bytes: buf.length, role: 'capture', width, tab: key, label: tab })
  writePrivate(path.join(STORE, 'pages', r.page, VERSION, 'capture', 'index.json'), Buffer.from(JSON.stringify({ tabs: r.tabs.map((l, i) => ({ key: 't' + String(i + 1).padStart(2, '0'), label: l })) }, null, 1) + '\n'))
}

async function capturePage(ctx: BrowserContext, pageId: string, route: string) {
  const r: PageResult = { page: pageId, route, shots: [], tabs: [], needs_reader: false, auth_refusals: [], shell_refusals: [], blocked_writes: [],
    blocked_side_effects: [], errors: [], memory: [] }
  results.push(r)
  for (const vp of VIEWPORTS) {
    if (!await memoryGate(r)) return
    const page = await ctx.newPage()
    await page.setViewportSize({ width: vp.width, height: vp.height })
    const inflight = { n: 0, last: Date.now() }
    page.on('request', () => { inflight.n++; inflight.last = Date.now() })
    const done = () => { inflight.n = Math.max(0, inflight.n - 1); inflight.last = Date.now() }
    page.on('requestfinished', done); page.on('requestfailed', done)
    page.on('dialog', d => { d.dismiss().catch(() => {}) })
    page.on('response', async resp => {
      if ((resp.status() === 401 || resp.status() === 403) && resp.url().includes('/api/')) {
        const code = ((await resp.text().catch(() => '')).match(/[A-Z][A-Z_]{6,}/) || [''])[0]
        const u = new URL(resp.url())
        const entry = `${resp.status()} ${u.pathname}${code ? ' ' + code : ''}`
        const shell = SHELL_ENDPOINTS.includes(u.pathname)
        const list = shell ? r.shell_refusals : r.auth_refusals
        if (!list.includes(entry)) list.push(entry)
        if (!shell) r.needs_reader = true
      }
    })
    await page.route('**/*', async rt => {
      const req = rt.request()
      if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method())) { r.blocked_writes.push(`${req.method()} ${new URL(req.url()).pathname}`); return rt.abort('blockedbyclient') }
      if (SIDE_EFFECT_URL.test(req.url())) { r.blocked_side_effects.push(new URL(req.url()).pathname); return rt.abort('blockedbyclient') }
      return rt.continue()
    })
    const url = BASE + '/v3' + (route === '/' ? '/' : route)
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await settle(page, inflight)
      await shoot(page, r, 'default', vp.width)
      const tabs = await tabCandidates(page)
      for (const label of tabs) {
        await tabCandidates(page) // re-tag after re-render
        const loc = page.locator(`[data-capture-tab="${label.replace(/"/g, '\\"')}"]`).first()
        if (!await loc.isVisible().catch(() => false)) {
          await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => {}); await settle(page, inflight, 12_000)
          await tabCandidates(page)
          if (!await loc.isVisible().catch(() => false)) continue
        }
        try { await loc.click({ timeout: 4000 }) } catch { continue }
        await settle(page, inflight, 12_000)
        await shoot(page, r, label, vp.width)
        if (page.url().split('?')[0] !== url.split('?')[0] && !page.url().startsWith(url)) {
          await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => {}); await settle(page, inflight, 12_000)
        }
      }
    } catch (e) {
      r.errors.push(`${vp.width}: ${String(e).slice(0, 200)}`)
    } finally {
      await page.close().catch(() => {})
    }
    writeManifest()
  }
}

function writeManifest() {
  const doc = { schema: 'DesignCaptureManifest@v1', base: BASE, version: VERSION, started_at: startedAt, finished_at: new Date().toISOString(),
    aborted, widths: VIEWPORTS.map(v => v.width), reader_identity: STORAGE_STATE ? 'storage-state supplied' : 'none', pages: results }
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true })
  fs.writeFileSync(MANIFEST, JSON.stringify(doc, null, 2) + '\n', { mode: 0o600 })
}

async function main() {
  if (!STORE || !MANIFEST || !GUARD) fail('DESIGN_CAPTURE_STORE, DESIGN_CAPTURE_MANIFEST and DESIGN_CAPTURE_GUARD are required (use scripts/design_capture.sh)', 2)
  const repo = path.resolve(APP, '..', '..')
  if (path.resolve(STORE).startsWith(repo + path.sep) || path.resolve(MANIFEST).startsWith(repo + path.sep)) fail('refusing to write captures inside the repository (public repo)', 2)
  const w = guard('window')
  if (w.code !== 0) fail(w.out.reason || 'window refused', 3)
  const registry = JSON.parse(fs.readFileSync(REGISTRY, 'utf8')) as { pages: Array<{ id: string; route: string | null }> }
  const todo = registry.pages.filter(p => p.route && (!PAGE_FILTER.length || PAGE_FILTER.includes(p.id)))
  console.log(`[design-capture] ${todo.length} pages × ${VIEWPORTS.length} widths → ${STORE}/pages/<page>/${VERSION}/capture`)
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ deviceScaleFactor: 1, serviceWorkers: 'block', ...(STORAGE_STATE ? { storageState: STORAGE_STATE } : {}) })
  ctx.on('page', async p => { if (await p.opener()) p.close().catch(() => {}) })
  const onSig = () => { aborted = aborted || 'interrupted'; writeManifest(); process.exit(130) }
  process.on('SIGINT', onSig); process.on('SIGTERM', onSig)
  for (const p of todo) {
    if (guard('window').code !== 0) { aborted = 'market-hours window reached during the run'; break }
    await capturePage(ctx, p.id, p.route as string)
    if (aborted) break
    const last = results[results.length - 1]
    console.log(`[design-capture] ${p.id}: ${last.shots.length} shots, ${last.tabs.length} tabs${last.needs_reader ? ' · NEEDS READER' : ''}`)
  }
  await browser.close()
  writeManifest()
  console.log(`[design-capture] done: ${results.reduce((n, r) => n + r.shots.length, 0)} screenshots; manifest ${MANIFEST}`)
  if (aborted) { console.error(`[design-capture] ABORTED: ${aborted}`); process.exit(2) }
}
main().catch(e => { console.error(e); try { writeManifest() } catch { /* */ } process.exit(1) })
