import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * FQ-058 / review #2622 P2622-R2 (browser regression).
 *
 * The phone wire row clamps the headline and the lede to two lines. A clamp only clips with
 * `overflow: hidden`: with `overflow: visible` (the head reviewed at 61657962) the third and further
 * lines paint outside the two-line box — over the badges line and the next row. Measured on that
 * head: a 165-character headline had a 30px box holding 75px of text.
 *
 * This runs in a real Chromium at 390px, renders the REAL compact ArticleCard markup (emitted by
 * e2e/fixtures/fq058-wire-row.mjs from the page module, not a hand copy), applies the real
 * W9Mobile.css, and asserts:
 *   1. the clamp is the two-line, clipped-overflow one (the reviewed defect);
 *   2. the clamped headline and lede end above the badges line;
 *   3. nothing of the headline or lede is the topmost painted thing on the badges line.
 */

const CSS = readFileSync(join(HERE, '../src/pages/W9Mobile.css'), 'utf8')
const ROW_HTML = execFileSync(process.execPath, [join(HERE, 'fixtures/fq058-wire-row.mjs')], {
  encoding: 'utf8',
  maxBuffer: 8 * 1024 * 1024,
})

test('the phone wire row clamps the headline and lede without painting over the badges', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.setContent(
    `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
     <style>body{margin:0;font-family:system-ui,sans-serif;background:#0b0e13;color:#e8eaf0}
     ${CSS}</style></head>
     <body><div class="w9-page">${ROW_HTML}</div></body></html>`,
  )
  await page.waitForTimeout(50)

  // 0. The paint proof. The badges band is screenshotted, then the headline and lede are hidden
  //    (layout kept) and the same band is screenshotted again. Identical pixels mean no glyph of
  //    either clamped text painted into the band; with `overflow: visible` the third and later lines
  //    paint exactly there, so this is the assertion the review's counterexample fails.
  const band = await page.locator('.ri-wire-meta').boundingBox()
  expect(band, 'the badges line was not rendered').not.toBeNull()
  const painted = await page.screenshot({ clip: band! })
  await page.evaluate(() => {
    document.querySelectorAll('.ri-wire-headline, .ri-wire-lede').forEach(e => {
      ;(e as HTMLElement).style.visibility = 'hidden'
    })
  })
  const empty = await page.screenshot({ clip: band! })
  expect(Buffer.compare(painted, empty), 'the clamped headline or lede paints over the badges line').toBe(0)

  const box = await page.evaluate(() => {
    const row = document.querySelector('.ri-wire-row') as HTMLElement
    const head = row.querySelector('.ri-wire-headline') as HTMLElement
    const lede = row.querySelector('.ri-wire-lede') as HTMLElement
    const meta = row.querySelector('.ri-wire-meta') as HTMLElement
    const hs = getComputedStyle(head)
    const ls = getComputedStyle(lede)
    const line = (el: HTMLElement, s: CSSStyleDeclaration) =>
      parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.2
    const mr = meta.getBoundingClientRect()
    const hr = head.getBoundingClientRect()
    const lr = lede.getBoundingClientRect()
    const mid = document.elementFromPoint(mr.left + Math.min(40, mr.width / 2), mr.top + mr.height / 2)
    return {
      headOverflowY: hs.overflowY,
      ledeOverflowY: ls.overflowY,
      clamp: (hs as any).webkitLineClamp ?? (hs as any).WebkitLineClamp,
      headLines: Math.round(hr.height / line(head, hs)),
      ledeLines: Math.round(lr.height / line(lede, ls)),
      headBottom: hr.bottom,
      ledeBottom: lr.bottom,
      metaTop: mr.top,
      hit: mid ? { cls: String((mid as HTMLElement).className), tag: mid.tagName } : null,
      headScroll: head.scrollHeight,
      headClient: head.clientHeight,
    }
  })

  // 1. the reviewed clamp: two lines, clipped overflow (this is exactly what P2622-R2 broke).
  expect(box.clamp, 'the phone row no longer clamps the headline to two lines').toBe('2')
  expect(box.headOverflowY, 'the headline must clip its overflow, or its extra lines paint over the row').toBe('hidden')
  expect(box.ledeOverflowY, 'the lede must clip its overflow').toBe('hidden')
  expect(box.headLines, 'the headline box is not two lines tall').toBeLessThanOrEqual(2)
  expect(box.ledeLines, 'the lede box is not two lines tall').toBeLessThanOrEqual(2)

  // 2. the clamped text finishes above the badges line, which the phone rule puts on row two.
  expect(box.headBottom).toBeLessThanOrEqual(box.metaTop + 1)
  expect(box.ledeBottom).toBeLessThanOrEqual(box.metaTop + 1)

  // 3. nothing of the headline or lede is the topmost thing on the badges line.
  expect(box.hit, 'nothing is hit-testable on the badges line').not.toBeNull()
  expect(box.hit!.cls).not.toContain('ri-wire-headline')
  expect(box.hit!.cls).not.toContain('ri-wire-lede')
})
