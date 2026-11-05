/**
 * FQ-022 (audit 2026-11-04): on a narrow phone the CIO tab strip was a single scrollable row, so "Capital & Policy"
 * and "Evidence & Comms" sat past the right edge — reachable only by swiping a tab strip. The finding's expectation is
 * that every tab stays readable and reachable WITHOUT sideways scrolling.
 *
 * This measures the real layout at 390 px and 412 px: no tab may end past the viewport, and the strip may not scroll
 * horizontally. It fails on the pre-fix CSS (the two long tabs extended to 419 px and 567 px at 390 px).
 */
import { expect, test } from '@playwright/test'

for (const width of [390, 412]) {
  test(`the CIO tab strip fits the ${width}px viewport without sideways scrolling`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/v3/cio', { waitUntil: 'domcontentloaded' })
    const nav = page.getByRole('tablist', { name: 'Office sections' })
    await expect(nav).toBeVisible({ timeout: 20_000 })
    const measured = await nav.evaluate((el) => {
      const strip = el as HTMLElement
      const vw = document.documentElement.clientWidth
      const tabs = Array.from(strip.querySelectorAll('button')).map((b) => {
        const r = b.getBoundingClientRect()
        return { label: (b.textContent || '').trim(), right: Math.round(r.right) }
      })
      return { vw, scrollWidth: strip.scrollWidth, clientWidth: strip.clientWidth, tabs }
    })
    expect(measured.tabs.length).toBeGreaterThanOrEqual(5)
    const past = measured.tabs.filter((t) => t.right > measured.vw + 1)
    expect(past, `tabs past the right edge: ${JSON.stringify(past)}`).toEqual([])
    expect(measured.scrollWidth, 'the tab strip must not scroll sideways').toBeLessThanOrEqual(measured.clientWidth + 1)
  })
}
