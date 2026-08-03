/**
 * Lightweight browser-facing contract checks for /v3/consumption DeepSeek path.
 * Asserts built UI source + API contracts without paid calls.
 * Run: node tests/e2e_consumption_deepseek_contract.mjs
 */
import { readFileSync, existsSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const hub = readFileSync(join(root, 'apps/command-center-v3/src/pages/ConsumptionHub.tsx'), 'utf8')
const oauth = readFileSync(join(root, 'apps/command-center-v3/src/hooks/useOAuthLanes.ts'), 'utf8')
const cloud = readFileSync(join(root, 'apps/command-center-v3/src/lib/cloudLlmRun.ts'), 'utf8')
const watch = readFileSync(join(root, 'apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx'), 'utf8')
const api = readFileSync(join(root, 'scripts/api_v2.py'), 'utf8')
const metaPath = join(root, 'apps/command-center-v3/dist/build-meta.json')

const fails = []
function ok(cond, msg) {
  if (!cond) fails.push(msg)
  else console.log('OK', msg)
}

ok(hub.includes('LLM Consumption'), 'route heading LLM Consumption present')
ok(hub.includes('DeepSeek V4 Pro'), 'Pro card labeled DeepSeek V4 Pro')
ok(hub.includes('Test V4 Flash'), 'Test V4 Flash button present')
ok(hub.includes('deepseek_flash_operator_smoke'), 'Flash smoke uses dedicated process id')
ok(!hub.includes("process_id: 'oauth_lane_keepalive'") || hub.includes('deepseek_flash_operator_smoke'), 'smoke not oauth_lane_keepalive for deepseek')
ok(hub.includes('disabled={!!busy || !Boolean(oauth.deepseek_flash'), 'Flash test disabled when offline')
ok(hub.includes('failToday') || hub.includes('failures'), 'aggregates surface failures')
ok(hub.includes('DeepSeek V4 Pro'), 'Pro card labeled DeepSeek V4 Pro')
ok(oauth.includes("byLane('deepseek-flash')"), 'useOAuthLanes looks up deepseek-flash')
ok(oauth.includes('reason_code'), 'readiness reason_code supported')
ok(cloud.includes("fetch('/api/v2/consumption/run-manual'"), 'cloudLlmRun posts run-manual')
ok(cloud.includes('returned_model'), 'ManualCloudResult includes returned_model')
ok(!/operator_confirmed\s*:/.test(cloud) && !cloud.includes('operator_confirmed:'), 'cloudLlmRun body omits operator_confirmed field')
ok(cloud.includes('Never send operator_confirmed') || !cloud.includes('operator_confirmed='), 'no Pro confirm flag wired for generic manual')
ok(watch.includes('RUN ALL FREE') || watch.includes('Free critics only'), 'RUN ALL FREE free ensemble contract')
ok(api.includes('classify_manual_lane'), 'backend uses classify_manual_lane')
ok(api.includes('deepseek_readiness_rows'), 'oauth-lanes includes deepseek readiness')
ok(api.includes('PROCESS_NOT_REGISTERED') || api.includes('is_process_registered'), 'process registration fail-closed')
ok(api.includes('POLICY_NOT_ALLOWED') || api.includes('process_allows_policy'), 'policy allowlist enforced')

if (existsSync(metaPath)) {
  const meta = JSON.parse(readFileSync(metaPath, 'utf8'))
  ok(Boolean(meta.ui_version || meta.built_at), `build-meta present ui_version=${meta.ui_version}`)
  console.log('build-meta', meta)
} else {
  console.log('NOTE build-meta.json not present until npm run build')
}

// Live API (read-only) if server is up
try {
  const r = await fetch('http://127.0.0.1:7777/api/v2/llm/oauth-lanes')
  if (r.ok) {
    const j = await r.json()
    const lanes = (j?.data ?? j)?.lanes || []
    // Live production may not have this fix yet — only note
    const hasDs = lanes.some(l => l.lane === 'deepseek-flash')
    console.log('LIVE oauth-lanes deepseek-flash present?', hasDs, '(expected false until deploy)')
  }
} catch {
  console.log('LIVE server probe skipped')
}

if (fails.length) {
  console.error('FAIL', fails)
  process.exit(1)
}
console.log('ALL e2e_consumption_deepseek_contract checks passed')
