// Actual route/classic renders, isolated from API hooks and data-heavy child panels.
// node src/lib/journalTabs.view.test.mjs [--browser] [--result path.json]
// --browser adds Chromium geometry over production CSS; it never requests a live page.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const routeLabels = ['Journeys', 'Calendar', 'Replay', 'Holding history', 'Journal (classic tabs)']
const classicLabels = ['Trades', 'By Ticker', 'Costs', 'Tagging Queue', 'Analytics', 'Exit Intel', 'Behavioral', 'Session', 'Advanced', 'Lessons', 'Protection', 'Backtesting', 'Real Accounts', 'Options', 'Import']
const optionLabels = ['Lifecycle', 'Proposals', 'All coverage', 'Open Options', 'Strategy Overview', 'Options Trends']
const cache = new Map()
let terminal = false
let pageName = ''
const Empty = () => null
const Pass = ({ children }) => React.createElement(React.Fragment, null, children)
const componentStub = new Proxy({ __esModule: true, default: Empty }, { get: (object, key) => key in object ? object[key] : Pass })

// Compile the real TSX and its pure model/style helpers. Effects never run under SSR.
function compile(filename) {
  if (cache.has(filename)) return cache.get(filename)
  const source = fs.readFileSync(filename, 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS, esModuleInterop: true,
  } }).outputText
  const module = { exports: {} }
  cache.set(filename, module.exports)
  const localRequire = name => {
    if (name.endsWith('.css')) return {}
    if (name === 'react-router-dom') return { useSearchParams: () => [new URLSearchParams(pageName === 'OptionsHub' ? 'view=classic' : ''), () => {}] }
    if (name.includes('/components/') || name === 'recharts' || name === './TradeJourney') return componentStub
    if (name.endsWith('/hooks/useApi')) return { useApi: () => ({ data: null, error: null, loading: false, refetch() {} }) }
    if (name.endsWith('/hooks/useOAuthLanes')) return { useOAuthLanes: () => ({ grok: {}, chatgpt: {} }), laneReady: () => false }
    if (name.endsWith('/lib/terminalUi')) return { useTerminalUi: () => [terminal] }
    if (name.endsWith('/lib/uiV5')) return { useUiV5: () => [false] }
    if (name.endsWith('/lib/optionsNovice')) return { isNoviceMode: () => false, setNoviceMode() {} }
    if (name.endsWith('/lib/cloudLlmRun')) return { runJournalAsk() { throw new Error('paid call denied') } }
    if (!name.startsWith('.')) return require(name)
    let target = resolve(dirname(filename), name)
    if (!fs.existsSync(target)) target = ['.ts', '.tsx', '.js'].map(suffix => target + suffix).find(fs.existsSync)
    assert.ok(target, `missing fixture dependency ${name}`)
    return compile(target)
  }
  new Function('require', 'module', 'exports', js)(localRequire, module, module.exports)
  cache.set(filename, module.exports)
  return module.exports
}

const originalFetch = globalThis.fetch
const report = { source: app, as_of: new Date().toISOString(), ssr: [], geometry: [] }
const escaped = label => renderToStaticMarkup(React.createElement('span', null, label)).slice(6, -7)
const render = name => {
  pageName = name
  const View = compile(join(app, 'src/pages', `${name}.tsx`)).default
  return renderToStaticMarkup(React.createElement(View, { onDrill() {} }))
}
try {
  globalThis.fetch = () => { throw new Error('network denied in fixture') }
  for (const [name, labels] of [['TradeInViewPage', routeLabels], ['JournalHub', classicLabels], ['OptionsHub', optionLabels]]) {
    const html = render(name)
    for (const label of labels) assert.ok(html.includes(`>${escaped(label)}</button>`), `${name}: missing rendered label ${label}`)
    if (name === 'TradeInViewPage') assert.equal((html.match(/role="tab"/g) || []).length, routeLabels.length)
    report.ssr.push({ page: name, labels, passed: true })
  }
  if (process.argv.includes('--browser')) {
    const { chromium } = require('playwright')
    const css = fs.readFileSync(join(app, 'src/styles/tokens.css'), 'utf8') + '\n' +
      fs.readFileSync(join(app, 'src/index.css'), 'utf8').replace("@import './styles/tokens.css';", '') + '\n' +
      fs.readFileSync(join(app, 'src/components/tradeinview/TradeInViewLayout.css'), 'utf8') +
      (process.env.JOURNAL_TABS_MUTATE_OWNER ? '\n@media(max-width:420px){.tradeinview-tabs{flex-wrap:nowrap;overflow-x:auto}}' : '')
    const browser = await chromium.launch({ headless: true })
    try {
      for (const width of [390, 412, 1200]) for (const mode of [false, true]) {
        terminal = mode
        for (const [name, labels] of [['TradeInViewPage', routeLabels], ['JournalHub', classicLabels], ['OptionsHub', optionLabels]]) {
          const context = await browser.newContext({ viewport: { width, height: 844 }, serviceWorkers: 'block' })
          try {
            const page = await context.newPage()
            const requests = []
            await page.route('**/*', route => { requests.push(route.request().url()); return route.abort() })
            const html = render(name)
            await page.setContent(`<style>${css}</style><div class="app-shell ${mode ? 'cc-terminal-ui' : ''}" style="display:flex;flex-direction:column;height:100vh"><div class="app-body" style="display:flex;flex:1;min-height:0;overflow:hidden"><main class="app-main" style="flex:1;min-width:0;min-height:0;overflow-y:auto;padding:16px 24px">${html}</main></div></div>`)
            const selector = name === 'TradeInViewPage' ? '.tradeinview-tabs' : '.hub-tabs'
            const measured = await page.locator(selector).first().evaluate(element => {
              const rect = node => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom } }
              return { wrap: getComputedStyle(element).flexWrap, overflowX: getComputedStyle(element).overflowX,
                clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
                tabs: [...element.querySelectorAll('button')].map(button => ({ label: button.textContent, ...rect(button) })) }
            })
            const offscreen = measured.tabs.filter(tab => tab.left < 0 || tab.right > width + 0.5).map(tab => tab.label)
            report.geometry.push({ page: name, width, terminal: mode, offscreen, requests, ...measured })
            assert.deepEqual(requests, [], 'fixture must never request a live page or API')
            assert.deepEqual(measured.tabs.map(tab => tab.label), labels, 'rendered labels must remain intact')
            if (name !== 'OptionsHub') assert.deepEqual(offscreen, [], `${name}: tab labels require sideways scrolling at ${width}px`)
            if (name === 'TradeInViewPage' && width <= 420) {
              assert.equal(measured.wrap, 'wrap')
              assert.ok(measured.scrollWidth <= measured.clientWidth + 1, 'actual route must not require horizontal scrolling')
            }
            // The Journal fix must not change the neighboring classic Options layout.
            if (name === 'OptionsHub') assert.equal(measured.wrap, 'nowrap')
          } finally { await context.close() }
        }
      }
    } finally { await browser.close() }
  }
} catch (error) {
  report.error = error.message
  process.exitCode = 1
} finally {
  globalThis.fetch = originalFetch
  const resultIndex = process.argv.indexOf('--result')
  if (resultIndex !== -1) fs.writeFileSync(process.argv[resultIndex + 1], JSON.stringify(report, null, 2) + '\n')
  console.log(JSON.stringify(report, null, 2))
}
