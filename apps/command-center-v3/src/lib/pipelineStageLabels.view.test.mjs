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
  // FQ-032 review at 64b3abc24: a label inside a 26-28 px cell clipped, so the words lead in their own line and the
  // strip keeps the colour. The phone must NOT claim to show a per-cell label it cannot fit.
  ok(!/data-current="1"\]\s*\.wp-cell-text \{ display: inline/.test(block),
     'the phone still squeezes the label into an unfittable cell')
  ok(/\.wp-current-stage \{ display: block/.test(block), 'the phone has no full-width current-stage line')
  ok(/\.wp-stages > div \{ height: 22px !important; \}/.test(block), 'stage bars lost their phone height')
}
ok(/data-current=\{c\.stage === it\.stage \? "1" : undefined\}/.test(src), 'the current stage cell is not marked')
ok(/data-testid="wp-current-stage"/.test(src), 'no full-width current-stage line in the component')
ok(/\{failedHere \? 'Failed at' : 'Now at'\}/.test(src), 'the line does not distinguish a failure from the current step')
ok(/aria-label=\{cellTitle\(c\)\}/.test(src), 'cells lost their accessible label')
if (failures.length) { console.error('FQ-032 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-032 ok: the current stage reads in words on its own line at phone width; the strip stays colour; every cell keeps its accessible label')
