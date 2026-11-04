// FQ-076: disabled filters and an unknown next-review time must EXPLAIN themselves in visible text.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'WatchIntelligenceUnified.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
ok(/data-testid="filters-unavailable-reason"/.test(src), 'no visible reason for the disabled filters')
ok(/off until the broker provider lands/.test(src), 'the reason is not stated in words')
ok(!/\|\| '—'\}\s*\n/.test(src.match(/Next review:[\s\S]{0,300}/)?.[0] ?? 'x'), 'next review still falls back to a bare dash')
ok(/not scheduled — no review time has been set/.test(src), 'the unknown next-review time is not explained')
ok((src.match(/data-filter="/g) || []).length >= 4, 'disabled filters were removed rather than explained')
if (failures.length) { console.error('FQ-076 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-076 ok: disabled filters give a visible reason; an unknown next-review time says why')
