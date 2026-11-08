// LQ-20261107-481 — a card's identity is its content, not its position in a list that is still filling.
//
// Measured 2026-11-07 19:20 ET on /v3/intelligence/classic: the Command Center list is assembled from
// ~13 feeds and the card id was `${source}-${out.length}`. Each time one more feed resolved the
// positions shifted, React saw a new key for an unchanged card and remounted it, and every mount
// re-read /api/v2/inference/ensemble (26 reads, 26 distinct ids, zero repeats — the signature of
// remount churn rather than polling) and /api/v2/llm/oauth-lanes (21 identical reads). The page never
// reached network idle.
//
// Red-first: this file does not resolve `./intelItemId.ts` on the parent commit, and the negative
// control below shows the positional formula drifting for an unchanged row.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { intelItemId, idSlug, titleTag } from './intelItemId.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

const signal = { source: '/api/v2/trade-ai', type: 'setup', symbol: 'AAPL', title: 'AAPL GO score 42' }

// 1. The same row keeps its id when other rows arrive before it in the list.
const before = [signal]
const after = [
  { source: '/api/v2/risk', type: 'risk', symbol: 'MSFT', title: 'MSFT risk/stop review' },
  { source: '/api/v2/command', type: 'telegram/action', symbol: 'NVDA', title: 'NVDA triggered stop from command feed' },
  signal,
]
const idBefore = intelItemId(before[0])
const idAfter = intelItemId(after[2])
assert.equal(idAfter, idBefore, 'an unchanged row must keep its card identity when other rows arrive first')

// 2. Negative control — the formula this change removes drifts for that same row.
const positional = (row: typeof signal, index: number) => `${row.source}-${index}`
assert.notEqual(positional(after[2], 2), positional(before[0], 0), 'the positional formula is the defect: it must drift')

// 3. The id is deterministic, and two different contents are told apart by the title tag.
assert.equal(intelItemId({ ...signal }), idBefore)
assert.notEqual(intelItemId({ ...signal, title: 'AAPL WAIT score 12' }), idBefore)
assert.notEqual(intelItemId({ ...signal, type: 'watchlist' }), idBefore)

// 4. Symbol case is not identity: a feed that re-cases a ticker must not remount the card.
assert.equal(intelItemId({ ...signal, symbol: 'aapl' }), idBefore)

// 5. Genuinely identical rows stay distinct, by an occurrence counter that does not encode position.
const dup = intelItemId(signal, 1)
assert.notEqual(dup, idBefore)
assert.equal(dup, intelItemId({ ...signal }, 1))
assert.equal(intelItemId(signal, 2), `${intelItemId(signal)}~3`)

// 6. The id is interpolated into a query string, so it must be URL-safe whatever the title holds.
const messy = intelItemId({ source: '/api/v2/command', type: 'portfolio-news', symbol: 'BRK.B', title: 'Why & how: "X" / Y? #1 — 100% done' })
assert.match(messy, /^[a-z0-9~-]+$/, `id must be URL-safe, got ${messy}`)
assert.ok(!messy.includes('&') && !messy.includes('#') && !messy.includes('?') && !messy.includes('/'))

// 7. Slugs are stable and bounded.
assert.equal(idSlug('/api/v2/trade-ai'), 'api-v2-trade-ai')
assert.equal(idSlug('BRK.B'), 'brk-b')
assert.equal(idSlug('', 'unknown'), 'unknown')
assert.equal(titleTag('same').length, 8)

// 8. The page uses it — the source guard is what makes the fix load-bearing on the site of the bug.
// nosemgrep: tq-ts-test-reads-source-text -- a source guard layered on the behavioural assertions above; a text read alone could pass on a commented-out page, which is why the id itself is called and asserted first.
const page = readFileSync(join(app, 'src/components/CentralIntelligencePages.tsx'), 'utf8')
assert.ok(page.includes("from '../lib/intelItemId'"), 'the page must import the content id')
assert.ok(!page.includes('${x.source}-${out.length}'), 'the positional card id must be gone')

console.log('intelItemId: content identity survives list growth; positional ids drift (negative control); ids are URL-safe')
