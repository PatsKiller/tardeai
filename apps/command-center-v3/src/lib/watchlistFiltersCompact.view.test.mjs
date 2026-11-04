// FQ-077: on a phone the filter stack collapses to a one-line summary; nothing is removed.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'WatchIntelligenceUnified.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
ok(/data-testid="filters-compact"/.test(src), 'no compact filter summary on the phone')
ok(/<details data-testid="filters-compact"/.test(src), 'the summary is not a details/summary (filters not reachable)')
ok(/Filters\{activeChips\.length \? ` · \$\{activeChips\.length\} active` : ' · none active'\}/.test(src),
   'the summary does not state how many filters are active')
ok(/max-width: 760px/.test(src), 'the compact summary is not scoped to phone width')
ok((src.match(/data-filter="/g) || []).length >= 4, 'filters were removed rather than collapsed')
if (failures.length) { console.error('FQ-077 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-077 ok: phone filter stack collapses to a named summary; every filter preserved')
