// FQ-032: on a phone the pipeline stage strip must NAME the current stage instead of showing unlabeled bars.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'WorkPipelinePanel.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }
const mq = src.match(/@media \(max-width: (\d+)px\) \{([\s\S]*?)\n      \}/)
ok(!!mq, 'no phone media query found in the panel')
if (mq) {
  const block = mq[2]
  ok(!/\.wp-cell-text \{ display: none; \}/.test(block), 'phone still hides every stage label')
  ok(/data-current="1"\]\s*\.wp-cell-text \{ display: inline/.test(block),
     'the current stage label is not shown on the phone')
  ok(/\.wp-stages > div \{ height: 22px !important; \}/.test(block), 'stage bars are not tall enough to carry a label')
}
ok(/data-current=\{c\.stage === it\.stage \? "1" : undefined\}/.test(src), 'the current stage cell is not marked')
ok(/aria-label=\{cellTitle\(c\)\}/.test(src), 'cells lost their accessible label')
if (failures.length) { console.error('FQ-032 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-032 ok: phone strip names the current stage; other cells stay compact; labels retained')
