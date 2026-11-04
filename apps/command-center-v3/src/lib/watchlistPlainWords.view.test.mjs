// FQ-075: the watchlist row must state its state in plain words, never in screaming policy codes.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'WatchlistIntelligenceBoard.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
ok(!/Provider NONE · Model NONE · Policy NO_CALL/.test(src), 'the raw code line still renders verbatim')
ok(/No provider or model assigned/.test(src), 'plain wording for "no provider/model" missing')
ok(/not scheduled/.test(src), 'plain wording for "not scheduled" missing')
ok(/export function plainReason/.test(src), 'no plainReason mapping — an unknown code would still shout')
// the mapping must actually decode the two codes the audit saw
const m = src.match(/const PLAIN_REASON: Record<string, string> = \{([\s\S]*?)\}/)
ok(!!m, 'PLAIN_REASON map missing')
if (m) {
  ok(/NOT_SCHEDULED: 'not scheduled'/.test(m[1]), 'NOT_SCHEDULED not mapped')
  ok(/NO_CALL: 'no external call'/.test(m[1]), 'NO_CALL not mapped')
}
if (failures.length) { console.error('FQ-075 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-075 ok: watchlist rows speak plain words; unknown codes are de-coded, not shouted')
