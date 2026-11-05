// FQ-030 / FQ-031 (/consumption): a phone page led by spend and failed calls, with the process
// registry and call log collapsed; internal identifiers stay one disclosure away.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/consumptionPresentation.test.ts
import {
  DESK_LOG_PREVIEW, DESK_PROCESS_PREVIEW, PHONE_LOG_PREVIEW, PHONE_PROCESS_PREVIEW,
  activityCensus, callDetailText, callPrimaryText, failedCalls, hiddenLabel, isOpaqueId, previewRows, readableSummary,
} from './consumptionPresentation.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, got === want, got)

const log = (id: number, success: boolean, extra: Record<string, unknown> = {}) => ({
  id, created_at: '2026-11-04T10:20:13-05:00', model_lane: 'deepseek-flash',
  process_id: 'local_llm_compat', process_name: 'Local-LLM compatibility shim (Flash)',
  task_summary: 'You are an institutional prop desk analyst. Analyze this paper trade proposal.',
  trigger_mode: 'automated', success, ...extra,
})

// --- FQ-030: the page must lead with failed calls ---------------------------------------
eq('no failures', failedCalls([log(1, true), log(2, true)]).length, 0)
eq('two failures', failedCalls([log(1, false), log(2, true), log(3, false)]).length, 2)
check('failed calls keep their order', failedCalls([log(9, false), log(4, false)]).map(l => l.id).join() === '9,4')

// --- FQ-030: registry and log collapse instead of rendering everything -------------------
eq('phone process preview is smaller than desktop', PHONE_PROCESS_PREVIEW < DESK_PROCESS_PREVIEW, true)
eq('phone log preview is smaller than desktop', PHONE_LOG_PREVIEW < DESK_LOG_PREVIEW, true)

const rows = Array.from({ length: 20 }, (_, i) => i)
const collapsed = previewRows(rows, false, 6)
eq('collapsed shows only the preview', collapsed.shown.length, 6)
eq('collapsed reports what is hidden', collapsed.hidden, 14)
eq('collapsed keeps the first rows in order', collapsed.shown.join(), '0,1,2,3,4,5')
const expanded = previewRows(rows, true, 6)
eq('expanded shows everything', expanded.shown.length, 20)
eq('expanded hides nothing', expanded.hidden, 0)
eq('a short list is never truncated', previewRows([1, 2], false, 6).hidden, 0)

// --- FQ-030: the control says how much is still hidden ----------------------------------
eq('collapsed label counts the rest', hiddenLabel('processes', 14, false), 'Show all — 14 more processes')
eq('expanded label is gone', hiddenLabel('processes', 0, true), '')
eq('nothing hidden means no control', hiddenLabel('processes', 0, false), '')

// --- FQ-031: internal identifiers become readable, and stay available for diagnosis -----
// These two raw values are real, taken from /api/v2/consumption/logs on 105df180e.
const composite = log(169102, true, {
  process_name: 'Watchlist Maria Flash Narrative',
  task_summary: 'agent_flash:agent_narrative:agent_narrative:NVDA:social_scalp_scanner',
})
const compositeLine = callPrimaryText(composite)
check('a ticker survives the rewrite', compositeLine.includes('NVDA'), compositeLine)
check('the work is described in words', compositeLine.includes('Social scalp scanner'), compositeLine)
check('the internal key is gone from the reader line', !compositeLine.includes('agent_narrative'), compositeLine)

const counts = log(169099, true, { task_summary: 'system:1557chars; system:385chars; user:18987chars' })
check('a size breakdown is not passed off as a summary', callPrimaryText(counts).includes('request text only'), callPrimaryText(counts))

// cc-deepseek-5's P3 on PR 2676: taking the LAST segment printed the ticker twice and dropped the task.
const tickerLast = readableSummary({ task_summary: 'agent_flash:agent_narrative:NVDA' })
eq('the ticker is not repeated back as a word', tickerLast, 'NVDA · Agent narrative')
const statusLast = readableSummary({ task_summary: 'cloud_review:research_up_thesis_flat:deepseek_ok' })
eq('a trailing status does not replace the task', statusLast, 'Research up thesis flat')
eq('a key with nothing but the ticker says so', readableSummary({ task_summary: 'NVDA:NVDA' }), 'No summary recorded')

const snake = log(169101, true, { task_summary: 'hermes_external_research' })
check('a bare task key is humanised', callPrimaryText(snake).includes('Hermes external research'), callPrimaryText(snake))

const row = log(169060, true)
const primary = callPrimaryText(row)
check('primary line names the process readably', primary.includes('Local-LLM compatibility shim (Flash)'), primary)
check('primary line does NOT expose the process id', !primary.includes('local_llm_compat'), primary)
check('a long request is a preview, not the whole prompt', primary.length < 200, primary.length)

const detail = callDetailText(composite)
check('detail carries the process id for diagnosis', detail.includes('local_llm_compat'), detail)
check('detail keeps the raw key the reader no longer sees', detail.includes('agent_narrative'), detail)
check('a row with no process id still yields a detail string', callDetailText(log(1, true, { process_id: '' })).length > 0)

// (the single pass/fail guard is at the end of this file — cc8's re-review, 16:24Z: an appended
// block after the old guard could print [FAIL] and still exit 0)

// --- cc-deepseek-8's F2/F3 on PR 2676 (driven on the live table) -------------------------
eq('a control directive plus a prompt is request text, not a summary',
   readableSummary({ task_summary: '/no_think Analyze stock catalyst for U and output JSON only. Headlines: - Unity Software' }),
   'No summary recorded — request text only')
eq('a prompt that only says output JSON only is request text too',
   readableSummary({ task_summary: 'Summarise this filing and output JSON only' }),
   'No summary recorded — request text only')
eq('a slash-led task key is not mistaken for a summary',
   readableSummary({ task_summary: '/compact' }), 'No summary recorded — request text only')
check('a manual trigger says so', callPrimaryText(log(1, true, { trigger_mode: 'manual' })).includes('started by you'))
check('an automated trigger says so', callPrimaryText(log(2, true)).includes('ran automatically'))
check('an unknown trigger asserts nothing', callPrimaryText(log(3, true, { trigger_mode: 'retry' })).includes('trigger not recorded'))

// ── cx-openai-3's CX3-F1: a census is only a census when the source was read ─────────────────────────
check('no data at all is not a clean window', activityCensus({ data: undefined }).state === 'unavailable')
check('an empty object is not a clean window', activityCensus({ data: {} }).state === 'unavailable')
check('a refused read is unavailable, and says why',
  activityCensus({ data: { ok: false, error: 'Synthetic source refused' } }).state === 'unavailable' &&
  String((activityCensus({ data: { ok: false, error: 'Synthetic source refused' } }) as any).reason).includes('refused'))
check('an accepted empty list IS a clean window', activityCensus({ data: { logs: [] } }).state === 'current')
check('a failing refresh over retained rows is retained, not current',
  activityCensus({ data: { logs: [{}] }, stale: true }).state === 'retained' &&
  activityCensus({ data: { logs: [{}] }, error: 'network' }).state === 'retained')
check('a healthy read with rows is current', activityCensus({ data: { logs: [{}, {}] } }).state === 'current')

// ── cx-openai-3's CX3-F2: an opaque id is an id, not a description ───────────────────────────────────
const HASH = '0123456789abcdef0123456789abcdef'
const UUID = '01234567-89ab-cdef-0123-456789abcdef'
check('a hex digest is recognised', isOpaqueId(HASH) && !isOpaqueId('Synthetic task 1'))
check('a UUID is recognised', isOpaqueId(UUID) && !isOpaqueId('Analyze the catalyst'))
check('a digest alone is not shown as a summary', readableSummary({ task_summary: HASH }) === 'No summary recorded — an identifier only')
check('a UUID alone is not shown as a summary', readableSummary({ task_summary: UUID }) === 'No summary recorded — an identifier only')
check('ordinary prose is untouched', readableSummary({ task_summary: 'Analyze the catalyst for NVDA' }).startsWith('Analyze the catalyst'))
check('a note about the 32 chars of a sentence is not mistaken for a digest',
  readableSummary({ task_summary: 'Rebuilt the watchlist and checked the 55 tickers' }).startsWith('Rebuilt the watchlist'))

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
