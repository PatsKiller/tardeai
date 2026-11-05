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
  //
  // cc-deepseek-5 review at c5a25828c: this used to assert only the ABSENCE of one exact selector, so mutating the
  // rule to a plain `.wp-cell-text { display: inline; }` — every label back in a 22 px bar, the original bug — still
  // passed. Assert the hiding itself, which is what the operator actually gets.
  ok(/\.wp-cell-text \{ display: none/.test(block),
     'the phone does not hide the in-cell label, so every label is drawn in a 22 px bar and clips')
  ok(!/\.wp-cell-text \{[^}]*display: (inline|block)/.test(block),
     'the phone re-shows the in-cell label in a cell too small to fit it')
  ok(/\.wp-current-stage \{ display: block/.test(block), 'the phone has no full-width current-stage line')
  ok(/\.wp-stages > div \{ height: 22px !important; \}/.test(block), 'stage bars lost their phone height')
}
// FQ-032 (cc-deepseek-3 R1 at e983b7d7): display:block inside the phone query is the element's default, so without a
// base rule the line rendered at 1440 too and every desktop card stated the stage twice.
const outside = src.split(/@media \(max-width: \d+px\)/)[0]
ok(/\.wp-current-stage \{ display: none/.test(outside), 'no base rule hides the current-stage line above the phone width')
ok(/data-testid="wp-current-stage"/.test(src), 'no full-width current-stage line in the component')
ok(!/Failed at/.test(src), 'the line still infers a failure from RAG colour (the producer uses red for staleness too)')
ok(/aria-label=\{cellTitle\(c\)\}/.test(src), 'cells lost their accessible label')
if (failures.length) { console.error('FQ-032 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-032 ok: the current stage reads in words on its own line at phone width; the strip stays colour; every cell keeps its accessible label')
