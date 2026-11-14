// LQ-20261113-3044 (C2 of REVIEW-2993ab-v3r, adopted from cc-opus-2's PROBE): the bridge banner's route rule, evaluated,
// not pattern-matched. The banner must follow the classic Watch hub (/watch-classic and its subpaths, /watch/<symbol> pages)
// and must NOT show on the v002 hub (/watch), /watch-lists, /watch-setups, /watchlist or other pages.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'SharedIntelligenceBridge.tsx'), 'utf8')
const m = src.match(/const showWatch = ([^\n]+)\n/)
assert.ok(m, 'showWatch expression present')
const showWatch = pathname => new Function('location', `return (${m[1]})`)({ pathname })
for (const p of ['/watch-classic', '/watch-classic/prospects', '/watch/AAPL', '/watch/intelligence/BBB']) assert.equal(showWatch(p), true, p)
for (const p of ['/watch', '/watch-lists', '/watch-setups', '/watchlist', '/journal']) assert.equal(showWatch(p), false, p)
console.log('SharedIntelligenceBridge route: 9 paths pass')
