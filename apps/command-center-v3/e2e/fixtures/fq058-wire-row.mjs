/**
 * Emits the REAL compact ArticleCard markup (server-rendered from the page module) for the FQ-058
 * browser regression. Run by e2e/fq058-wire-clamp.spec.ts with node, so Playwright never has to
 * transform the page module (it imports a .css file, which Playwright's loader cannot parse).
 *
 * Same technique as src/lib/researchWireRow.view.test.mjs: transpile with the project's TypeScript,
 * drop the .css import, and keep every other module real.
 */
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const memo = new Map()

function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
    .replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
    .replace(/import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__fixture')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (_whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (existsSync(target) && statSync(target).isDirectory()) {
      target = ['index.ts', 'index.tsx', 'index.js'].map(s => resolve(target, s)).find(existsSync)
    }
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const LONG_TITLE =
  'The retirement contribution deadline, the catch-up rules and the Roth conversion window all move ' +
  'together this quarter, and the household should decide before the next payroll run whether to ' +
  'fund from cash or from the bond ladder that matures in the same week as the tax payment'
const LONG_LEDE =
  'The conversion would reset the holding period on the oldest lots and the five-year clock would ' +
  'start again, so the sizing that looked obvious in the spring is not the sizing that applies now'

const { ArticleCard } = await import(compile(join(app, 'src/pages/ResearchIntelligenceHub.tsx')))
const item = {
  id: 'fq058-clamp-row',
  title: LONG_TITLE,
  lede: LONG_LEDE,
  symbol: 'SCHD',
  categories: ['income'],
  source_system: 'hermes',
  starred: false,
  freshness_tier: 'fresh',
  freshness_label: '2h',
  created_at: new Date().toISOString(),
}
process.stdout.write(renderToStaticMarkup(
  React.createElement(ArticleCard, { item, catMeta: {}, view: 'compact', onOpen: () => {}, onFeedback: () => {} }),
))
