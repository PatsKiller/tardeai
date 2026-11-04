// FQ-042: on a phone the journal journey list renders DATED SUMMARIES with details on demand,
// and nothing is removed — the full row still exists behind the toggle.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'TradeJourney.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
ok(/compact\?:\s*boolean/.test(src), 'Row has no compact prop')
ok(/data-testid="tj-row-compact"/.test(src), 'no compact summary row rendered')
ok(/<details[^>]*data-testid="tj-row-compact"/.test(src), 'the compact row is not a details/summary (no details-on-demand)')
ok(/<summary/.test(src), 'no summary line in the compact row')
ok(/compact=\{phone\}/.test(src), 'the list does not pass compact on phone')
// nothing removed: the full row still renders inside the toggle
ok(/const grid = \(\s*<div className="tradeinview-journey-row"/.test(src), 'the original full row was not preserved')
ok(/if \(!compact\) return grid/.test(src), 'desktop no longer renders the full row')
if (failures.length) { console.error('FQ-042 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-042 ok: phone list is dated summaries with details on demand; full row preserved')
