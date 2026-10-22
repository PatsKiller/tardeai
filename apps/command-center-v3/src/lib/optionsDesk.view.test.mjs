// node --experimental-strip-types src/lib/optionsDesk.view.test.mjs
// Fails if any term or metric the Options desk renders lacks a glossary entry.
//  - every literal key (k="…", glossaryKey: '…') in the desk view and model must resolve;
//  - every dynamic key expression must come from the model, whose emitted keys
//    optionsDeskModel.test.ts proves resolve;
//  - every <Term>/<ControlTip>/<Missing> carries a key.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { GLOSSARY } from './optionsGlossary.ts'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FILES = ['../components/options/OptionsDesk.tsx', '../components/options/GlossaryTip.tsx', './optionsDeskModel.ts']
const DYNAMIC_OK = new Set(['c.glossaryKey', 'e.glossaryKey', 'l.glossaryKey', 'b.glossaryKey', 'i.stuckKey', 'strategyGlossaryKey(i.strategy)', 'k'])
let failed = 0
const fail = msg => { failed++; console.error('FAIL ' + msg) }

let literals = 0
for (const rel of FILES) {
  const src = fs.readFileSync(path.join(HERE, rel), 'utf8')
  for (const m of src.matchAll(/\bk=["']([a-z_]+\.[a-z0-9_]+)["']/g)) { literals++; if (!GLOSSARY[m[1]]) fail(`${rel}: k="${m[1]}" has no glossary entry`) }
  for (const m of src.matchAll(/\bglossaryKey:\s*['"]([a-z_]+\.[a-z0-9_]+)['"]/g)) { literals++; if (!GLOSSARY[m[1]]) fail(`${rel}: glossaryKey '${m[1]}' has no glossary entry`) }
  for (const m of src.matchAll(/\bkey:\s*['"]([a-z]+\.[a-z0-9_]+)['"]/g)) { literals++; if (!GLOSSARY[m[1]]) fail(`${rel}: key '${m[1]}' has no glossary entry`) }
  for (const m of src.matchAll(/'(blocker\.[a-z_]+|term\.[a-z_]+|lifecycle\.[a-z]+|fresh\.[a-z_]+|concept\.[a-z_]+|strategy\.[a-z_]+)'/g)) {
    if (!GLOSSARY[m[1]]) fail(`${rel}: '${m[1]}' has no glossary entry`)
  }
  for (const m of src.matchAll(/\bk=\{([^}]+)\}/g)) {
    const expr = m[1].trim()
    if (!DYNAMIC_OK.has(expr)) fail(`${rel}: dynamic key expression k={${expr}} is not a model-emitted key; add it to the model and its test`)
  }
  for (const m of src.matchAll(/<(Term|ControlTip|Missing)\b(?![^>]*\bk=)[^>]*>/g)) fail(`${rel}: <${m[1]}> without k=`)
}
if (literals < 15) fail(`expected the desk to render many glossary terms, found ${literals} literal keys`)

// The desk renders no POST of its own: next steps go through the hub's existing flows.
const desk = fs.readFileSync(path.join(HERE, '../components/options/OptionsDesk.tsx'), 'utf8')
if (/fetch\(|method:\s*['"]POST/.test(desk)) fail('OptionsDesk.tsx must not fetch or POST; use the hub callbacks')
if (/place_order|\/orders?\b|preflight\b.*fetch|2fa.*fetch/i.test(desk)) fail('OptionsDesk.tsx must not reference order, preflight or 2FA routes')

if (failed) { console.error(`optionsDesk.view: ${failed} failure(s)`); process.exit(1) }
console.log(`optionsDesk.view: ok (${literals} literal glossary keys)`)
