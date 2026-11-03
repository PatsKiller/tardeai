// Home market-risk card v007 — phone acceptance fixture.
// Renders the REAL actionable card (ActionableBody/Head) with the repo's own v006 synthetic payload,
// at 390 and 412, and records what is visible before/after the v007 build.
//   node e2e/home-v007-card.fixture.mjs <outdir>
// No live API: everything is the committed synthetic fixture. No private data.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom';
      import {ActionableBody, ActionableHead, ACTIONABLE_CSS} from './src/components/home/MarketRiskActionable';
      import {GlossaryProvider} from './src/components/home/MarketRiskActions';
      import {actionableModel} from './src/lib/marketRisk';
      import './src/index.css';
      const terms = ${JSON.stringify(JSON.parse(fs.readFileSync(path.join(app, '../../config/market_risk_glossary.json'), 'utf8')).terms)};
      import {marketRiskV006} from './e2e/fixtures/marketRisk.fixture';
      const PAYLOAD = marketRiskV006('ORANGE', 'NOT_NOW');
      const model = actionableModel(PAYLOAD);
      createRoot(document.getElementById('root')).render(
        <MemoryRouter><GlossaryProvider terms={terms}>
          <div className="ops-evidence-page" data-testid="v007-frame" style={{padding:8,background:'var(--bg0)',color:'var(--text0)',minHeight:'100vh'}}>
            <style dangerouslySetInnerHTML={{__html: ACTIONABLE_CSS}} />
            <div style={{fontSize:11,opacity:.7}}>SYNTHETIC — repo fixture only, no live data</div>
            <div data-testid="card"><ActionableHead m={model} /><ActionableBody m={model} why={<span>synthetic reasons for the fixture</span>} /></div>
          </div>
        </GlossaryProvider></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'v007-fixture.tsx',
  },
  bundle: true, write: false, outfile: 'f.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{ name: 'stub-node-fs', setup(b) {
    b.onResolve({ filter: /^node:fs$/ }, () => ({ path: 'fs-stub', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export function readFileSync(){return \'{"terms":{}}\'}', loader: 'js' }))
  } }],
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><main id="root"></main><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  for (const width of [390, 412]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
    const page = await ctx.newPage()
    const t = { pageErrors: [], external: [] }
    page.on('pageerror', e => t.pageErrors.push(String(e.message || e)))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://v007.test') { t.external.push(route.request().url()); return route.abort() }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      return route.fulfill({ contentType: 'application/json', body: '{"ok":false}' })
    })
    await page.goto('http://v007.test/')
    try { await page.waitForSelector('[data-testid="card"]', { timeout: 5000 }) }
    catch (e) {
      const txt = await page.evaluate(() => document.body.innerText.slice(0, 300))
      const errs = t.pageErrors.join(' | ')
      throw new Error(`card not rendered at ${width}; pageErrors=${errs}; text=${txt}`)
    }
    await page.waitForTimeout(300)
    const m = await page.evaluate(() => {
      const text = document.body.innerText || ''
      const taps = [...document.querySelectorAll('button,a,[role="button"]')].map(el => {
        const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), text: (el.textContent || '').slice(0, 24) }
      })
      return {
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        sections: { protect: /Protect/i.test(text), hedge: /Hedge/i.test(text), rotate: /Rotate/i.test(text), sectors: /Sectors vs SPY/i.test(text), reentry: /Since you were stopped out/i.test(text) },
        details: document.querySelectorAll('details').length,
        tableRows: document.querySelectorAll('[data-mr-actionable] tbody tr').length,
        smallTaps: taps.filter(x => x.w < 44 || x.h < 44).length, taps: taps.length,
        smallDetail: taps.filter(x => x.w < 44 || x.h < 44).slice(0, 4),
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
      }
    })
    assert.deepEqual(t.pageErrors, [], `page errors at ${width}`)
    const shot = path.join(out, `card-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width, shot, measured: m, traffic: t })
    await ctx.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify({ fixture: 'home-v007-card', results }, null, 2))
for (const r of results) {
  const m = r.measured
  console.log(`  [${m.overflow ? 'FAIL' : 'CAPTURE'}] ${r.width}: sections=${Object.entries(m.sections).filter(([, v]) => v).map(([k]) => k).join(',')} details=${m.details} rows=${m.tableRows} taps<44px=${m.smallTaps}/${m.taps} overflow=${m.overflow}`)
}
