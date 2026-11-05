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

const { EvidenceSentence } = await import(compile(join(app, 'src/components/HermesClosedLoopPanel.tsx')))
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
  assert.match(t, /fired on 12% of those days/)
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
