// LQ-20261107-1642 — the Home CIO risk meter colours each segment by its DRIVER STATE, and the tier cutoffs are
// on the same 0-100 scale. Renders the REAL CioCardV5 with a synthetic HomeCioCard@v1 payload at 390 / 412 / 1440 px.
//   node e2e/cio-meter-state.fixture.mjs <outdir>
// No live API and no private data: the payload is invented here. Proves the three things the ticket names:
//   (1) the FIRST segment is the WARN one and it is amber — under the old nth-child rule the first segment was red,
//       which is exactly how an operator came to read "RED badge" next to an amber bar;
//   (2) a STRESS segment is red wherever it sits in the list;
//   (3) the 25/40/60/75 ticks are where the policy's tier boundaries are, and the phone layouts do not scroll.
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

const P = { source_id: 'market_risk:2031-03-03T21:00:00+00:00', as_of: '2031-03-03T21:00:00+00:00' }
// WARN first, STRESS second: the old nth-child(odd)=red / nth-child(even)=amber rule drew the mirror image.
const CARD = {
  schema: 'HomeCioCard@v1',
  card: {
    tier: { value: 'ORANGE', ...P },
    score: { value: 44.2, ...P },
    score_sum: { value: 44.2, ...P },
    posture: { value: 'DEFENSIVE — HOLD CASH', ...P },
    drivers: [
      { name: 'Breadth', state: 'WARN', points: 12.0, detail: 'synthetic breadth reading', ...P },
      { name: 'Volatility', state: 'STRESS', points: 19.4, detail: 'synthetic volatility reading', ...P },
      { name: 'Cross-asset', state: 'IMPROVING', points: 4.1, detail: 'synthetic cross-asset reading', ...P },
      { name: 'Quiet one', state: 'CALM', points: 0, ...P },
      { name: 'Unmeasured', state: 'UNKNOWN', points: 8.7, detail: 'level-only, not scored', ...P },
    ],
  },
}

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import CioCardV5 from './src/components/home/CioCardV5';
      import './src/index.css';
      const CARD: any = ${JSON.stringify(CARD)};
      createRoot(document.getElementById('root')).render(
        <div className="ops-evidence-page" data-testid="frame" style={{padding:0,minHeight:'100vh'}}>
          <div style={{fontSize:11,opacity:.7,padding:'4px 8px'}}>SYNTHETIC — repo fixture only, no live data</div>
          <CioCardV5 card={CARD.card} adviceOk={false} adviceReason="synthetic fixture" nowMs={1893456000000} />
        </div>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'cio-meter-fixture.tsx',
  },
  bundle: true, write: false, outfile: 'f.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><main id="root"></main><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`

const browser = await chromium.launch()
const receipt = { fixture: 'cio-meter-state', card: 'ORANGE 44.2', renders: [] }
try {
  for (const width of [390, 412, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    await page.setContent(html, { waitUntil: 'load' })
    await page.waitForSelector('[data-testid="cio5-seg"]')

    const got = await page.evaluate(() => {
      const probe = (v) => { const d = document.createElement('div'); d.style.background = `var(${v})`; document.body.append(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c }
      const segs = [...document.querySelectorAll('[data-testid="cio5-seg"]')]
      const ticks = [...document.querySelectorAll('[data-testid="cio5-ticks"] .tk')]
      const meter = document.querySelector('.meter')
      const meterBox = meter.getBoundingClientRect()
      const tickBoxes = ticks.map(t => ({ tick: Number(t.dataset.tick), x: t.getBoundingClientRect().left + t.getBoundingClientRect().width / 2, label: t.textContent }))
      return {
        warn: probe('--warning-color'), danger: probe('--danger-color'), info: probe('--info-color'), neutral: probe('--neutral-color'),
        segs: segs.map(s => ({ state: s.dataset.state, bg: getComputedStyle(s).backgroundColor, w: s.getBoundingClientRect().width })),
        ticks: tickBoxes, meter: { left: meterBox.left, width: meterBox.width },
        scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth,
        past: [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5).length,
      }
    })

    // (1) + (2): colour follows the state, wherever the segment sits
    assert.equal(got.segs.length, 4, 'four scored drivers (CALM with 0 points is not drawn)')
    assert.deepEqual(got.segs.map(s => s.state), ['WARN', 'STRESS', 'IMPROVING', 'UNKNOWN'])
    assert.equal(got.segs[0].bg, got.warn, 'the FIRST segment is a WARN reading: amber, not the old red')
    assert.equal(got.segs[1].bg, got.danger, 'a STRESS reading is red')
    assert.equal(got.segs[2].bg, got.info, 'IMPROVING is the info colour')
    assert.equal(got.segs[3].bg, got.neutral, 'UNKNOWN is neutral: a reading that was not measured never looks like stress')
    assert.notEqual(got.segs[0].bg, got.danger, 'the old nth-child rule drew this segment red')
    // widths are still the points' share of 100: 12.0, 19.4, 4.1, 8.7 of the meter
    const share = got.segs.map(s => s.w / got.meter.width)
    for (const [i, pts] of [12.0, 19.4, 4.1, 8.7].entries()) assert.ok(Math.abs(share[i] - pts / 100) < 0.02, `segment ${i} width is its points' share`)

    // (3): the tick marks sit at 25/40/60/75% of the same scale, labelled with their own number
    assert.deepEqual(got.ticks.map(t => t.tick), [25, 40, 60, 75])
    assert.deepEqual(got.ticks.map(t => t.label), ['25', '40', '60', '75'])
    for (const t of got.ticks) {
      const at = (t.x - got.meter.left) / got.meter.width
      assert.ok(Math.abs(at - t.tick / 100) < 0.02, `tick ${t.tick} is drawn at ${(at * 100).toFixed(1)}%`)
    }
    // the ticks are ordered left-to-right and never overlap, at any width
    for (let i = 1; i < got.ticks.length; i++) assert.ok(got.ticks[i].x > got.ticks[i - 1].x)

    // phone layouts do not scroll sideways
    assert.equal(got.scrollW, got.clientW, `no horizontal scroll at ${width}px`)
    assert.equal(got.past, 0, `nothing past the viewport edge at ${width}px`)
    assert.deepEqual(errors, [], `no page errors at ${width}px`)

    const shot = path.join(out, `cio-meter-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    receipt.renders.push({ width, segments: got.segs.map(s => ({ state: s.state, background: s.bg })), ticks: got.ticks.map(t => t.label), screenshot: path.basename(shot) })
    await page.close()
  }
} finally {
  await browser.close()
}
fs.writeFileSync(path.join(out, 'cio-meter-state-receipt.json'), JSON.stringify(receipt, null, 2))
console.log(`cio-meter-state: ok — ${receipt.renders.length} renders at 390/412/1440 px; WARN amber, STRESS red, ticks 25/40/60/75`)
