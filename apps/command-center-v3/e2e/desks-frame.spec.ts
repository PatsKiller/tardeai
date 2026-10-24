import { test, expect, type Locator } from '@playwright/test'
import { build } from 'esbuild'
import fs from 'node:fs'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fixture = await build({ entryPoints: [path.join(app, 'e2e/desks-frame.fixture.tsx')], bundle: true, write: false, metafile: true,
  outfile: 'desk.js', define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent' })
const js = fixture.outputFiles.find(file => file.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
const css = fixture.outputFiles.find(file => file.path.endsWith('.css'))?.text ?? ''
const sourceFiles = [...Object.keys(fixture.metafile!.inputs).map(file => path.resolve(app, file)).filter(file => file.startsWith(path.join(app, 'src') + path.sep)), path.join(app, 'e2e/desks-frame.fixture.tsx'), fileURLToPath(import.meta.url)]
const testedSource = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: app, encoding: 'utf8' }).trim(), sha256: Object.fromEntries(sourceFiles.map(file => [path.relative(app, file), crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')])) }
const writers = [
  { lane_id: 'posture', state: 'ACTIVE', last_success_at: '2026-10-24T23:25:00Z', evidence_as_of: '2026-10-24T23:59:00Z', reason: null },
  { lane_id: 'options', state: 'PAUSED', last_success_at: '2026-10-14T00:00:00Z', evidence_as_of: '2026-10-24T23:59:00Z', reason: null },
  { lane_id: 'cash', state: 'NONE', last_success_at: null, reason: 'No scheduled writer is registered for this source.' },
  { lane_id: 'regime', state: 'RETIRED', last_success_at: null, reason: 'No successful run is recorded in the available execution evidence.' },
]
test.use({ hasTouch: true })
for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`board 0 clocks, rail and URL navigation at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const activate = (target: Locator) => width <= 820 ? target.tap() : target.click()
    const inViewport = async (target: Locator) => { await target.scrollIntoViewIfNeeded(); const box = await target.boundingBox(); expect(box).not.toBeNull(); expect(box!.y).toBeGreaterThanOrEqual(0); expect(box!.y + box!.height).toBeLessThanOrEqual(height); return box! }
    await page.clock.install({ time: new Date('2026-10-25T00:00:00Z') })
    const errors: string[] = [], forbidden: string[] = [], reads: string[] = []
    let apiFails = false
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== 'http://desk-frame-fixture.test' || request.method() !== 'GET') {
        forbidden.push(request.method() + ' ' + url.origin + url.pathname); return route.abort()
      }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body:
        `<!doctype html><html data-theme="dark"><head><meta charset="UTF-8"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      if (url.pathname === '/api/v2/desk-sources') {
        reads.push(url.pathname)
        if (apiFails) return route.fulfill({ status: 503, json: { ok: false, error: 'fixture_unavailable' } })
        expect(url.searchParams.get('lanes')).toBe('cash,options,posture,regime')
        return route.fulfill({ json: { ok: true, data: { observed_at: '2026-10-25T00:00:00Z', writers } } })
      }
      forbidden.push(url.pathname); return route.abort()
    })
    await page.goto('http://desk-frame-fixture.test/strategy?account=fixture#review')
    await expect(page.getByRole('heading', { name: 'Restored desk' })).toBeVisible()
    await expect(page).toHaveURL(/account=fixture&tab=overview#review$/)
    const clocks = page.getByRole('region', { name: 'Source clocks' })
    for (const state of ['ACTIVE', 'PAUSED', 'RETIRED', 'NONE']) await expect(clocks.getByText(`Writer ${state}`, { exact: true })).toBeVisible()
    await expect(clocks.getByText('The source update time is incomplete or invalid.')).toBeVisible()
    await expect(clocks.getByText('The source update time is in the future.')).toBeVisible()
    await expect(clocks.getByText('Last successful run: 35m ago')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Decisions for you' })).toBeVisible()
    await expect(page.getByRole('note').filter({ hasText: 'Panel evidence missing' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const shot = (state: string) => {
      const filename = `impl-0-${state}-${width}.png`
      return process.env.DESK_SHOTS_DIR ? path.join(process.env.DESK_SHOTS_DIR, filename) : testInfo.outputPath(filename)
    }
    await page.screenshot({ path: shot('source-clocks'), fullPage: true })
    const historyTab = page.getByRole('button', { name: 'History', exact: true })
    const tabBox = await inViewport(historyTab); expect(tabBox.height).toBeGreaterThanOrEqual(44)
    await activate(historyTab)
    await expect(page).toHaveURL(/account=fixture&tab=history#review$/)
    await expect(page.getByRole('heading', { name: 'History evidence' })).toBeVisible()
    await page.goBack()
    await expect(page.getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.goForward()
    await expect(page.getByRole('button', { name: 'History', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.reload()
    await expect(page.getByRole('heading', { name: 'History evidence' })).toBeVisible()
    if (width <= 820) await activate(page.getByRole('button', { name: 'Open navigation', exact: true }))
    const rail = page.getByRole('navigation', { name: 'Sections' })
    const restored = ['Re-Entry', 'Defense', 'Rotation', 'Strategy', 'Advisory Desk', 'Intelligence', 'Research lineage', 'Hermes', 'Rec Intelligence', 'Reports', 'Agents']
    for (const name of restored) await expect(rail.getByRole('link', { name, exact: true })).toHaveCount(1)
    await expect(rail.getByText('back', { exact: true })).toHaveCount(11)
    if (width <= 820) { const link = rail.getByRole('link', { name: 'Reports', exact: true }); const box = await inViewport(link); expect(box.height).toBeGreaterThanOrEqual(44) }
    await page.screenshot({ path: shot('rail'), fullPage: true })
    if (width <= 820) await activate(page.getByRole('button', { name: 'Close navigation', exact: true }))
    const primary = page.getByRole('link', { name: 'Review the cash-alternatives gap', exact: true })
    const primaryBox = await inViewport(primary); expect(primaryBox.height).toBeGreaterThanOrEqual(44)
    await activate(primary)
    await expect(page).toHaveURL(/system\/ops-controls\?tab=jobs$/)
    await expect(page.getByRole('heading', { name: 'Decision destination' })).toBeVisible()
    await inViewport(page.getByRole('heading', { name: 'Decision destination' }))
    await page.goBack()
    await expect(page.getByRole('heading', { name: 'History evidence' })).toBeVisible()
    await inViewport(page.getByRole('heading', { name: 'History evidence' }))
    await page.goto('http://desk-frame-fixture.test/strategy?tab=legacy&account=fixture#review')
    await expect(page).toHaveURL(/tab=history&account=fixture#review$/)
    await page.goto('http://desk-frame-fixture.test/strategy?tab=History&account=fixture#review')
    await expect(page).toHaveURL(/tab=history&account=fixture#review$/)
    await page.clock.setFixedTime(new Date('2026-11-08T00:00:00Z'))
    await page.reload()
    await expect(rail.getByText('back', { exact: true })).toHaveCount(0)
    apiFails = true
    await page.reload()
    await expect(clocks.getByRole('note').filter({ hasText: 'Writer clocks unavailable' })).toBeVisible()
    await expect(clocks.getByText('Writer state unavailable', { exact: true })).toHaveCount(4)
    await page.screenshot({ path: shot('writer-unavailable'), fullPage: true })
    expect(errors).toEqual([]); expect(forbidden).toEqual([]); expect(reads.length).toBeGreaterThan(0)
    fs.writeFileSync(testInfo.outputPath('fixture-traffic.json'), JSON.stringify({ width, height, tapFlows: ['tab filter', 'navigation sheet open/back', 'primary decision link and browser back'], reads, forbidden, errors, testedSource }, null, 2))
  })
}
