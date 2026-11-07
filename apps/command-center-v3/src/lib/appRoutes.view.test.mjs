// LQ-20261107-175: a drill link to a route that does not exist renders a BLANK page.
//
// What happened: the Reports → System rollup "Research & reports" panel drills to `/v3/research-intel`
// (SystemRollupTab.tsx). No such route is declared — the surface is `/v3/research-intelligence` — and the
// shell declared no catch-all, so clicking it rendered the header and nothing else: the sweep recorded
// "page text len 161: header + 'Running the artifact the server serves · Diagnostics'". A blank page is
// indistinguishable from "no data" and from "still loading", which is the same argument that put
// RouteErrorBoundary on every route (a page that THROWS must say so, not disappear). A page that does not
// EXIST must say so too.
//
// Two gates, both source scans (nothing here renders React):
//   1. every internal /v3 link the app can follow resolves to a declared <Route> path;
//   2. the shell declares its own catch-all, and that surface names the path it could not resolve.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const srcRoot = join(app, 'src')
const failures = []
const ok = (cond, msg) => { if (!cond) failures.push(msg) }

function sourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...sourceFiles(p))
    else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) out.push(p)
  }
  return out
}

const appSrc = readFileSync(join(srcRoot, 'App.tsx'), 'utf8')
const routePaths = [...appSrc.matchAll(/<Route path="([^"]+)"/g)].map(m => m[1])

const normalise = target => {
  const path = String(target).split('?')[0].split('#')[0]
  const bare = path.startsWith('/v3/') ? path.slice('/v3/'.length) : path.replace(/^\//, '')
  return bare.replace(/\/+$/, '')
}
const declared = new Set(routePaths.map(normalise))

function resolves(target) {
  const want = normalise(target)
  if (declared.has(want)) return true
  const segs = want.split('/')
  for (const route of declared) {
    const rs = route.split('/')
    if (rs.length === segs.length && rs.every((s, i) => s === segs[i] || s.startsWith(':'))) return true
  }
  return false
}

// 1. Nothing the app links to may point at a route nobody declared.
const LINKS = /(?:drill|to|href)="(\/v3\/[^"]*)"|navigate\(\s*['"](\/v3\/[^'"]*)['"]/g
const dead = []
let scanned = 0
for (const file of sourceFiles(srcRoot)) {
  for (const m of readFileSync(file, 'utf8').matchAll(LINKS)) {
    const target = m[1] || m[2]
    scanned++
    if (!resolves(target)) dead.push(`${relative(app, file)} → ${target}`)
  }
}
ok(scanned > 0, 'the link scan found no internal /v3 links at all — the pattern no longer matches this codebase')
ok(dead.length === 0,
  `${dead.length} internal link(s) point at a route App.tsx does not declare, so they render a blank page: ${dead.join('; ')}`)

// 2. The shell declares its own catch-all. The outer App router only has path="/*" → <Shell />, which means an
//    unknown inner path used to match NOTHING and the outlet rendered empty.
const shellStart = appSrc.indexOf('function Shell')
ok(shellStart > 0, 'Shell is no longer a named function in App.tsx — this gate needs updating with the router')
const routesOpen = appSrc.indexOf('<Routes>', shellStart)
const routesClose = appSrc.indexOf('</Routes>', routesOpen)
const shellRoutes = routesOpen > 0 && routesClose > routesOpen ? appSrc.slice(routesOpen, routesClose) : ''
ok(/<Route\s+path="\*"/.test(shellRoutes),
  'the shell has no catch-all route (path="*"): an unknown path renders the header and nothing else, which reads as "no data"')
ok(/path="\*"[\s\S]{0,120}NotFound/.test(shellRoutes),
  'the catch-all does not render the NotFound surface — an unknown path must say so, not render a placeholder')

// 3. That surface names the route it could not resolve, so the reader can see the typo or the dead link.
let notFoundSrc = ''
try {
  notFoundSrc = readFileSync(join(srcRoot, 'pages', 'NotFoundPage.tsx'), 'utf8')
} catch {
  /* reported below */
}
ok(notFoundSrc.length > 0, 'src/pages/NotFoundPage.tsx is missing — the catch-all has no surface to render')
ok(/useLocation/.test(notFoundSrc) && /pathname/.test(notFoundSrc),
  'NotFoundPage does not read location.pathname, so it cannot tell the reader WHICH path failed')
ok(/not found|does not exist|no such page/i.test(notFoundSrc),
  'NotFoundPage does not say in words that the page does not exist')

if (failures.length) {
  console.error('LQ-20261107-175 FAILED:\n  - ' + failures.join('\n  - '))
  process.exit(1)
}
console.log(`LQ-20261107-175 ok: ${scanned} internal links resolve against ${declared.size} declared routes, and the shell states an unknown path`)
