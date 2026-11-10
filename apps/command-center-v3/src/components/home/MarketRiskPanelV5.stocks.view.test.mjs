// LQ-20261107-1655 — the individual names under each defensive ETF row, in the Market Risk panel.
//
// The operator asked for held names in the sector first, then the group's best constituents by RS vs SPY
// over 20 sessions, each with its own close/as-of, the tranche-1 share count and a stock-vs-ETF line.
//
// Red-first: at the parent revision MarketRiskPanelV5 renders no stock rows at all — `stocks` is not in the
// type and StockRows does not exist — so every case below fails on presence before the fix.
//
// Phone width: the CSS case reads the stylesheet directly. The stocks sub-list must stay one column and must
// not reintroduce a nowrap run or a px min-width under `.mr5 .rc .sk`; the measured 412 px proof is the
// Playwright spec `e2e/home-cio-rotate-stocks-20261109.spec.ts`.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = globalThis.window || {}
globalThis.window.matchMedia = globalThis.window.matchMedia || (q => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
globalThis.window.location = globalThis.window.location || { origin: 'http://localhost:4173', pathname: '/v3/home', search: '', hash: '' }
globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
globalThis.document = globalThis.document || { documentElement: { style: {} }, body: { style: {} },
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (spec.endsWith('.css')) return 'from "data:text/javascript,export default {}"'
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const T = '2031-03-07'
const fact = (value, source_id = 'synthetic', as_of = T) => ({ value, source_id, as_of })

const STOCKS = {
  symbol: 'DEMOH', held: true, close: fact(30.0, 'ticker_prices:daily:DEMOH'),
  held_value_usd: fact(3000.0, 'book_exposure:2031-03-07'), rs20: fact(-4.25, 'ticker_prices:rs20_vs_spy:DEMOH'),
  tranche1_usd: 1200.0, tranche1_shares: 40, proposed: true,
  compare: 'weaker than XLV by 18.0 pts',
  source_id: 'ticker_prices:daily:DEMOH', as_of: T,
}
// LQ-20261107-1784: a HELD name that fails a floor is still listed, with a plain flag instead of a rank.
const FLAGGED = {
  symbol: 'DEMOSUB', held: true, close: fact(2.0, 'ticker_prices:daily:DEMOSUB'),
  flag: 'below $5.00 — review',
  source_id: 'ticker_prices:daily:DEMOSUB', as_of: T,
}
const RANKED = {
  symbol: 'DEMOB', held: false, close: fact(12.5, 'ticker_prices:daily:DEMOB'),
  rs20: fact(21.0, 'ticker_prices:rs20_vs_spy:DEMOB'),
  tranche1_usd: 1200.0, tranche1_shares: 96, proposed: true,
  compare: 'stronger than XLV by 7.2 pts',
  source_id: 'ticker_prices:daily:DEMOB', as_of: T,
}
const UNTRACEABLE = {
  symbol: 'NOCLOSE', held: false, close: { value: 9.0, source_id: '', as_of: T }, // a value with no source is not a value
  source_id: 'ticker_prices:daily:NOCLOSE', as_of: T,
}

const PANEL = {
  header: { tier: fact('YELLOW') },
  protect: [], stopped_out: [], positions: { rows: [] },
  rotate: {
    source_id: 'market_risk:sectors:2031-03-07', as_of: T,
    // LQ-20261107-1784: the CIO's buys line rides out for the TODAY line. An OPEN gate proposes nothing withheld.
    buys: { gate: fact('OPEN'), line: fact('Buys open, slowly') },
    candidates: [
      { key: 'healthcare', symbol: 'XLV', label: 'Healthcare', state: 'RESILIENT', rs20: 13.8, qualifies: true,
        close: fact(184.4, 'market_ohlcv_bars:daily:XLV:2031-03-07'), price: fact(184.4, 'quote:synthetic', T),
        source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        proposed: { target_pct: 4.0, target_usd: 4000.0, tranche1_usd: 1200.0, shares: 6, proposed: true },
        stocks: [STOCKS, FLAGGED, RANKED, UNTRACEABLE], stocks_min_price: 5, stocks_note: '3 dropped: 2 under $5.00, 1 under $10.0M/day' },
      // a filled tranche under a released gate: HOLD, and the next step is tranche 2 at the current price
      { key: 'staples', symbol: 'XLP', label: 'Staples', state: 'RESILIENT', rs20: 13.5, qualifies: true,
        close: fact(99.0, 'market_ohlcv_bars:daily:XLP:2031-03-07'), price: fact(99.0, 'quote:synthetic', T),
        source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        proposed: { target_pct: 3.0, target_usd: 3000.0, tranche1_usd: 900.0, shares: 9, proposed: true },
        held: { shares: 9, avg_cost: 98.5, filled: true, source_id: 'positions_current:sync_run_1', as_of: T },
        next_tranche: { tranche: 2, usd: 900.0, shares: 9, after: null },
        stocks_gap: 'no constituent with a measured close' },
      { key: 'utilities', symbol: 'XLU', label: 'Utilities', state: 'NEUTRAL', rs20: 9.7, qualifies: false,
        source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        proposed: { target_pct: 2.0, target_usd: 25000.0, proposed: true },
        stocks: [{ symbol: 'DEMOU', held: false, close: fact(41.0, 'ticker_prices:daily:DEMOU'),
          rs20: fact(6.0, 'ticker_prices:rs20_vs_spy:DEMOU'), source_id: 'ticker_prices:daily:DEMOU', as_of: T }] },
    ],
    plan: { proposed: true, tranche1_usd: 2100.0, split: [0.3, 0.3, 0.4] },
  },
}

const { default: Panel } = await import(compile(join(app, 'src/components/home/MarketRiskPanelV5.tsx')))

const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/home'] },
  React.createElement(Panel, { panel: PANEL, notes: [], mr: null })))

const block = (sym) => {
  // the ETF row for `sym`, up to the next ETF row: where its action line and stock rows must live
  const rows = html.split('data-testid="mr5-rotate-row"')
  return rows.find(r => r.includes(`<span class="nm">${sym}</span>`)) ?? ''
}
const text = (s) => s.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('the names are rendered under their own ETF row, not in one list at the bottom', () => {
  const xlv = block('XLV'), xlp = block('XLP'), xlu = block('XLU')
  assert.ok(xlv.includes('data-testid="mr5-rotate-stocks"'), 'XLV has no stock block')
  assert.ok(xlu.includes('data-testid="mr5-rotate-stocks"'), 'XLU has no stock block')
  assert.ok(!xlp.includes('data-testid="mr5-rotate-stocks"'), 'XLP has stocks it should not have')
  assert.equal((html.match(/data-testid="mr5-stock-row"/g) || []).length, 4, 'three healthcare names + one utility')
})

check('held first, and only the held names are tagged', () => {
  const rows = block('XLV').split('data-testid="mr5-stock-row"').slice(1)
  assert.match(rows[0], /<b>DEMOH<\/b>/, 'the held name does not lead the sector')
  assert.match(rows[0], /held/, 'a held name is not flagged held')
  assert.match(rows[1], /<b>DEMOSUB<\/b>/)
  assert.ok(!rows[2].includes(' held '), 'a non-held name is tagged held')
  assert.match(rows[2], /<b>DEMOB<\/b>/)
})

check('each name is ONE line: symbol, held flag, price, and the relational phrase', () => {
  const held = text(block('XLV').split('data-testid="mr5-stock-row"')[1])
  assert.match(held, /DEMOH held \$30\.00 · weaker than XLV by 18\.0 pts/)
  // the duplicated RS pair, the RS-vs-SPY sentence and the two-close comparison are gone
  for (const gone of [/Close 30\.00/, /vs SPY/, /184\.40/, /RS -/, /pts vs XLV/]) {
    assert.ok(!gone.test(held), `the old duplicated reading is back: ${gone}`)
  }
})

check('a held name that fails a floor shows its plain flag instead of a rank', () => {
  assert.match(text(html), /DEMOSUB held \$2\.00 · below \$5\.00 — review/)
})

check('the stocks caption and the drop count are the operator\'s numbers, not a copy', () => {
  assert.match(text(block('XLV')), /Stocks \(liquid, ≥\$5\)/)
  assert.match(text(block('XLV')), /3 dropped: 2 under \$5\.00, 1 under \$10\.0M\/day/)
})

check('one action line per group, drawn from the facts the server already carries', () => {
  assert.equal((html.match(/data-testid="mr5-action"/g) || []).length, 3, 'a group has no action line, or has two')
  assert.match(text(block('XLV')), /▶ PROPOSED\s*\.\s*Tranche 1 \$1,200 ≈ 6 sh at \$184\.40\. Needs your OK\./)
  assert.match(text(block('XLU')), /NO ACTION\s*\.\s*Starts at RESILIENT → 2% ≈ \$25K\. No live price\./)
})

check('a filled tranche states the next step at the current price', () => {
  const xlp = text(block('XLP'))
  assert.match(xlp, /HOLD\s*\.\s*Tranche 1 filled: 9 sh @ \$98\.50 \(now \$99\.00\)\./)
  assert.match(xlp, /Next: tranche 2 ≈ \$900 \(~9 sh\)\./)
})

check('the header cannot run the label, ticker and state together', () => {
  assert.match(text(block('XLV')), /HEALTHCARE · XLV · RESILIENT/)
  assert.ok(!/HealthcareXLV/.test(text(html)), 'the label still runs into the ticker')
  assert.ok(!/RESILIENTPROPOSED|RESILIENThold/.test(text(html)), 'the state still runs into the next cell')
})

check('TODAY states the CIO buys line and nothing of its own', () => {
  const today = (html.match(/data-testid="mr5-today"[^>]*>([\s\S]*?)<\/div>/) || [])[1]
  assert.ok(today, 'no TODAY line')
  assert.match(text(today), /TODAY:\s*Buys open, slowly\./)
})

check('the copy is descriptive, never an instruction', () => {
  const t = text(html)
  for (const word of [/^Buy /, /^Sell /, /Place (an )?order/i, /shares? to (buy|sell)/i]) {
    assert.ok(!word.test(t), `the copy instructs: ${word}`)
  }
})

check('an untraceable value is absent, never printed as zero', () => {
  assert.ok(!html.includes('NOCLOSE'), 'a row with no traceable close was rendered')
  assert.ok(!/\$9\.00/.test(html), 'a value without a source was drawn as a close')
})

check('an empty group says why instead of showing nothing', () => {
  assert.match(text(block('XLP')), /no constituent with a measured close/)
})

check('the sub-list and the action line are one column and cannot push a phone sideways', () => {
  const css = readFileSync(join(app, 'src/styles/cioCard.css'), 'utf8')
  const rules = css.split('\n').filter(l => l.includes('.mr5 .rc .sk') || l.includes('.mr5 .rc .sgap'))
  assert.ok(rules.length >= 4, 'the stocks sub-list has no stylesheet rules')
  for (const line of rules) {
    assert.ok(!/min-width:\s*\d/.test(line), `a px min-width is back in the sub-list: ${line.trim()}`)
    assert.ok(!/white-space:\s*nowrap/.test(line) || line.includes('.amt'), `a nowrap run is back: ${line.trim()}`)
    if (line.includes('grid-template-columns')) {
      assert.ok(!/minmax\(\s*0\s*,\s*[^)]*\)\s+minmax/.test(line), `a multi-column track is back: ${line.trim()}`)
    }
  }
  assert.match(css, /\.mr5 \.rc \.sk \.sl \{[^}]*overflow-wrap: anywhere/, 'the stock line does not wrap')
  assert.match(css, /\.mr5 \.rc \.act \{[^}]*overflow-wrap: anywhere/, 'the action line does not wrap')
  assert.match(css, /\.mr5 \.today \{[^}]*overflow-wrap: anywhere/, 'the TODAY line does not wrap')
})

// ── LQ-20261107-1389: under a no-buys verdict the column proposes nothing and says what it is waiting for ───────
//
// The projection withholds the tranche (tranche1_usd/shares null, tranches [], no plan) and carries the gate facts.
// Red-first: at the parent revision `gated` is not in the type and not read, so the amount cell printed "watch" and
// no pill was rendered at all. The server half is tests/test_home_cio_cio_verdict_lq1389_20261109.py; this is the
// same two fields as the operator actually sees them.
const GATED = (c) => {
  const x = { ...c }
  if (x.proposed) x.proposed = { ...x.proposed, tranche1_usd: null, shares: null, tranches: [] }
  if (x.stocks) {
    x.stocks = x.stocks.map(s => {
      const y = { ...s }
      delete y.tranche1_usd; delete y.tranche1_shares; delete y.proposed  // the server omits them, it does not zero them
      return y
    })
  }
  return x
}
const GATED_PANEL = {
  ...PANEL,
  rotate: {
    ...PANEL.rotate,
    plan: null,
    buys: { gate: fact('NONE'), line: fact('No new buys before CPI Tue 03-11 08:30 ET; protect gains with stops') },
    gated: { gate: fact('NONE'), until: fact('CPI Tue 03-11 08:30 ET'), until_short: fact('CPI Tue'),
             line: fact('No new buys before CPI Tue 03-11 08:30 ET; protect gains with stops') },
    candidates: PANEL.rotate.candidates.map(GATED),
  },
}
const gatedHtml = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/home'] },
  React.createElement(Panel, { panel: GATED_PANEL, notes: [], mr: null })))
const gatedText = (s) => text(s)

check('a no-buys verdict is a WAIT line naming the release, not a live proposal', () => {
  const xlv = gatedHtml.split('data-testid="mr5-rotate-row"').find(r => r.includes('<span class="nm">XLV</span>')) ?? ''
  assert.match(gatedText(xlv), /WAIT\s*\.\s*Tranche 1 waits on CPI Tue 03-11 08:30 ET \(buys now NONE\)\./)
  // the CIO's own line travels with it, so the operator can trace the verdict
  assert.match(gatedText(gatedHtml), /TODAY: No new buys before CPI Tue 03-11 08:30 ET; protect gains with stops\./)
})

check('a gated, unheld row never shows the tranche-1 dollars the verdict forbids', () => {
  const xlv = gatedHtml.split('data-testid="mr5-rotate-row"').find(r => r.includes('<span class="nm">XLV</span>')) ?? ''
  assert.ok(!/\$1,200/.test(gatedText(xlv)), 'a gated row still sizes tranche 1')
  assert.ok(!/tranche 1 \$/.test(gatedText(gatedHtml)), 'a gated column still states tranche-1 dollars')
  assert.ok(!/\$2,100/.test(gatedText(gatedHtml)), 'the removed plan table is back')
  assert.ok(!/watch/.test(gatedText(xlv)), 'a waiting tranche still reads "watch"')
})

check('the names under a gated ETF keep their readings and lose their share count', () => {
  const xlv = gatedHtml.split('data-testid="mr5-rotate-row"').find(r => r.includes('<span class="nm">XLV</span>')) ?? ''
  assert.ok(xlv.includes('data-testid="mr5-rotate-stocks"'), 'the stock block disappeared with the tranche')
  assert.match(gatedText(xlv), /DEMOH held \$30\.00 · weaker than XLV by 18\.0 pts/)
  assert.ok(!/≈\d+ sh/.test(gatedText(xlv)), 'a gated stock row still sizes a tranche')
  assert.equal((gatedHtml.match(/data-testid="mr5-stock-row"/g) || []).length, 4, 'a name row was dropped, not just ungated')
})


const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
