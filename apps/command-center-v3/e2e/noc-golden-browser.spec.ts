import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const enabled = process.env.NOC_GOLDEN_BROWSER === '1'
const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '../../..')
const out = path.join(root, 'docs/_evidence/autonomous_advisory_loop/noc_golden_browser')

async function api(page: import('@playwright/test').Page, route: string, name: string) {
  const response = await page.request.get(route)
  expect(response.status(), `${route} status`).toBe(200)
  const body = await response.json()
  expect(body?._serving?.schema, `${route} serving freshness`).toBe('ServingFreshness@v1')
  fs.writeFileSync(path.join(out, name), JSON.stringify(body, null, 2))
  return body
}

test.describe('NOC golden browser acceptance', () => {
  test.skip(!enabled, 'set NOC_GOLDEN_BROWSER=1 for isolated source-server acceptance')

  test.beforeAll(() => fs.mkdirSync(out, { recursive: true }))

  test('HTTP payloads preserve exact thesis and serving truth', async ({ page }) => {
    const advisory = await api(page, '/api/v3/advisory', 'advisory.json')
    const universe = await api(page, '/api/v3/cio/universe-theses', 'cio_universe_theses.json')
    const noc = await api(page, '/api/v3/cio/symbol-thesis/NOC', 'cio_symbol_noc.json')
    const thin = await api(page, '/api/v3/cio/symbol-thesis/BND', 'cio_symbol_bnd_thin.json')
    await api(page, '/api/v3/cio/home', 'cio_home.json')

    const row = advisory.rows.find((item: any) => item.symbol === 'NOC')
    expect(row?.symbol_thesis?.thesis_version).toBe('symbol_noc@v2')
    expect(row?.symbol_thesis?.summary?.length).toBeGreaterThan(400)
    expect(row?.decision_context?.decision_id).toBe('dec_noc_golden_v2')
    expect(row?.decision_context?.research_delta_classification).toBe('STRENGTHENS')
    expect(noc.symbol_thesis_version).toBe('symbol_noc@v2')
    expect(noc.core_thesis.length).toBeGreaterThan(400)
    expect(noc.cio_action.decision_id).toBe('dec_noc_golden_v2')
    expect(thin.thesis_state).toBe('THIN')
    expect(thin.core_thesis).not.toBe('No living thesis')

    const held = universe.metrics?.percentage_definitions?.held_substantive
    expect(held?.denominator).toBe(2)
    expect(held?.numerator).toBe(1)
    expect(universe.symbols.some((item: any) => item.symbol === 'NOC')).toBeTruthy()
    expect(universe.symbols.some((item: any) => item.symbol === 'BND')).toBeTruthy()

    for (const payload of [advisory, universe, noc, thin]) {
      expect(payload._serving.loaded_pin).toBeTruthy()
      expect(payload._serving.current_pin_sha).toBeTruthy()
      expect(payload._serving.pin_match).toBeFalsy()
    }
  })

  test('operator surfaces render NOC, THIN, research ops and receipts', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/v3/advisory')
    await expect(page.getByText('NOC').first()).toBeVisible({ timeout: 20_000 })
    await page.screenshot({ path: path.join(out, 'advisory.png'), fullPage: true })

    await page.goto('/v3/cio?tab=universe-theses')
    const panel = page.getByTestId('cio-universe-theses')
    await expect(panel).toBeVisible({ timeout: 20_000 })
    await expect(panel.getByText('NOC', { exact: true })).toBeVisible()
    await expect(panel.getByText('BND', { exact: true })).toBeVisible()
    await page.screenshot({ path: path.join(out, 'universe-and-theses.png'), fullPage: true })

    await panel.getByText('NOC', { exact: true }).click()
    const card = page.getByTestId('symbol-thesis-card')
    await expect(card).toContainText('symbol_noc@v2')
    await expect(card).not.toContainText('No living thesis')
    await card.screenshot({ path: path.join(out, 'noc-symbol-card.png') })

    await panel.getByText('BND', { exact: true }).click()
    await expect(card).toContainText('THIN')
    await expect(card).not.toContainText('No living thesis')
    await card.screenshot({ path: path.join(out, 'bnd-thin-symbol-card.png') })

    await page.getByRole('tab', { name: 'TELEGRAM RECEIPTS' }).click()
    await expect(page.getByRole('tabpanel', { name: 'TELEGRAM RECEIPTS' })).toBeVisible()
    await page.screenshot({ path: path.join(out, 'telegram-receipts.png'), fullPage: true })
  })
})
