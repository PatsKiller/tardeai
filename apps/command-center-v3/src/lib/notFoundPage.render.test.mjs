// LQ-20261107-175: the not-found surface must RENDER what it promises — the path it could not resolve and a way
// out — not merely exist as a file the router can point at. The route table and the dead link are gated by
// appRoutes.view.test.mjs; this file renders the component and reads the markup it produces.
//
//   node src/lib/notFoundPage.render.test.mjs
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

let pass = 0, fail = 0
const check = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) }
}

// The colour/type tokens are a facade over the theme; the surface only needs values, so stub them rather than
// transpiling the whole design-system chain.
const tokens = {
  BB: {
    amber: 'var(--amber)', amberDim: 'var(--amber-dim)', bg: 'var(--bg)', bgPanel: 'var(--bg-panel)',
    text0: 'var(--text0)', text1: 'var(--text1)', text2: 'var(--text2)', text3: 'var(--text3)',
  },
  TYPE: { xs: 10, sm: 11, base: 12, md: 14, lg: 18, xl: 24 },
}
const seenPaths = []
const router = {
  useLocation: () => ({ pathname: seenPaths[seenPaths.length - 1] }),
  Link: props => React.createElement('a', { href: props.to }, props.children),
}

function loadTsx(path) {
  const js = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS, esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  const localRequire = name => {
    if (name === 'react') return React
    if (name === 'react/jsx-runtime') return require('react/jsx-runtime')
    if (name === 'react-router-dom') return router
    if (name.endsWith('.css')) return {}
    if (name.endsWith('lib/watchTokens')) return tokens
    throw new Error(`unexpected import ${name}`)
  }
  new Function('exports', 'require', 'module', js)(module.exports, localRequire, module)
  return module.exports
}

const NotFoundPage = loadTsx(join(app, 'src/pages/NotFoundPage.tsx')).default

for (const pathname of ['/v3/research-intel', '/v3/does-not-exist']) {
  seenPaths.push(pathname)
  const html = renderToStaticMarkup(React.createElement(NotFoundPage))
  check(`${pathname}: says the page does not exist`, /THIS PAGE DOES NOT EXIST/.test(html), html.slice(0, 200))
  check(`${pathname}: names the path it could not resolve`, html.includes(pathname), html.slice(0, 200))
  check(`${pathname}: is a live region, not a silent blank`, /role="alert"/.test(html))
  check(`${pathname}: offers a way out`, /href="\/v3"/.test(html) && /Research Intelligence/.test(html))
}

if (fail) { console.error(`notFoundPage render: ${fail} FAILED, ${pass} passed`); process.exit(1) }
console.log(`notFoundPage render ok: ${pass} checks — the unknown-path surface states the path and links onward`)
