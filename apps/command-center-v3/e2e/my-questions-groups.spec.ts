/** My questions grouping (Screen 5): phone tap proof at 412/390 plus desktop/phone screenshots of every grouping.
 * Every request is intercepted (no server). Bodies come from the builder-generated
 * e2e/fixtures/myQuestionsGroups.fixture.json (cio_ask_api + cio_ask_groups on a SYNTHETIC ledger).
 * Screenshots: MQ_SCREENSHOT_DIR=<dir> → impl-questions-<state>-<width>.png.
 */
import { expect, test, type Page } from '@playwright/test'
import { build } from 'esbuild'
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

const fx = JSON.parse(readFileSync(new URL('./fixtures/myQuestionsGroups.fixture.json', import.meta.url), 'utf8'))
const origin = 'http://my-questions.invalid'
const shots = process.env.MQ_SCREENSHOT_DIR
let js = '', css = ''
test.beforeAll(async () => {
  const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';
    import MyQuestions from'./src/pages/MyQuestions';import'./src/styles/tokens.css';import'./src/index.css';
    createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Routes><Route path="cio/questions" element={<MyQuestions/>}/><Route path="cio/questions/:threadId" element={<MyQuestions/>}/></Routes></BrowserRouter>);`,
    resolveDir: process.cwd(), loader: 'tsx', sourcefile: 'my-questions.tsx' },
    bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
  js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script'); css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
  if (shots) mkdirSync(shots, { recursive: true })
})
async function serve(page: Page, opts: { empty?: boolean } = {}) {
  const traffic = { forbidden: [] as string[], writes: [] as { path: string; body: unknown }[] }
  await page.routeWebSocket('**/*', ws => { traffic.forbidden.push('WS:' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (u.origin !== origin) { traffic.forbidden.push(req.url()); return route.abort() }
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname.startsWith('/v3/')) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:16px;box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
    if (req.method() === 'POST') {
      traffic.writes.push({ path: u.pathname, body: req.postDataJSON() })
      if (!u.pathname.endsWith('/regroup')) { traffic.forbidden.push('POST ' + u.pathname); return route.abort() }
      return json({ ok: true, data: { override: { kind: 'ask.group_override' } } })
    }
    if (u.pathname === '/api/v2/cio/asks') {
      if (opts.empty) return json(fx.empty)
      const gb = u.searchParams.get('group_by'), ch = u.searchParams.get('channel')
      if (!gb) return json({ ok: true, data: { threads: fx.grouped.none.data.threads, as_of: fx.clock } })
      const body = ch === 'telegram' && gb === 'security' ? fx.grouped.telegram : !ch && !u.searchParams.get('q') ? fx.grouped[gb] : null
      return body ? json(body) : json({ ok: true, data: { threads: fx.grouped.none.data.threads, as_of: fx.clock } })
    }
    const m = u.pathname.match(/^\/api\/v2\/cio\/asks\/(thr_[0-9a-f]{16})$/)
    if (m && fx.threads[m[1]]) return json(fx.threads[m[1]])
    traffic.forbidden.push('unlisted:' + u.pathname); return route.abort()
  })
  return traffic
}
const tapTarget = async (locator: ReturnType<Page['locator']>) => {
  await locator.scrollIntoViewIfNeeded()
  const r = await locator.boundingBox(); expect(r && r.width >= 44 && r.height >= 44, JSON.stringify(r)).toBe(true)
  await locator.tap()
}
const snap = async (page: Page, state: string, width: number) => { if (shots) await page.screenshot({ path: path.join(shots, `impl-questions-${state}-${width}.png`), fullPage: true, animations: 'disabled' }) }

test.describe('phone: My questions grouped', () => {
  test.use({ hasTouch: true, isMobile: true })
  for (const viewport of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
    test(`group-by taps, group → full-screen thread sheet → related → regroup → back ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const traffic = await serve(page)
      await page.goto(origin + '/v3/cio/questions')
      await expect(page.getByTestId('mq-group-security')).toHaveAttribute('aria-pressed', 'true')
      const sec = fx.grouped.security.data.grouped
      await expect(page.getByTestId('mq-group')).toHaveCount(sec.groups.length)
      const tsla = page.locator('[data-testid="mq-group"]', { hasText: 'TSLA' })
      await expect(tsla.getByTestId('mq-group-counts')).toHaveText('2 questions · 1 thread')
      await expect(tsla.getByTestId('mq-group-memory')).toContainText('Question memory: answer recorded')
      await expect(tsla.getByTestId('mq-group-memory')).toContainText('Current stance: unavailable (shadow record)')
      await expect(tsla.getByTestId('ask-research-lifecycle')).toContainText('Last checked: not measured')
      for (const gb of ['sector', 'theme', 'date', 'none', 'security']) {
        await tapTarget(page.getByTestId(`mq-group-${gb}`))
        await expect(page.getByTestId(`mq-group-${gb}`)).toHaveAttribute('aria-pressed', 'true')
        if (gb === 'none') await expect(page.getByTestId('my-questions-list').locator('li')).toHaveCount(fx.grouped.none.data.threads.length)
        else await expect(page.getByTestId('mq-group')).toHaveCount(fx.grouped[gb].data.grouped.groups.length)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      }
      await expect(page.getByText('Unclassified')).toHaveCount(0) // security view: no sector catch-all
      // open the follow-up question (its answer recalled the first ask)
      await tapTarget(page.getByTestId('gq-ask_aaaaaaaaaaaaaaa2'))
      const sheet = page.getByTestId('ask-thread-sheet')
      await expect(sheet).toBeVisible()
      expect(await sheet.boundingBox()).toEqual({ x: 0, y: 0, ...viewport })
      const related = sheet.locator('[data-ask-id="ask_aaaaaaaaaaaaaaa2"]').getByTestId('mq-related')
      await related.scrollIntoViewIfNeeded()
      await expect(related).toContainText('Related from CIO memory — 2 earlier questions recalled into this answer')
      await expect(related).toContainText('100 or 1,000 TSLA?')
      await expect(related).toContainText('recalled ask is not on the ask ledger')
      await expect(sheet.locator('[data-ask-id="ask_aaaaaaaaaaaaaaa1"]').getByTestId('mq-related')).toContainText('recalled no earlier question')
      await tapTarget(sheet.getByTestId('mq-regroup-ask_aaaaaaaaaaaaaaa2'))
      await tapTarget(sheet.getByTestId('mq-ungroup'))
      await expect(sheet.getByRole('status').filter({ hasText: 'Ungrouped — saved to the ask ledger.' })).toBeVisible()
      expect(traffic.writes).toEqual([{ path: '/api/v2/cio/asks/thr_aaaaaaaaaaaaaaaa/regroup', body: { ask_id: 'ask_aaaaaaaaaaaaaaa2', group_by: 'security', group_key: null } }])
      await tapTarget(page.getByTestId('ask-thread-back'))
      await expect(page.getByTestId('ask-thread-sheet')).toHaveCount(0)
      expect(traffic.forbidden).toEqual([])
    })

    test(`channel select and empty state ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const traffic = await serve(page)
      await page.goto(origin + '/v3/cio/questions')
      await page.getByTestId('mq-channel').selectOption('telegram')
      await expect(page.getByTestId('mq-group')).toHaveCount(fx.grouped.telegram.data.grouped.groups.length)
      await page.close()
      expect(traffic.forbidden).toEqual([])
    })
  }
})

test('empty ledger shows the empty state, never sample groups', async ({ page }) => {
  for (const width of [1440, 412]) {
    await page.setViewportSize({ width, height: 900 })
    const traffic = await serve(page, { empty: true })
    await page.goto(origin + '/v3/cio/questions')
    await expect(page.getByTestId('mq-empty')).toBeVisible()
    await expect(page.getByTestId('mq-group')).toHaveCount(0)
    await snap(page, 'empty', width)
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    expect(traffic.forbidden).toEqual([])
  }
})

test('screenshots: every grouping at 1440 and 412', async ({ page }) => {
  for (const width of [1440, 412]) {
    await page.setViewportSize({ width, height: 1000 })
    const traffic = await serve(page)
    for (const gb of ['security', 'sector', 'theme', 'date', 'none']) {
      await page.goto(origin + `/v3/cio/questions${gb === 'security' ? '' : `?group=${gb}`}`)
      await expect(page.getByTestId(`mq-group-${gb}`)).toHaveAttribute('aria-pressed', 'true')
      if (gb !== 'none') await expect(page.getByTestId('mq-group').first()).toBeVisible()
      await snap(page, `group-${gb}`, width)
    }
    if (width === 1440) {
      await page.goto(origin + '/v3/cio/questions/thr_aaaaaaaaaaaaaaaa')
      await expect(page.getByTestId('mq-related').first()).toBeVisible()
      await snap(page, 'thread-related', width)
    }
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    expect(traffic.forbidden).toEqual([])
  }
})
