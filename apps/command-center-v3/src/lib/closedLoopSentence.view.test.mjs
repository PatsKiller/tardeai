// node src/lib/closedLoopSentence.view.test.mjs
//
// FQ-026 (cc-deepseek-6 at c9638963, cc-deepseek-2's R1): the closed-loop evidence sentence is an operator-facing claim and
// nothing rendered it in a test. Two properties, both of which have been wrong or unverified on this branch:
//   * an ABSENT score_delta must not be rendered as "score unchanged" (that is a measurement nobody took);
//   * a real zero still says "score unchanged", and a non-zero delta still says up/down with its size.
// Mutation proof: put the old ternary back (absent -> "score unchanged") and the first check goes red.
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const fs = require('node:fs')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = fs.readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (url: any): any => (globalThis as any).__closedLoopFixture?.(url)')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { EvidenceSentence, ThresholdReviewModal } = await import(compile(join(app, 'src/components/HermesClosedLoopPanel.tsx')))
const text = (evidence, metrics) => renderToStaticMarkup(
  React.createElement(EvidenceSentence, { evidence, metrics })).replace(/<[^>]*>/g, '')

let pass = 0, fail = 0
const check = (n, fn) => { try { fn(); pass++; console.log(`  [PASS] ${n}`) } catch (e) { fail++; console.log(`  [FAIL] ${n}: ${e.message}`) } }

check('an absent delta is not rendered as a measurement', () => {
  for (const absent of [null, undefined, '']) {
    const t = text({ sample_days: 30, confidence: 'HIGH', score_delta: absent }, { trigger_rate: 0.12 })
    assert.match(t, /score change not recorded/, `absent ${JSON.stringify(absent)} -> ${t}`)
    assert.doesNotMatch(t, /score unchanged/, 'an absent delta claimed the score was unchanged')
  }
})
check('a real zero still reads as unchanged', () => {
  assert.match(text({ sample_days: 30, score_delta: 0 }, { trigger_rate: 0.12 }), /score unchanged/)
})
check('a non-zero delta keeps its direction and size', () => {
  assert.match(text({ sample_days: 30, score_delta: 0.042 }, {}), /score up 0\.042/)
  assert.match(text({ sample_days: 30, score_delta: -0.5 }, {}), /score down 0\.500/)
})
check('the surrounding sentence is intact', () => {
  const t = text({ sample_days: 30, confidence: 'HIGH', score_delta: 0 }, { trigger_rate: 0.12 })
  assert.match(t, /Based on 30 days of signals/)
  assert.match(t, /confidence high/)
  assert.match(t, /candidate trigger rate 12%/)
})


// Mount the production proposal-review caller; helper-only renders cannot guard this wiring.
const reviewText = (evidence, thresholds = [{ threshold_id: 'efficiency.tighten_threshold', safe_band: { min: 0.42, max: 0.58 } }]) => {
  const markup = renderToStaticMarkup(React.createElement(ThresholdReviewModal, {
    proposals: [{ id: 'synthetic-review', threshold_id: 'efficiency.tighten_threshold', label: 'Efficiency',
      current_value: 0.5, proposed_value: 0.52, direction: 'tighten', evidence }],
    thresholds, onClose: () => { throw new Error('render invoked close') },
    onRequestAction: () => { throw new Error('render invoked an approval') },
  }))
  return { markup, text: markup.replace(/<[^>]*>/g, '') }
}
check('the proposal review caller renders its own constructed evidence', () => {
  for (const [delta, expected] of [[null, /score change not recorded/], [0, /score unchanged/], [0.042, /score up 0\.042/], [-0.5, /score down 0\.500/]]) {
    const { text } = reviewText({ sample_days: 30, confidence: 'HIGH', score_delta: delta, candidate_metrics: { trigger_rate: 0.12 } })
    assert.match(text, /Review threshold proposals/)
    assert.match(text, /Based on 30 days of signals/)
    assert.match(text, /confidence high/)
    assert.match(text, /candidate trigger rate 12%/)
    assert.match(text, expected)
  }
})
check('the actual proposal caller keeps malformed score delta unknown', () => {
  for (const delta of [null, undefined, '', ' ', 'n/a', '—', 'abc', 'NaN', 'Infinity', '-Infinity', NaN, Infinity, -Infinity, true, false, [], [0], {}, { value: 0 }]) {
    const { text } = reviewText({ sample_days: 30, score_delta: delta })
    assert.match(text, /score change not recorded/)
    assert.doesNotMatch(text, /score (?:unchanged|up|down)/)
  }
})
check('the actual caller preserves finite numeric string zero and signed changes', () => {
  for (const [delta, phrase] of [['0', /score unchanged/], [' +0.042 ', /score up 0\.042/], ['-0.5', /score down 0\.500/]]) {
    assert.match(reviewText({ score_delta: delta }).text, phrase)
  }
})

check('the safe band constrains the threshold value, not the candidate score', () => {
  const { text } = reviewText({ candidate_score: 0.91, score_delta: 0.042 })
  assert.match(text, /Allowed threshold range: 0\.42–0\.58/)
  assert.doesNotMatch(text, /score sits in/)
})
check('the proposal caller retains scoring evidence behind a closed disclosure', () => {
  const { markup, text } = reviewText({ sample_days: 30, score_delta: 0,
    runner_up: { value: 0.51, score: 0.8123 }, metric_contributions: { efficiency: 0.2345 },
    confidence_factors: ['sample_complete', 'stable_window'] })
  assert.match(text, /How this was scored/)
  assert.match(text, /next best candidate was 0\.51 at 0\.8123/)
  assert.match(text, /efficiency=0\.2345/)
  assert.match(text, /sample_complete, stable_window/)
  const details = markup.match(/<details([^>]*)>/)
  assert.ok(details, 'raw detail was removed')
  assert.doesNotMatch(details[1], /\bopen\b/, 'raw detail is open by default')
})

check('the full sample is not presented as the candidate scoring window', () => {
  for (const holdout of [undefined, { passed: true, train_score: 0.4, holdout_score: 0.38 }, { skipped: true }]) {
    const { text } = reviewText({ sample_days: 30, score_delta: 0, holdout_validation: holdout,
      candidate_metrics: { trigger_rate: 0.12 }, counterfactual: { window_days: 14, trigger_rate: 0.5 } })
    assert.match(text, /Based on 30 days of signals/)
    assert.match(text, /candidate trigger rate 12%/)
    assert.match(text, /scoring-window length not recorded/)
    assert.doesNotMatch(text, /fired on 12% of those days/)
    assert.doesNotMatch(text, /23 days|14 days|50%/)
  }
})

// Privacy tripwire: operator captures are private evidence, never source-tree assets.
for (const width of [390, 412]) {
  check(`operator capture ${width} stays outside the published source tree`, () => {
    const capture = resolve(app, '../../docs/evidence/fq025', `fq025-before-105df180e-phone${width}.png`)
    assert.equal(existsSync(capture), false, 'Private operator captures must remain outside the source tree')
  })
}

console.log(`closedLoopSentence.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
