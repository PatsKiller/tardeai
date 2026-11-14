// Scaffold invariants, run before every build. Fails the build rather than warning.
import fs from 'fs'
import path from 'path'
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const read = p => fs.readFileSync(path.join(root, p), 'utf8')
const fail = []
const fam = read('src/routes/families.ts')
const val = read('src/contracts/valuation.ts')
const client = read('src/api/client.ts')
if (!/VALUATION_CONTRACT_VERSION = 'valuation-assessment@1'/.test(val)) fail.push('valuation contract version missing')
for (const s of ['UNASSESSED', 'N_M', 'N_A', 'FUND_METRIC', 'PE_TRAILING', 'PE_FORWARD', 'OWN_HISTORY', 'INDUSTRY_PEERS', 'SECTOR_PEERS'])
  if (!val.includes(`'${s}'`)) fail.push(`valuation contract lacks ${s}`)
if (/cheap|buy_signal|threshold\s*[:=]\s*\d/i.test(val.replace(/\/\/.*$/gm, ''))) fail.push('valuation contract encodes a cutoff or buy signal')
if (/method:\s*'(POST|PUT|PATCH|DELETE)'/.test(client)) fail.push('wealth client issues a write method')
if (/token|authorization/i.test(client.replace(/\/\/.*$/gm, ''))) fail.push('wealth client handles credentials')
for (const m of fam.matchAll(/'(\/api\/v[23]\/[^']+)'/g)) if (!m[1].startsWith('/api/')) fail.push(`bad reader ${m[1]}`)
const srcFiles = []
const walk = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p) : srcFiles.push(p) } }
walk(path.join(root, 'src'))
for (const f of srcFiles) if (/command-center-v3/.test(fs.readFileSync(f, 'utf8'))) fail.push(`${path.relative(root, f)} imports from command-center-v3`)
if (fail.length) { console.error('check-contracts FAIL\n- ' + fail.join('\n- ')); process.exit(1) }
console.log(`check-contracts PASS (${srcFiles.length} src files)`)
