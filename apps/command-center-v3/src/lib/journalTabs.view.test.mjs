// FQ-041: the journal tab row must WRAP at phone width, not scroll the last tab off-screen.
// The rule is asserted against the stylesheet the page actually loads, and against the tab list the page renders.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, '..', 'index.css'), 'utf8')
const hub = readFileSync(join(here, '..', 'pages', 'JournalHub.tsx'), 'utf8')
const failures = []
const ok = (cond, msg) => { if (!cond) failures.push(msg) }

// the phone media query must exist and set wrap + no horizontal scroller on .hub-tabs
const mq = css.match(/@media[^{]*max-width:\s*4[0-9]{2}px[^{]*\{([\s\S]*?)\n\}/)
ok(!!mq, 'no phone-width media query found in index.css')
if (mq) {
  const block = mq[1]
  const rule = block.match(/\.hub-tabs\s*\{([\s\S]*?)\}/)
  ok(!!rule, 'the phone media query does not address .hub-tabs')
  if (rule) {
    ok(/flex-wrap:\s*wrap/.test(rule[1]), 'phone .hub-tabs does not wrap')
    ok(/overflow-x:\s*visible/.test(rule[1]), 'phone .hub-tabs still creates a horizontal scroller')
  }
}
// every tab label must still be rendered (nothing removed — brief rule 2)
const tabs = hub.match(/const TABS = \[([\s\S]*?)\] as const/)
ok(!!tabs, 'TABS list not found — did the page change shape?')
if (tabs) ok((tabs[1].match(/'/g) || []).length / 2 === 15, 'expected 15 journal tabs, labels changed')

if (failures.length) { console.error('FQ-041 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-041 ok: phone .hub-tabs wraps without a horizontal scroller; 15 tabs rendered')
