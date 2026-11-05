// node --experimental-strip-types src/lib/automationsSeam.test.mjs
// F1 seam (cc-deepseek-5's BLOCK at d4bc7430): the projection required 'Automations@v1' while the native producer
// emits 'N8nAutomations@v1', so every real payload rendered UNAVAILABLE — and the projection suite could not see it,
// because its fixture built the consumer's string rather than the producer's.
//
// Plain .mjs on purpose: the app's tsconfig has no Node types, so reading a source file from a .ts test fails tsc
// (the same reason reportCardText.test.mjs and healthOperatorLanguage.wiring.test.mjs are .mjs).
// This reads the Python module's own constant, so the two sides cannot drift apart again without a test saying so.
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = resolve(HERE, '../..')
const PRODUCER = resolve(APP, '../../scripts/lib/data_broker/n8n_automations.py')

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const src = readFileSync(PRODUCER, 'utf8')
const m = src.match(/^SCHEMA\s*=\s*["']([^"']+)["']/m)
check(!!m, `no SCHEMA constant found in ${PRODUCER}`)

// The projection is TypeScript; node strips types, so import the module directly and read its exported constant.
const mod = await import(pathToFileURL(join(APP, 'src/lib/automationsProjection.ts')).href)
const consumer = mod.SCHEMA
check(!!consumer, 'automationsProjection.ts does not export its schema constant')
if (m) check(consumer === m[1], `the projection requires '${consumer}' but the producer emits '${m[1]}'`)

if (failed) { console.error(`automationsSeam: ${failed} failure(s)`); process.exit(1) }
console.log(`automationsSeam: ok — both sides use '${m ? m[1] : '?'}'`)
