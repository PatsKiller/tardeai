// LQ-20261113-3044 (C2 of REVIEW-2993ab-v3r, adopted from cc-opus-2's PROBE): the bridge banner's route rule, evaluated,
// not pattern-matched. The banner must follow the classic Watch hub (/watch-classic and its subpaths, /watch/<symbol> pages)
// and must NOT show on /watch-lists, /watch-setups, /watchlist or other pages.
// RELEASE-3 ruling (lead 2026-11-14T10:18:07Z) REVERSES the earlier v002-hub exclusion: removing the bridge from bare
// /watch without an approved mockup is a UI removal, so the banner MUST mount there again
// (tests/test_reentry_cross_surface_v6.py pins it). '/watch' moved from the false list to the true list below.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'SharedIntelligenceBridge.tsx'), 'utf8')
const m = src.match(/const showWatch = ([^\n]+)\n/)
assert.ok(m, 'showWatch expression present')
const showWatch = pathname => new Function('location', `return (${m[1]})`)({ pathname })
for (const p of ['/watch', '/watch-classic', '/watch-classic/prospects', '/watch/AAPL', '/watch/intelligence/BBB']) assert.equal(showWatch(p), true, p)
for (const p of ['/watch-lists', '/watch-setups', '/watchlist', '/journal']) assert.equal(showWatch(p), false, p)
console.log('SharedIntelligenceBridge route: 9 paths pass')
