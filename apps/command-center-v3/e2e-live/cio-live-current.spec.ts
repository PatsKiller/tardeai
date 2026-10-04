import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { stageValueText } from '../src/lib/cioDecisionLineage'

// LIVE CURRENT acceptance: no route interception anywhere in this file.
const RUN_DIR = process.env.LIVE_RUN_DIR || path.resolve(process.cwd(), 'test-results', 'live-current')
const EXPECTED_SHA = (process.env.EXPECTED_SHA || '').trim()
const SETTLE_MS = 45_000

const PAGES: Array<[string, string]> = [
  ['cio-overview', '/v3/cio?tab=overview'],
  ['cio-decisions', '/v3/cio?tab=decisions'],
  ['cio-research', '/v3/cio?tab=research'],
  ['cio-capital-policy', '/v3/cio?tab=capital-policy'],
  ['cio-operator-evidence', '/v3/cio?tab=evidence-comms&sub=operator-evidence'],
  ['cio-institutional-cognition', '/v3/cio?tab=evidence-comms&sub=institutional-cognition'],
  ['cio-learning-cockpit', '/v3/cio?tab=evidence-comms&sub=learning-cockpit'],
  ['cio-capability-coverage', '/v3/cio?tab=evidence-comms&sub=capability-coverage'],
  ['advisory', '/v3/advisory'],
  ['agents', '/v3/agents'],
  ['hermes', '/v3/hermes'],
  ['research-intelligence', '/v3/research-intelligence'],
]
const VIEWPORTS: Array<[string, number, number]> = [['desktop', 1400, 900], ['narrow', 390, 844]]

type PageResult = {
  name: string; url: string; viewport: string; ok: boolean; failures: string[]
  api: Array<{ url: string; status: number }>; consoleErrors: string[]; pageErrors: string[]
  settle_ms: number; screenshot: string
}
const results: PageResult[] = []

fs.mkdirSync(RUN_DIR, { recursive: true })

function record(): void {
  fs.writeFileSync(path.join(RUN_DIR, 'pages.json'), JSON.stringify(results, null, 2))
}

async function observe(page: Page) {
  return page.evaluate(() => {
    const text = document.body.innerText || ''
    const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || '')
    const loading = text.match(/Loading [^\n]{0,60}(…|\.\.\.)/)
    return {
      textLength: text.length,
      overflowPx: document.documentElement.scrollWidth - window.innerWidth,
      loading: loading ? loading[0] : null,
      doubleBase: links.filter(h => h.includes('/v3/v3')).slice(0, 3),
      rawJson: (text.match(/\{"[A-Za-z_]+":/) || [null])[0],
    }
  })
}

// Sequential (workers: 1, fullyParallel: false) but NOT serial: one page failing
// must not skip the rest, or the receipt hides every later finding.
test.describe('LIVE CURRENT CIO surfaces', () => {
  test.describe.configure({ mode: 'default' })
  test('served bundle is the expected CURRENT build', async ({ request }) => {
    const meta = await (await request.get('/v3/build-meta.json', { headers: { 'cache-control': 'no-cache' } })).json()
    fs.writeFileSync(path.join(RUN_DIR, 'build-meta.json'), JSON.stringify(meta, null, 2))
    expect(String(meta.git_sha || ''), 'build-meta git_sha').not.toBe('')
    if (EXPECTED_SHA) expect(meta.git_sha, 'served bundle SHA must equal CURRENT GIT_SHA').toBe(EXPECTED_SHA)
  })

  for (const [vpName, width, height] of VIEWPORTS) {
    for (const [name, url] of PAGES) {
      test(`${name} @ ${vpName}`, async ({ page }) => {
        await page.setViewportSize({ width, height })
        const r: PageResult = { name, url, viewport: vpName, ok: false, failures: [], api: [], consoleErrors: [], pageErrors: [], settle_ms: 0, screenshot: '' }
        page.on('console', m => { if (m.type() === 'error') r.consoleErrors.push(m.text().slice(0, 240)) })
        page.on('pageerror', e => r.pageErrors.push(String(e).slice(0, 240)))
        page.on('response', resp => {
          const u = resp.url()
          if (u.includes('/api/')) r.api.push({ url: u.replace(/^https?:\/\/[^/]+/, '').slice(0, 160), status: resp.status() })
        })
        const t0 = Date.now()
        try {
          await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 })
          await page.waitForLoadState('networkidle', { timeout: 60_000 }).catch(() => undefined)
          let obs = await observe(page)
          while (obs.loading && Date.now() - t0 < SETTLE_MS) {
            await page.waitForTimeout(1000)
            obs = await observe(page)
          }
          r.settle_ms = Date.now() - t0
          if (obs.textLength < 80) r.failures.push(`page nearly empty (${obs.textLength} chars)`)
          if (obs.loading) r.failures.push(`still loading after ${SETTLE_MS / 1000}s: ${obs.loading}`)
          if (obs.overflowPx > 1) r.failures.push(`horizontal overflow ${obs.overflowPx}px`)
          if (obs.doubleBase.length) r.failures.push(`/v3/v3 links: ${obs.doubleBase.join(', ')}`)
          if (page.url().includes('/v3/v3')) r.failures.push(`/v3/v3 url: ${page.url()}`)
          if (obs.rawJson) r.failures.push(`raw JSON in primary UI: ${obs.rawJson}`)
        } catch (e) {
          r.failures.push(`navigation: ${String(e).slice(0, 200)}`)
        }
        const bad = r.api.filter(a => a.status >= 500)
        if (bad.length) r.failures.push(`HTTP 5xx: ${bad.map(a => `${a.status} ${a.url}`).slice(0, 4).join('; ')}`)
        if (r.consoleErrors.length) r.failures.push(`console errors: ${r.consoleErrors.length}`)
        if (r.pageErrors.length) r.failures.push(`page errors: ${r.pageErrors.length}`)
        r.screenshot = path.join(RUN_DIR, `${vpName}-${name}.png`)
        await page.screenshot({ path: r.screenshot, fullPage: false }).catch(() => undefined)
        r.ok = r.failures.length === 0
        results.push(r)
        record()
        expect(r.failures, `${name} @ ${vpName}`).toEqual([])
      })
    }
  }

  test('lineage of a real current decision shows the API stage values', async ({ page, request }) => {
    const plan = await (await request.get('/api/v2/cio/capital-plan')).json()
    const data = plan.data || plan
    const did = String(((data.position_decisions || [])[0] || {}).decision_id || '')
    expect(did, 'a live capital-plan decision exists').not.toBe('')
    const api = await (await request.get(`/api/v3/cio/decision/${encodeURIComponent(did)}/lineage`)).json()
    expect(api.ok, 'lineage API ok').toBe(true)
    const stages: Record<string, { value?: unknown }> = api.lineage.stages
    await page.setViewportSize({ width: 1400, height: 900 })
    await page.goto(`/v3/cio?tab=evidence-comms&sub=decision-lineage&decision=${encodeURIComponent(did)}`)
    await expect(page.getByTestId('cio-decision-lineage')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Loading decision lineage')).toHaveCount(0, { timeout: 60_000 })
    const mismatches: string[] = []
    for (const [stage, rec] of Object.entries(stages)) {
      const expected = stageValueText(rec.value)
      const el = page.getByTestId(`cio-lineage-value-${stage}`)
      const shown = (await el.count()) ? (await el.innerText()).trim() : null
      if (shown !== expected) mismatches.push(`${stage}: api=${JSON.stringify(expected)} ui=${JSON.stringify(shown)}`)
    }
    fs.writeFileSync(path.join(RUN_DIR, 'lineage.json'), JSON.stringify({ decision_id: did, mismatches, stage_count: Object.keys(stages).length }, null, 2))
    await page.screenshot({ path: path.join(RUN_DIR, 'lineage.png'), fullPage: true })
    expect(mismatches).toEqual([])
  })
})
