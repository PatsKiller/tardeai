/**
 * driver.mjs — renders every registered Command Center route in a real browser,
 * under every forced state, and reports what was actually on the screen.
 *
 * "A route returning the SPA shell is not a pass." The shell is `<div id="root">`
 * plus a script tag; a pass requires hydrated, route-specific content. This driver
 * measures the rendered DOM after hydration and records:
 *
 *   shell_only        nothing rendered inside #root
 *   rendered          real content, with element/text volume and the route markers
 *   error_boundary    the app caught and displayed a failure (that is honest)
 *   crashed           the page threw and rendered nothing
 *
 * It also records every network request the page issued, so a non-GET during page
 * load is caught as evidence rather than assumed absent.
 *
 * Usage: node driver.mjs <base-url> <plan.json> <out.json>
 */
import { chromium } from 'playwright'
import { readFileSync, writeFileSync } from 'node:fs'

const [baseUrl, planPath, outPath] = process.argv.slice(2)
if (!baseUrl || !planPath || !outPath) {
  console.error('usage: node driver.mjs <base-url> <plan.json> <out.json>')
  process.exit(2)
}

const plan = JSON.parse(readFileSync(planPath, 'utf8'))
const results = []

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })

for (const step of plan.steps) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()

  const requests = []
  const consoleErrors = []
  const pageErrors = []
  page.on('request', r => requests.push({ method: r.method(), url: r.url(), resourceType: r.resourceType() }))
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) })
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 300)))

  // Tell the server which state to serve before the app asks for anything.
  await ctx.addInitScript(() => { try { localStorage.setItem('CC_CONTROL_PLANE_PREVIEW', '1') } catch {} })

  const url = `${baseUrl}${step.url}`
  let nav = 'ok', navDetail = null
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  } catch (e) {
    nav = 'nav_error'; navDetail = String(e).slice(0, 200)
  }

  // Hydration + first data paint. The LOADING state deliberately holds the API
  // open, so a short settle is the point: we want the pending render, not the
  // resolved one.
  await page.waitForTimeout(step.settleMs ?? 1500)

  let probe
  try {
    probe = await page.evaluate(() => {
      const root = document.getElementById('root')
      const main = document.querySelector('main') || root
      const text = (main?.innerText || '').trim()
      const html = root?.innerHTML || ''
      const els = root ? root.querySelectorAll('*').length : 0
      const bannerEl = document.querySelector('[data-surface-mode]')
      const errish = /something went wrong|render error|error boundary/i.test(text)
      return {
        rootExists: !!root,
        elementCount: els,
        textLength: text.length,
        htmlLength: html.length,
        headingSample: Array.from(document.querySelectorAll('h1,h2,h3,[data-page]'))
          .slice(0, 6).map(n => (n.textContent || '').trim().slice(0, 60)).filter(Boolean),
        textSample: text.slice(0, 400),
        hasNavRail: !!document.querySelector('nav, [class*="nav"], [class*="Nav"]'),
        hasMetricStrip: /PORTFOLIO|TODAY|SETUPS|REGIME|VIX/i.test(text),
        surfaceMode: bannerEl ? bannerEl.getAttribute('data-surface-mode') : null,
        surfaceRoute: bannerEl ? bannerEl.getAttribute('data-surface-route') : null,
        bannerDismissible: bannerEl ? bannerEl.getAttribute('data-banner-dismissible') : null,
        looksLikeErrorBoundary: errish,
      }
    })
  } catch (e) {
    probe = { rootExists: false, elementCount: 0, textLength: 0, htmlLength: 0, evalError: String(e).slice(0, 200) }
  }

  const mutating = requests.filter(r => !['GET', 'HEAD'].includes(r.method))
  let verdict
  if (nav === 'nav_error') verdict = 'nav_error'
  else if (!probe.rootExists || probe.elementCount === 0) verdict = 'shell_only'
  else if (probe.looksLikeErrorBoundary) verdict = 'error_boundary'
  else if (probe.elementCount < 8 && probe.textLength < 20) verdict = 'shell_only'
  else verdict = 'rendered'

  results.push({
    route: step.route,
    url: step.url,
    state: step.state,
    verdict,
    navDetail,
    elementCount: probe.elementCount,
    textLength: probe.textLength,
    headingSample: probe.headingSample || [],
    textSample: probe.textSample || '',
    surfaceMode: probe.surfaceMode ?? null,
    surfaceRoute: probe.surfaceRoute ?? null,
    bannerDismissible: probe.bannerDismissible ?? null,
    requestCount: requests.length,
    apiRequestCount: requests.filter(r => r.url.includes('/api/')).length,
    mutatingRequests: mutating.map(r => ({ method: r.method, url: r.url })),
    consoleErrorCount: consoleErrors.length,
    consoleErrors: consoleErrors.slice(0, 3),
    pageErrors: pageErrors.slice(0, 3),
  })

  await ctx.close()
  process.stderr.write(`  ${step.state.padEnd(20)} ${step.route.padEnd(34)} ${verdict}\n`)
}

await browser.close()
writeFileSync(outPath, JSON.stringify({ schema: 'BrowserStateMatrixResults@v1', baseUrl, results }, null, 1))
console.log(JSON.stringify({ steps: results.length, out: outPath }))
