// Route-level regression: exactly one <h1> per route, and the family roots render the shell's Outlet.
//
// Live defect (hourly audit, LEAD-ASSIGN-WEALTH-H1-FAMILYROOT-FIX-20261115T2118Z):
//   * `FamilyPage.tsx` rendered a second <h1>, so every route whose view is a family page (the audit counted 24:
//     /ops/* ×11, /watch/* ×11, /portfolio, /portfolio/levels, /portfolio/retirement, /home/needs,
//     /home/outlook) carried two top-level headings beside the shell's own (`shell/Shell.tsx`).
//   * `/cio /defense /journal /performance /reentry /retirement /risk /rotation /trading` — the family roots
//     App.tsx registers — resolved to `known:false` in `shell/nav.ts`, so the shell hid the Outlet and printed
//     "Unknown Wealth address" over a page that exists.
//
// The test renders the REAL Shell and the REAL FamilyPage under a MemoryRouter (the registry is read from
// `routes/families.ts`, the same table App.tsx routes from), and composes the per-route guarantee from two
// facts: the shell renders exactly one <h1> on every route, and no other component renders one at all.
//
// Both modules carry JSX or extensionless imports, so they are compiled with the repo's own tsc into the same
// cache `performance-page.test.mjs` uses; CSS is not bundled and gets empty stubs, as in shell-logic.test.mjs.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const SRC = path.join(APP, 'src')
const GATE_CACHE = path.join(APP, 'node_modules/.cache/wealth-gate-tests')

/** The nine roots the audit named, plus the two parameterised family paths App.tsx also registers. */
const FAMILY_ROOTS = ['/cio', '/defense', '/journal', '/performance', '/reentry', '/retirement', '/risk', '/rotation', '/trading']

let gate = null
function compileGateModules() {
  if (gate !== null) return gate
  fs.mkdirSync(GATE_CACHE, { recursive: true })
  const out = fs.mkdtempSync(path.join(GATE_CACHE, 'route-h1-'))
  const cssDecl = path.join(out, 'css-modules.d.ts')
  fs.writeFileSync(cssDecl, "declare module '*.css'\n")
  // The build defines these three (vite-env.d.ts); outside vite the identifiers are free.
  const globalsDecl = path.join(out, 'build-globals.d.ts')
  fs.writeFileSync(globalsDecl, [
    'declare const __WEALTH_SOURCE_SHA__: string | null',
    'declare const __WEALTH_APP_VERSION__: string',
    'declare const __WEALTH_BUILT_AT__: string',
    '',
  ].join('\n'))
  const roots = [
    'src/shell/Shell.tsx',
    'src/shell/nav.ts',
    'src/pages/FamilyPage.tsx',
    'src/routes/families.ts',
  ].map(p => path.join(APP, p))
  const args = [
    '--target', 'ES2020', '--module', 'commonjs', '--moduleResolution', 'node', '--strict', '--skipLibCheck',
    '--allowImportingTsExtensions', '--rewriteRelativeImportExtensions', '--jsx', 'react-jsx',
    '--typeRoots', path.join(APP, 'node_modules/@types'), '--types', 'node', '--outDir', out,
    ...roots, cssDecl, globalsDecl,
  ]
  const r = spawnSync(process.execPath, [path.join(APP, 'node_modules/typescript/bin/tsc'), ...args], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`tsc could not compile the route-h1 gate modules (rc ${r.status}):\n${r.stdout ?? ''}${r.stderr ?? ''}`)
  fs.writeFileSync(path.join(out, 'package.json'), '{"type":"commonjs"}')
  process.once('exit', () => fs.rmSync(out, { recursive: true, force: true }))
  // tsc does not copy assets: every .css the graph imports becomes an empty stub, and the real .mjs the
  // adapter modules import are copied beside their compiled consumers.
  for (const rel of listFiles(SRC, /\.css$/)) {
    const dest = path.join(out, path.relative(SRC, rel))
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    fs.writeFileSync(dest, '')
  }
  const mjsDir = path.join(out, 'pages/portfolio/analytics')
  fs.mkdirSync(mjsDir, { recursive: true })
  for (const f of fs.readdirSync(path.join(SRC, 'pages/portfolio/analytics'))) {
    if (f.endsWith('.mjs')) fs.copyFileSync(path.join(SRC, 'pages/portfolio/analytics', f), path.join(mjsDir, f))
  }
  // The build defines these; in Node they are free identifiers looked up on the global object.
  globalThis.__WEALTH_SOURCE_SHA__ = null
  globalThis.__WEALTH_APP_VERSION__ = '0.1.0'
  globalThis.__WEALTH_BUILT_AT__ = '2026-11-15T00:00:00.000Z'
  const load = createRequire(import.meta.url)
  load.extensions['.css'] = () => {}
  gate = {
    Shell: load(path.join(out, 'shell/Shell.js')).Shell,
    resolve: load(path.join(out, 'shell/nav.js')).resolve,
    NAV: load(path.join(out, 'shell/nav.js')).NAV,
    FamilyPage: load(path.join(out, 'pages/FamilyPage.js')).FamilyPage,
    FAMILIES: load(path.join(out, 'routes/families.js')).FAMILIES,
    cssStubs: path.join(out, 'shell'),
  }
  assert.ok(fs.existsSync(path.join(gate.cssStubs, 'v02.css')), 'the shell CSS stub must exist beside the compiled shell')
  return gate
}

function listFiles(dir, re, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) listFiles(p, re, acc)
    else if (re.test(e.name)) acc.push(p)
  }
  return acc
}

/** Render a pathname through the real Shell, with a probe where the page would sit. */
function renderShell(pathname) {
  const { Shell } = compileGateModules()
  return renderToStaticMarkup(
    React.createElement(MemoryRouter, { initialEntries: [pathname] },
      React.createElement(Routes, null,
        React.createElement(Route, { element: React.createElement(Shell) },
          React.createElement(Route, { path: '*', element: React.createElement('p', { id: 'probe' }, 'probe') })))),
  )
}

const count = (hay, needle) => hay.split(needle).length - 1
/** React escapes text children; a title with an ampersand (`Performance & Income`) is drawn as `&amp;`. */
const escapeText = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Every route the app registers: the 8 NAV group roots, every NAV view, and the family registry's paths. */
function registeredRoutes() {
  const { NAV, FAMILIES } = compileGateModules()
  const routes = []
  for (const g of NAV) {
    routes.push(`/${g.id}`)
    for (const v of g.views) routes.push(`/${g.id}/${v.id}`)
  }
  for (const f of FAMILIES) {
    if (f.path === '/') continue
    routes.push(f.path.replace(':symbol', 'SYNTH'))
  }
  return [...new Set(routes)]
}

test('the shell renders exactly one <h1> on every registered route, and the Outlet is not gated off', () => {
  compileGateModules()
  const failures = []
  for (const route of registeredRoutes()) {
    const html = renderShell(route)
    const h1 = count(html, '<h1')
    if (h1 !== 1) failures.push(`${route}: ${h1} <h1> (expected exactly 1, the shell's)`)
    if (!html.includes('id="probe"')) failures.push(`${route}: the shell did not render its Outlet`)
  }
  assert.deepEqual(failures, [], `one <h1> and a rendered Outlet on every route\n${failures.join('\n')}`)
})

test('the nine family roots render their page, not "Unknown Wealth address"', () => {
  compileGateModules()
  const failures = []
  for (const root of FAMILY_ROOTS) {
    const html = renderShell(root)
    if (html.includes('Unknown Wealth address')) failures.push(`${root}: still prints "Unknown Wealth address"`)
    if (!html.includes('id="probe"')) failures.push(`${root}: the shell hid its Outlet`)
    if (count(html, '<h1') !== 1) failures.push(`${root}: ${count(html, '<h1')} <h1> (expected exactly 1)`)
  }
  assert.deepEqual(failures, [], `family roots render\n${failures.join('\n')}`)
})

test('the gate still refuses a genuinely unknown first segment', () => {
  const { resolve } = compileGateModules()
  assert.equal(resolve('/not-a-page').known, false, 'an unregistered first segment must stay unknown')
  assert.equal(resolve('/home/today').known, true, 'a NAV view must stay known')
  assert.equal(resolve('/home').known, true, 'a NAV root must stay known')
})

test('FamilyPage renders no <h1>: the shell owns the only one', () => {
  const { FamilyPage, FAMILIES } = compileGateModules()
  const marked = FAMILIES.filter(f => f.id !== 'home') // home's path is '/' and is drawn by NAV's own view
  assert.ok(marked.length >= 9, `the registry must still list the families (got ${marked.length})`)
  for (const family of marked) {
    const html = renderToStaticMarkup(React.createElement(FamilyPage, { family }))
    assert.equal(count(html, '<h1'), 0, `${family.id}: FamilyPage rendered an <h1>`)
    assert.equal(count(html, `<h2 id="h-${family.id}"`), 1, `${family.id}: the family title is the page's <h2>, id kept`)
    assert.ok(html.includes(escapeText(family.title)), `${family.id}: the family title is still drawn`)
  }
})

test('a NAV route still draws its group tabs', () => {
  const { NAV } = compileGateModules()
  const failures = []
  for (const g of NAV) {
    const html = renderShell(`/${g.id}`)
    if (!html.includes('class="tabs"')) failures.push(`${g.id}: the tabs nav is gone`)
    for (const v of g.views) {
      const labels = [...html.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)].map(a => a[1].replace(/<[^>]*>/g, ''))
      const expected = escapeText(v.label)
      const present = labels.some(label => label === expected || (g.id === 'home' && v.id === 'needs' && label.startsWith(expected + ' · ')))
      if (!present) failures.push(`${g.id}: tab ${v.label} is missing`)
    }
  }
  assert.deepEqual(failures, [], `NAV routes keep their tabs\n${failures.join('\n')}`)
})

test('no component but the shell renders an <h1>', () => {
  // The per-route guarantee above is only complete if the routed pages contribute no <h1> of their own. Comments
  // are stripped first: two page files mention the rule in prose and must not be rewritten to satisfy a scan.
  const offenders = []
  for (const file of listFiles(SRC, /\.tsx$/)) {
    if (/Tests\.tsx$|\.test\.tsx$/.test(file)) continue
    const code = fs.readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    if (/<h1[\s>]/.test(code)) offenders.push(path.relative(SRC, file))
  }
  assert.deepEqual(offenders, ['shell/Shell.tsx'], '<h1> belongs to the shell alone')
})
