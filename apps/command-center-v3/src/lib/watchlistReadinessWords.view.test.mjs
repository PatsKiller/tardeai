// FQ-078: research cards explain readiness in plain words; the raw enum stays in the provenance panel only.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'components', 'rockville', 'WatchCardV2.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
ok(/export function freshnessWords/.test(src), 'no plain-words mapping')
ok(/CURRENT: 'up to date'/.test(src), 'CURRENT not mapped to words')
ok(/AFTER_HOURS_CURRENT: 'up to date after the close'/.test(src), 'AFTER_HOURS_CURRENT not mapped')
ok(/DATA_UNAVAILABLE: 'unavailable — no recent read succeeded'/.test(src), 'DATA_UNAVAILABLE not mapped')
// the main line must use the words, not the enum
const main = src.match(/data-provenance-line[\s\S]{0,300}/)?.[0] ?? ''
ok(/\{freshnessWords\(freshnessState\)\}/.test(main), 'the main reading line still prints the raw enum')
ok(!/\{freshnessState \|\| 'DATA_UNAVAILABLE'\}/.test(main), 'the main line still falls back to the raw code')
// developer detail preserved
ok(/<div>freshness: \{freshnessState \|\| '—'\}<\/div>/.test(src), 'the provenance panel lost the raw enum')
if (failures.length) { console.error('FQ-078 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-078 ok: cards speak plain words; raw enum kept in the provenance panel')
