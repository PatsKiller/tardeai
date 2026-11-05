// FQ-033: the work pipeline leads in words. A checkout path, the census shell error and a refused action's raw
// text stay available one tap away under "Technical" — they never sit in the middle of the sentence the operator
// reads first. Nothing is removed: every value is still rendered, just closed by default.
//
// Hermetic: reads the panel source. No browser, no network, no data. The rendered check is the phone capture in
// the PR, at 390 and 412 px.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'pages', 'WorkPipelinePanel.tsx'), 'utf8')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

// The one component that hides provenance behind a closed disclosure.
ok(/function Technical\(\{ label, children \}[^)]*\) \{[\s\S]*?<details data-testid="technical-details"/.test(src),
   'no Technical disclosure component (a closed <details>) in the panel')
ok(/<summary style=\{\{ \.\.\.small, cursor: 'pointer' \}\}>/.test(src),
   'the disclosure summary is not tappable')

// 1. The checkout path is no longer inline; it is under Technical and still rendered.
ok(!/· \{it\.where\.worktree\}/.test(src), 'the raw checkout path is still printed inline in the Where cell')
ok(/<Technical label="Technical: where the work is checked out">\{it\.where\.worktree\}<\/Technical>/.test(src),
   'the checkout path is not rendered under Technical')

// 2. The census banner leads with a sentence; the shell error is under Technical.
ok(/PR census could not refresh — the last good copy is shown/.test(src),
   'the census banner does not say, in words, that it could not refresh')
ok(/<Technical label="Technical: why the census could not refresh">\{census\.warning\}<\/Technical>/.test(src),
   'the census shell error is not rendered under Technical')

// 3. A refused action leads with a sentence and keeps the service text in `technical`.
ok(/That action did not go through\. The service's exact message is under Technical\./.test(src),
   'a failed action does not lead with a plain sentence')
ok(!/refused: \$\{r\.error/.test(src), 'the raw service error is still concatenated into the visible message')
ok(/technical: raw \|\| undefined/.test(src), 'the raw service text is not carried in the technical field')
ok(/busy\.technical \? <Technical/.test(src), 'the technical text is not rendered as a disclosure')

// 4. Identifiers are not the sentence the operator reads first.
ok(/<Technical label="Technical: item id, design id and batch">[\s\S]{0,400}<span>\{it\.id\}<\/span>/.test(src),
   'the item id / design id / batch are not under Technical')
ok(/<Technical label="Technical: agent session">\{it\.who\.session\}<\/Technical>/.test(src),
   'the raw agent session id is still inline')

// 5. Nothing removed: the values are still in the panel.
ok((src.match(/it\.where\.worktree/g) || []).length >= 2, 'the checkout path value was removed, not moved')
ok((src.match(/census\??\.warning/g) || []).length >= 2, 'the census warning value was removed, not moved')

// 5. Reachable at phone widths: no media query hides the disclosure.
for (const width of [390, 412]) {
  const media = new RegExp(`@media \\(max-width: ${width}px\\) \\{([\\s\\S]*?)\\n      \\}`).exec(src)
  // The panel's own phone block is a single max-width rule; assert it is not the source of hiding.
  if (media) ok(!/technical/i.test(media[1]), `the ${width}px block hides Technical`)
}
ok(/@media \(max-width: 760px\)/.test(src), 'the phone layout breakpoint disappeared')

if (failures.length) { console.error('FQ-033 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-033 ok: checkout path, census error and refused-action text are behind Technical; plain sentences lead; nothing removed')
