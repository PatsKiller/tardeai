// FQ-075 (retirement half): the shadow board stays retired, and the file says so where a reader will look.
//
// THE PLAIN-WORDS HALF MOVED. This test used to render WatchIntelligenceUnified and assert the plain words the live
// /watchlist surface prints. That wording landed in FQ-078 / PR 2611 (cc-deepseek-4) — the same strings, in the
// component that owns the surface — so asserting it in a second gate here would only duplicate that PR and fail on any
// head that does not contain it. cc-deepseek-4 released this path at 15:00Z and I dropped the duplicate hunks.
//
// What remains is the half that has no other owner: `WatchlistIntelligenceBoard.tsx` is a page nothing mounts. The
// original review's finding was that the plain-words work had landed in a file no route renders. The durable fix is not
// a comment — it is this gate: if anyone imports the retired board again, CI fails and they have to make that decision
// deliberately. A rendered assertion cannot express "nothing imports it", which is why this file is a source scan.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const srcRoot = join(app, 'src')

const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

function sourceFiles(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...sourceFiles(p))
    else if (/\.(ts|tsx|mjs|js)$/.test(name) && !/\.test\.|\.spec\./.test(name)) out.push(p)
  }
  return out
}

// 1. nothing mounts the retired board.
const importers = sourceFiles(srcRoot)
  .filter(p => !p.endsWith('WatchlistIntelligenceBoard.tsx'))
  .filter(p => /WatchlistIntelligenceBoard/.test(readFileSync(p, 'utf8')))
ok(importers.length === 0,
  `WatchlistIntelligenceBoard is imported by ${importers.length} non-test file(s): ${importers.map(p => p.slice(app.length + 1)).join(', ')} — `
  + 'if it is being mounted again, move the FQ-075 assertions onto the new surface and update this guard deliberately')

// 2. /watchlist still goes to the live Watch surface, not to the board.
const appSrc = readFileSync(join(srcRoot, 'App.tsx'), 'utf8')
ok(/<Route path="watchlist"[\s\S]{0,220}Navigate to="\/watch\?tab=intelligence/.test(appSrc),
  '/watchlist no longer redirects to /watch?tab=intelligence — the live surface may have moved')

// 3. the file itself says it is retired, in its first screenful, where the next reader will see it.
const boardSrc = readFileSync(join(srcRoot, 'pages', 'WatchlistIntelligenceBoard.tsx'), 'utf8')
const header = boardSrc.split('\n').slice(0, 25).join('\n')
ok(/RETIRED/.test(header), 'WatchlistIntelligenceBoard.tsx does not state in its header that it is a retired shadow page')
ok(/WatchIntelligenceUnified/.test(header), 'the retirement note does not name the live surface that replaced it')

if (failures.length) {
  console.error('FQ-075 FAILED:\n  - ' + failures.join('\n  - '))
  process.exit(1)
}
console.log('FQ-075 ok: the shadow watchlist board stays unmounted, and both the route and the file say where the live surface is')
