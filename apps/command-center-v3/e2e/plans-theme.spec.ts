import { test, expect, type Locator, type Page } from '@playwright/test'

/**
 * Plans page theme + desktop detail panel (2026-11-03).
 *
 * Source-string tests cannot see an inline style, which is how the page chrome stayed a dark
 * terminal block on the white light-theme page (h1 1.05:1, purpose 2.56:1, active nav 1.68:1).
 * This spec renders the real bundle in Chromium, mocks the plans API on the local preview, and
 * measures COMPUTED colours — the element's own colour composited over its first opaque ancestor
 * background — for both themes. It also proves the desktop panel takes focus, closes on Escape,
 * returns focus to its card, and has a 44 px Back control. The phone sheet must keep working.
 *
 * Nothing here talks to :7777: every /api request is intercepted below.
 */

const NOW = Date.now()
const iso = (minAgo: number) => new Date(NOW - minAgo * 60_000).toISOString()

// One self-declared registration and one approved plan with steps. Registration is not approval;
// both shapes must render.
const selfDeclared = {
  id: 'PLAN-20261103-selfdecl',
  title: 'Registered plan with no approval recorded',
  status: 'registered',
  vendor: 'codex',
  updated_at: iso(8),
  steps_done: 0,
  steps_left: 2,
  author_proof: 'self-declared',
}
const approved = {
  id: 'PLAN-20261103-approved',
  title: 'Approved plan with steps',
  status: 'approved',
  vendor: 'claude',
  approved_at: iso(30),
  updated_at: iso(5),
  claim: 'CLAIM-20261103-ui',
  branch: 'wt/plan-registry-ui-20261102',
  pr: 2490,
  steps_done: 1,
  steps_left: 2,
  steps: [
    { done: true, text: 'Replace the hardcoded page chrome' },
    { done: false, text: 'Prove it in Chromium' },
  ],
  author_proof: 'claim:CLAIM-20261103-ui',
  operator_quote: 'Make the light theme readable.',
}

const listView = {
  ok: true,
  data: {
    schema: 'PlanRegistryView@v1',
    as_of: iso(2),
    store: { state: 'ok', reason: null },
    plans: [selfDeclared, approved],
  },
}
const detailView = {
  ok: true,
  data: {
    schema: 'PlanRegistryView@v1',
    as_of: iso(2),
    store: { state: 'ok', reason: null },
    plan: { ...approved, body: 'Line one of the plan body.\nLine two of the plan body.' },
  },
}

/**
 * Intercept everything. Plans returns the served PlanRegistryView@v1 shape; the overview and
 * health endpoints fail on purpose so the "showing last-good data" bar renders and its contrast
 * can be measured. Every other API is a benign empty envelope.
 */
async function mockApi(page: Page) {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error(`live API traffic is forbidden: ${url.href}`)
    if (url.pathname === '/api/v2/plans') {
      const id = url.searchParams.get('id')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(id ? detailView : listView) })
    }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/v2/overview' || url.pathname === '/api/health') {
      return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture outage' }) })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: {} }) })
  })
}

/** Set the theme the way main.tsx/useTheme does: localStorage choice + <html data-theme>. */
async function openPlans(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript((value: string) => {
    try { window.localStorage.setItem('cc.ui.theme', value) } catch { /* private mode */ }
    // At document-start documentElement can be null; the app's initTheme() sets it on mount.
    if (document.documentElement) document.documentElement.dataset.theme = value
  }, theme)
  await mockApi(page)
  await page.goto('/v3/plans')
  await expect(page.locator('.pl-card').first()).toBeVisible()
}

type ContrastSample = { ratio: number; color: string; background: string }

/** WCAG 2.1 contrast of the element's text over what is actually painted behind it. */
async function contrastFor(locator: Locator): Promise<ContrastSample> {
  return locator.evaluate(el => {
    type RGBA = { r: number; g: number; b: number; a: number }
    const parse = (value: string): RGBA => {
      const match = value.match(/^rgba?\(([^)]+)\)$/)
      if (!match) throw new Error(`cannot parse colour ${value}`)
      const parts = match[1].split(',').map(part => Number.parseFloat(part.trim()))
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 }
    }
    const over = (top: RGBA, bottom: RGBA): RGBA => ({
      r: top.r * top.a + bottom.r * (1 - top.a),
      g: top.g * top.a + bottom.g * (1 - top.a),
      b: top.b * top.a + bottom.b * (1 - top.a),
      a: 1,
    })
    const linear = (channel: number) => {
      const c = channel / 255
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    }
    const luminance = (c: RGBA) => 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b)
    const ratio = (a: RGBA, b: RGBA) => {
      const la = luminance(a)
      const lb = luminance(b)
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
    }
    // Rendered background: the element's own background layers composited over its first opaque
    // ancestor. This is what catches a translucent bar painted over the page.
    const layers: RGBA[] = []
    let node: Element | null = el
    let base: RGBA = { r: 255, g: 255, b: 255, a: 1 }
    while (node) {
      const bg = parse(window.getComputedStyle(node).backgroundColor)
      if (bg.a > 0) layers.push(bg)
      if (bg.a === 1) break
      node = node.parentElement
    }
    if (layers.length > 0 && layers[layers.length - 1].a === 1) base = layers.pop() as RGBA
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base)
    const raw = parse(window.getComputedStyle(el).color)
    const fg = raw.a < 1 ? over(raw, base) : raw
    return {
      ratio: Math.round(ratio(fg, base) * 100) / 100,
      color: `rgb(${Math.round(fg.r)}, ${Math.round(fg.g)}, ${Math.round(fg.b)})`,
      background: `rgb(${Math.round(base.r)}, ${Math.round(base.g)}, ${Math.round(base.b)})`,
    }
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`plans page chrome follows the ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openPlans(page, theme)
    await expect(page.getByTestId('cc-reconnect-bar')).toBeVisible({ timeout: 20_000 })

    const checks: { name: string; locator: Locator; min: number }[] = [
      { name: 'h1', locator: page.locator('main h1'), min: 3 },            // large text
      { name: 'purpose', locator: page.locator('main header p'), min: 4.5 },
      { name: 'active nav', locator: page.locator('.nav-item.is-active'), min: 4.5 },
      { name: 'last-good bar', locator: page.getByTestId('cc-reconnect-bar'), min: 4.5 },
      { name: 'card title', locator: page.locator('.pl-card-title').first(), min: 4.5 },
      { name: 'card meta', locator: page.locator('.pl-card-line').first(), min: 4.5 },
      { name: 'card links', locator: page.locator('.pl-card-links').first(), min: 4.5 },
    ]
    const measured: string[] = []
    for (const check of checks) {
      const sample = await contrastFor(check.locator)
      measured.push(`${check.name}: ${sample.ratio}:1 (${sample.color} on ${sample.background}, min ${check.min})`)
      expect(sample.ratio, `${theme} ${check.name} — ${sample.color} on ${sample.background}`).toBeGreaterThanOrEqual(check.min)
    }
    // Keep the numbers visible in the run output: measured, not asserted-only.
    console.log(`[plans-theme ${theme}]\n  ${measured.join('\n  ')}`)

    // The desktop detail sheet must be readable too.
    await page.locator('.pl-card').first().click()
    await expect(page.locator('.pl-panel')).toBeVisible()
    for (const check of [
      { name: 'detail sheet', locator: page.locator('.pl-panel') },
      { name: 'detail meta', locator: page.locator('.pl-meta') },
    ]) {
      const sample = await contrastFor(check.locator)
      console.log(`[plans-theme ${theme}] ${check.name}: ${sample.ratio}:1 (${sample.color} on ${sample.background}, min 4.5)`)
      expect(sample.ratio, `${theme} ${check.name} — ${sample.color} on ${sample.background}`).toBeGreaterThanOrEqual(4.5)
    }
  })
}

test('desktop detail panel takes focus, closes on Escape and restores focus', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openPlans(page, 'dark')
  const card = page.locator('.pl-card').first()
  await card.click()

  const panel = page.locator('.pl-panel')
  await expect(panel).toBeVisible()

  const focusIsInsidePanel = () => page.evaluate(() => {
    const el = document.querySelector('.pl-panel')
    const active = document.activeElement
    return Boolean(el && active && (el === active || el.contains(active)))
  })
  expect(await focusIsInsidePanel(), 'focus must enter the desktop dialog').toBe(true)

  const back = page.locator('.pl-back')
  const box = await back.boundingBox()
  expect(box, 'the Back control has a layout box').not.toBeNull()
  expect(box!.width, 'Back control width').toBeGreaterThanOrEqual(44)
  expect(box!.height, 'Back control height').toBeGreaterThanOrEqual(44)
  console.log(`[plans-theme desktop] back control ${box!.width.toFixed(1)} × ${box!.height.toFixed(1)} px`)

  await page.keyboard.press('Escape')
  await expect(page.locator('.pl-panel')).toHaveCount(0)
  await expect(card, 'focus returns to the card that opened the dialog').toBeFocused()
})

test('phone sheet opens with focus inside, Escape closes it, and nothing overflows', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openPlans(page, 'light')
  const card = page.locator('.pl-card').first()
  await card.click()

  const sheet = page.locator('.mobile-detail-sheet')
  await expect(sheet).toBeVisible()
  expect(await page.evaluate(() => {
    const el = document.querySelector('.mobile-detail-sheet')
    const active = document.activeElement
    return Boolean(el && active && (el === active || el.contains(active)))
  }), 'focus must enter the phone sheet').toBe(true)

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    inner: window.innerWidth,
  }))
  console.log(`[plans-theme phone] scrollWidth document=${overflow.document} body=${overflow.body} viewport=${overflow.inner}`)
  expect(overflow.document, 'no horizontal page scroll').toBeLessThanOrEqual(overflow.inner + 1)
  expect(overflow.body, 'no horizontal body scroll').toBeLessThanOrEqual(overflow.inner + 1)

  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
})
