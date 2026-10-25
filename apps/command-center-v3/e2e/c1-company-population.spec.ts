/** Actual saved-CIO fact component, immutable production COPY evidence only.
 * No app server, database, provider, cookie, websocket or mutation request.
 */
import { expect, test } from '@playwright/test'
import { build } from 'esbuild'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const data = JSON.parse(readFileSync(new URL('./fixtures/c1CompanyPopulation.fixture.json', import.meta.url), 'utf8'))
const origin = 'http://c1-copy-fixture.invalid'
let js = '', css = ''
test.beforeAll(async () => {
  const bundled = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';
    import{WatchCompanyFacts}from'./src/components/watch/WatchCompanyFacts';import'./src/index.css';
    const d=${JSON.stringify(data)};createRoot(document.getElementById('root')).render(<main className="cc-terminal-ui" style={{padding:20,minHeight:'100vh',background:'var(--bg-0)',color:'var(--text-0)'}}>
    <h1 style={{fontSize:20}}>Saved CIO company facts</h1><p>Production COPY · ${data.captured_at} · no live writes</p>
    {d.rows.map(r=><article key={r.symbol} data-testid="copy-company-row" style={{margin:'20px 0',padding:16,border:'1px solid #303640',borderRadius:6}}>
    <WatchCompanyFacts symbol={r.symbol} facts={r.company_facts} ticker={<b>{r.symbol}</b>}/></article>)}</main>);`,
    loader: 'tsx', resolveDir: process.cwd(), sourcefile: 'c1-copy-fixture.tsx' }, bundle: true, write: false,
    outfile: 'c1-copy-fixture.js', jsx: 'automatic', platform: 'browser', define: { 'process.env.NODE_ENV': '"production"' } })
  js = bundled.outputFiles.find(f => f.path.endsWith('.js'))!.text
  css = bundled.outputFiles.find(f => f.path.endsWith('.css'))!.text
})
for (const width of [1440, 412]) test(`real FATN ANET saved facts ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.clock.install({ time: new Date(data.captured_at) })
  const forbidden: string[] = []
  await page.routeWebSocket('**/*', ws => { forbidden.push(`WS:${ws.url()}`); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (req.method() !== 'GET' || u.origin !== origin) { forbidden.push(`${req.method()}:${req.url()}`); return route.abort() }
    if (u.pathname === '/fixture.js') return route.fulfill({ contentType: 'text/javascript', body: js })
    if (u.pathname === '/fixture.css') return route.fulfill({ contentType: 'text/css', body: css })
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>' })
    forbidden.push(`unlisted:${req.url()}`); return route.abort()
  })
  await page.goto(origin)
  const rows = page.getByTestId('copy-company-row'); await expect(rows).toHaveCount(2)
  for (let i = 0; i < data.rows.length; i++) {
    const r = data.rows[i], row = rows.nth(i)
    await expect(row).toContainText(r.symbol)
    for (const key of ['company', 'description', 'sector', 'industry']) await expect(row).toContainText(r.company_facts[key].value)
    await expect(row).toContainText('CIO record')
    expect(await row.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    const description = row.locator('.watch-company-description')
    expect(await description.evaluate(el => el.clientHeight <= 2 * parseFloat(getComputedStyle(el).lineHeight) + 1)).toBe(true)
    await expect(description).toHaveAttribute('title', new RegExp(r.company_facts.description.source))
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  expect(forbidden).toEqual([])
  if (process.env.C1_POPULATE_SHOTS_DIR) { mkdirSync(process.env.C1_POPULATE_SHOTS_DIR, { recursive: true }); await page.screenshot({ path: resolve(process.env.C1_POPULATE_SHOTS_DIR, `c1-production-copy-${width}.png`), fullPage: true }) }
})
