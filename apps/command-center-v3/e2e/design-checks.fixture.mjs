/** Design checks on FIXTURE data (AGENTS.md §28.13 proposed, design/README.md, design/system/breakpoints.md).
 *
 *   node e2e/design-checks.fixture.mjs <fresh-out-dir>                 render every registry page at 1440/412/390,
 *                                                                       phone rules ratchet (exit 1 on a new or a
 *                                                                       fixed-but-still-listed violation)
 *   node e2e/design-checks.fixture.mjs <out-dir> --visual-verdict      exit 1 when a screenshot differs from its
 *                                                                       committed fixture baseline beyond tolerance
 *   node e2e/design-checks.fixture.mjs <fresh-out-dir> --update        rewrite the committed baselines + phone baseline
 *
 * Serves the BUILT app (dist/) from a local static server. Every /api request is intercepted in the browser:
 * there is no live server, proxy, credential or broker anywhere in this run. The app receives only an explicit
 * "fixture gap" (503) for data endpoints, so every page renders its real chrome and its gap states — sample data
 * only, never the operator's. Non-GET requests and any non-local host are aborted and fail the run. Clock fixed.
 *
 * Visual compare is report-only until 2026-11-01 (see .github/workflows/design-checks.yml).
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import {fileURLToPath} from 'node:url'
import {chromium} from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repo = path.resolve(app, '../..')
const here = path.join(app, 'e2e', 'design-checks')
const BASELINES = path.join(here, 'baselines')
const PHONE_BASELINE = path.join(here, 'phone_rules_baseline.json')
const out = process.argv[2]
const mode = process.argv.includes('--visual-verdict') ? 'verdict' : process.argv.includes('--update') ? 'update' : 'check'
assert(out, 'Explicit output directory required')
const CLOCK = '2026-10-23T14:00:00Z'
const TOLERANCE = 0.01 // share of pixels that may differ (channel delta > 32) before a page counts as changed
const VIEWPORTS = [{w: 1440, h: 900}, {w: 412, h: 915}, {w: 390, h: 844}]
const RULES = ['fixed_chrome', 'tap_target', 'horizontal_overflow', 'raw_iso', 'empty_bullet']

if (mode === 'verdict') {
  const report = JSON.parse(fs.readFileSync(path.join(out, 'report.json'), 'utf8'))
  const changed = report.visual.filter(v => v.status !== 'same')
  for (const v of changed) console.log(`visual ${v.status}: ${v.page} @${v.width} diff=${v.diff_ratio ?? 'n/a'}`)
  console.log(`visual compare: ${report.visual.length - changed.length}/${report.visual.length} within tolerance ${TOLERANCE}`)
  process.exit(changed.length ? 1 : 0)
}

fs.mkdirSync(out, {recursive: false})
for (const d of ['shots', 'text']) fs.mkdirSync(path.join(out, d))
const dist = path.join(app, 'dist')
assert(fs.existsSync(path.join(dist, 'index.html')), 'Run npm run build first (dist/index.html missing)')
const registry = JSON.parse(fs.readFileSync(path.join(repo, 'design/registry.json'), 'utf8'))
const only = (process.env.DESIGN_CHECK_PAGES || '').split(',').filter(Boolean)
const pages = registry.pages.filter(p => p.route && (!only.length || only.includes(p.id)))
const buildMeta = fs.readFileSync(path.join(dist, 'build-meta.json'))

const types = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json'}
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  if (req.method !== 'GET' || !url.pathname.startsWith('/v3')) { res.writeHead(404); return res.end() }
  let rel = decodeURIComponent(url.pathname.replace(/^\/v3\/?/, ''))
  let file = path.join(dist, rel)
  if (!file.startsWith(dist) || !rel || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html')
  res.writeHead(200, {'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store'})
  fs.createReadStream(file).pipe(res)
})
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve) })
const origin = `http://127.0.0.1:${server.address().port}`

const violations = []
const unexpected = []
const shots = []
const timings = {}
const t0 = Date.now()
// Same fonts everywhere (e2e/design-checks/fonts.conf): host and runner differ in their default sans otherwise.
const browser = await chromium.launch({env: {...process.env, FONTCONFIG_FILE: path.join(here, 'fonts.conf')}})
try {
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({viewport: {width: vp.w, height: vp.h}, deviceScaleFactor: 1, reducedMotion: 'reduce',
      colorScheme: 'dark', locale: 'en-US', timezoneId: 'America/New_York', serviceWorkers: 'block'})
    await context.route('**/*', route => {
      const req = route.request()
      const u = new URL(req.url())
      if (u.origin !== origin) { unexpected.push(`external ${req.method()} ${u.host}`); return route.abort() }
      if (req.method() !== 'GET') { unexpected.push(`${req.method()} ${u.pathname}`); return route.abort() }
      if (u.pathname === '/v3/build-meta.json') return route.fulfill({status: 200, contentType: 'application/json', body: buildMeta})
      if (u.pathname.startsWith('/api/')) {
        return route.fulfill({status: 503, contentType: 'application/json',
          body: JSON.stringify({ok: false, error: 'FIXTURE_GAP', detail: 'design-checks fixture: no data for this source'})})
      }
      return route.continue()
    })
    for (const pg of pages) {
      const page = await context.newPage()
      await page.clock.setFixedTime(new Date(CLOCK))
      const started = Date.now()
      await page.goto(`${origin}/v3${pg.route === '/' ? '/' : pg.route}`, {waitUntil: 'domcontentloaded', timeout: 30_000})
      await page.waitForLoadState('networkidle', {timeout: 8_000}).catch(() => {})
      await page.addStyleTag({content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}'})
      await page.waitForTimeout(400)
      const name = `${pg.id}-${vp.w}`
      const shot = path.join(out, 'shots', `${name}.png`)
      await page.screenshot({path: shot, animations: 'disabled', mask: [page.locator('[data-testid="cc-loaded-build"]')]})
      const text = await page.evaluate(() => document.body.innerText)
      fs.writeFileSync(path.join(out, 'text', `${name}.txt`), text)
      if (vp.w < 821) {
        const found = await page.evaluate(measurePhoneRules)
        for (const rule of RULES) if (found[rule].count) violations.push({key: `${pg.id}|${vp.w}|${rule}`, count: found[rule].count, samples: found[rule].samples})
      }
      shots.push({page: pg.id, width: vp.w, file: shot})
      timings[name] = Date.now() - started
      await page.close()
    }
    await context.close()
  }
  // Visual compare in the browser (no image library dependency): decode both PNGs on a canvas and count pixels whose
  // largest channel difference exceeds 32.
  const cmp = await browser.newPage()
  const visual = []
  for (const s of shots) {
    const base = path.join(BASELINES, `${s.page}-${s.width}.png`)
    if (!fs.existsSync(base)) { visual.push({page: s.page, width: s.width, status: 'no_baseline', diff_ratio: null}); continue }
    const ratio = await cmp.evaluate(async ([a, b]) => {
      const load = src => new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = src })
      const [x, y] = await Promise.all([load(a), load(b)])
      if (x.width !== y.width || x.height !== y.height) return 1
      const c = document.createElement('canvas'); c.width = x.width; c.height = x.height
      const g = c.getContext('2d', {willReadFrequently: true})
      g.drawImage(x, 0, 0); const p = g.getImageData(0, 0, c.width, c.height).data
      g.clearRect(0, 0, c.width, c.height); g.drawImage(y, 0, 0); const q = g.getImageData(0, 0, c.width, c.height).data
      let n = 0
      for (let i = 0; i < p.length; i += 4) if (Math.max(Math.abs(p[i] - q[i]), Math.abs(p[i + 1] - q[i + 1]), Math.abs(p[i + 2] - q[i + 2])) > 32) n++
      return n / (p.length / 4)
    }, [`data:image/png;base64,${fs.readFileSync(s.file).toString('base64')}`, `data:image/png;base64,${fs.readFileSync(base).toString('base64')}`])
    visual.push({page: s.page, width: s.width, status: ratio <= TOLERANCE ? 'same' : 'changed', diff_ratio: Number(ratio.toFixed(5))})
  }
  await cmp.close()

  const baseline = fs.existsSync(PHONE_BASELINE) ? JSON.parse(fs.readFileSync(PHONE_BASELINE, 'utf8')).violations : {}
  const current = Object.fromEntries(violations.map(v => [v.key, v.count]))
  const added = Object.entries(current).filter(([k, n]) => n > (baseline[k] ?? 0)).map(([k, n]) => `${k}: ${n} (baseline ${baseline[k] ?? 0})`)
  const improved = Object.entries(baseline).filter(([k, n]) => (current[k] ?? 0) < n).map(([k, n]) => `${k}: ${current[k] ?? 0} (baseline ${n})`)
  const report = {schema: 'DesignChecksReport@v1', clock: CLOCK, pages: pages.length, viewports: VIEWPORTS.map(v => v.w),
    seconds: Math.round((Date.now() - t0) / 1000), unexpected, phone: {violations, new: added, ratchet_down: improved}, visual, timings}
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2))

  if (mode === 'update') {
    fs.mkdirSync(BASELINES, {recursive: true})
    for (const s of shots) fs.copyFileSync(s.file, path.join(BASELINES, `${s.page}-${s.width}.png`))
    fs.writeFileSync(PHONE_BASELINE, JSON.stringify({schema: 'DesignPhoneRulesBaseline@v1',
      _about: 'Ratchet of phone-rule violations measured on fixture data at 412 and 390 (design/system/breakpoints.md). A count may only go down; regenerate with --update after fixing.',
      measured_at: new Date().toISOString().slice(0, 10), rules: RULES,
      violations: Object.fromEntries(Object.entries(current).sort())}, null, 2) + '\n')
    console.log(`updated ${shots.length} baselines and ${Object.keys(current).length} phone-rule entries`)
  }
  const changed = visual.filter(v => v.status !== 'same').length
  console.log(`design checks: ${pages.length} pages × ${VIEWPORTS.length} widths in ${report.seconds}s; phone violations ${violations.length} keys ` +
    `(${added.length} new, ${improved.length} improved); visual ${visual.length - changed}/${visual.length} same; unexpected ${unexpected.length}`)
  for (const a of added) console.log('NEW phone violation: ' + a)
  for (const a of improved) console.log('FIXED (remove from baseline with --update): ' + a)
  for (const u of [...new Set(unexpected)]) console.log('UNEXPECTED request: ' + u)
  if (mode === 'check' && (added.length || improved.length || unexpected.length)) process.exitCode = 1
} finally {
  await browser.close()
  server.close()
}

/** In-page: phone rules from design/system/breakpoints.md. */
function measurePhoneRules() {
  const vh = window.innerHeight, vw = window.innerWidth
  const visible = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05 }
  const desc = el => `${el.tagName.toLowerCase()}${el.getAttribute('data-testid') ? `[${el.getAttribute('data-testid')}]` : ''} "${(el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 40)}"`
  const res = {}
  // Fixed chrome: the parts of the viewport that do not scroll with the page. When <main> is the scroller (app shell
  // 100vh), everything above and below it is fixed; add fixed/sticky elements inside it.
  const main = document.querySelector('main')
  const intervals = []
  const docScrolls = document.documentElement.scrollHeight > document.documentElement.clientHeight + 1
  if (main && !docScrolls) {
    const r = main.getBoundingClientRect()
    if (r.top > 0) intervals.push([0, Math.min(r.top, vh)])
    if (r.bottom < vh) intervals.push([Math.max(r.bottom, 0), vh])
  }
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el)
    if ((s.position === 'fixed' || s.position === 'sticky') && visible(el)) {
      const r = el.getBoundingClientRect()
      if (r.height >= vh * 0.9) continue // a full-screen sheet is content, not chrome
      intervals.push([Math.max(0, r.top), Math.min(vh, r.bottom)])
    }
  }
  intervals.sort((a, b) => a[0] - b[0])
  let covered = 0, end = -1
  for (const [a, b] of intervals) { if (b <= a) continue; if (a > end) { covered += b - a; end = b } else if (b > end) { covered += b - end; end = b } }
  const share = covered / vh
  res.fixed_chrome = {count: share > 0.15 ? 1 : 0, samples: [`${Math.round(share * 100)}% of ${vh}px`]}
  const small = []
  for (const el of document.querySelectorAll('button, a[href], [role="button"], [role="tab"], input[type="checkbox"], input[type="radio"], select')) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if (r.width >= 44 && r.height >= 44) continue
    if (el.tagName === 'A' && el.parentElement && /^(P|SPAN|LI|TD)$/.test(el.parentElement.tagName) && (el.parentElement.innerText || '').length > (el.innerText || '').length + 20) continue
    small.push(`${desc(el)} ${Math.round(r.width)}x${Math.round(r.height)}`)
  }
  res.tap_target = {count: small.length, samples: small.slice(0, 8)}
  const over = Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, main ? main.scrollWidth - main.clientWidth : 0)
  res.horizontal_overflow = {count: over > 1 ? 1 : 0, samples: [`+${over}px at ${vw}px`]}
  const iso = /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/
  const isoHits = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = (n.nodeValue || '').trim(), el = n.parentElement
    if (!t || !el || el.closest('pre, code, textarea, input, script, style, [data-testid="cc-loaded-build"]') || !visible(el)) continue
    if (iso.test(t)) isoHits.push(t.slice(0, 60))
  }
  res.raw_iso = {count: isoHits.length, samples: isoHits.slice(0, 5)}
  const emptyLi = [...document.querySelectorAll('li')].filter(li => visible(li) && !li.innerText.trim() && !li.querySelector('img,svg,input,canvas,button'))
  const bulletLines = (document.body.innerText || '').split('\n').filter(l => /^\s*[•·▪◦‣]\s*$/.test(l)).length
  res.empty_bullet = {count: emptyLi.length + bulletLines, samples: emptyLi.slice(0, 5).map(desc)}
  return res
}
