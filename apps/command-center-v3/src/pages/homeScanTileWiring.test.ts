// LQ-20261113-3100 (A06): the Home "Latest scan" tile and the header Setups tile pass the payload's top-level run health
// into renderSetupCounts and do not draw unknown run health as success. Source pins; the logic is in homeSetupsCatalyst.test.ts.

// Same pattern as intelConsolidation.test.ts: node's fs through process.getBuiltinModule, so the file type-checks
// without @types/node and needs no tsconfig exclude. readFileSync takes the URL directly (no node:url import).
declare const process: { exit(code?: number): never; getBuiltinModule(id: 'node:fs'): { readFileSync(p: URL, enc: 'utf8'): string } }
const readFileSync = process.getBuiltinModule('node:fs').readFileSync
let fail = 0
function check(name: string, cond: boolean) { console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${name}`); if (!cond) fail++ }
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const home = read('./HomeDoNow.tsx')
check('HomeDoNow passes run_health_status as the fallback', /renderSetupCounts\(tradeAi\?\.setup_run_summary,[^)]*fallbackStatus:\s*tradeAi\?\.run_health_status/.test(home))
check('HomeDoNow tile tone comes from setupTileTone', /tone:\s*setupTileTone\(setup,/.test(home))
check('HomeDoNow prints the health note beside the counts', /setupHealth/.test(home) && /\$\{setupHealth/.test(home))
check('HomeDoNow gives the health note the run date (M1, no tooltip on a phone)', /runHealthNote\(setup,\s*tradeAi\?\.run_date\)/.test(home))
check('HomeDoNow no longer tones the tile from degraded/healthDegraded alone', !/scanStale \|\| setup\.degraded \|\| setup\.healthDegraded \?/.test(home))

const strip = read('../components/MetricStrip.tsx')
check('MetricStrip passes run_health_status as the fallback', /fallbackStatus:\s*tradeAi\?\.run_health_status/.test(strip))
check('MetricStrip tone treats unknown run health as a warning', /healthDegraded \|\| \(!!tradeAi && setupRun\.healthUnknown\) \? 'warn'/.test(strip))

console.log(`homeScanTileWiring.test.ts: ${fail ? 'FAILED' : 'ok'}`)
process.exit(fail ? 1 : 0)
