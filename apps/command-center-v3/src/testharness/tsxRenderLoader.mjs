// A Node module hook that lets the test suite RENDER the real page components.
//
// Why this exists (codex, #2541 round four): every test of this page drove a PURE helper beside the JSX branch, so
// deleting the branch itself left the suite green. A pure-function test beside a JSX branch is a test of a sibling.
//
// This hook transpiles .ts/.tsx on import (the app's own TypeScript compiler, JSX classic runtime) and stubs
// stylesheet imports, so a plain `node --experimental-strip-types` test can `import` the page and render it with
// react-dom/server. Nothing is written to disk and no production body changes.
import fs from 'node:fs'
import ts from 'typescript'

const STYLE = /\.(css|scss|sass|less)$/

export async function resolve(specifier, context, next) {
  if (STYLE.test(specifier)) {
    return { url: 'data:text/javascript,export default {}', shortCircuit: true }
  }
  // The app writes extensionless relative imports (../hooks/useApi); Node needs the real file.
  if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
    for (const cand of ['.ts', '.tsx', '/index.ts', '/index.tsx', '.js']) {
      try {
        return await next(specifier + cand, context)
      } catch { /* try the next one */ }
    }
  }
  return next(specifier, context)
}

export async function load(url, context, next) {
  if (url.startsWith('file:') && /\.(ts|tsx)$/.test(url)) {
    const src = fs.readFileSync(new URL(url), 'utf8')
    const out = ts.transpileModule(src, {
      fileName: url,
      compilerOptions: {
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
        verbatimModuleSyntax: false,
        isolatedModules: true,
      },
    })
    return { format: 'module', source: out.outputText, shortCircuit: true }
  }
  return next(url, context)
}
