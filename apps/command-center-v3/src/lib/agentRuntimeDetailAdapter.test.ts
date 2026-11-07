// Pure-logic tests for agentRuntimeDetailAdapter.ts (Node 22 type-stripping):
//   node apps/command-center-v3/src/lib/agentRuntimeDetailAdapter.test.ts
// fetch is injected; proves role attribution, _shadow normalization, __run_event__
// exclusion, knowledge aggregation, and fail-closed behaviour.
//
// 2026-11-07 (LQ-20261107-90): also proves the request COUNT. The desk used to issue
// 1 + 3*50 + 2 = 153 requests per load; it now issues 3 (batch, lessons, cases). The
// per-run fan-out is DELETED, not kept as a fallback (operator 2026-11-07,
// remove-the-old-code): the desk and the read API ship in the same release, so a batch
// that cannot be read leaves the desk with nothing it can trust — and it says so after
// ONE request instead of re-creating the fan-out it exists to remove.
import { resolveAgentRuntimeDetail, normalizeAgentId } from './agentRuntimeDetailAdapter.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const ZERO = { mutation: false, provider_call: false, service_control: false, schedule_change: false, financial_action: false }

function ok(kind: string, data: unknown) {
  return { ok: true, status: 200, json: async () => ({ read_only: true, kind, data, authority: { ...ZERO } }) } as unknown as Response
}

function envelope(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response
}

function missing() {
  return { ok: false, status: 404, json: async () => ({ detail: 'no such agent-runtime read route' }) } as unknown as Response
}

// Real LAB shape: watch_producer_shadow produced 3 artifacts (+1 internal run-event),
// sentinel_shadow reviewed them, darwin_shadow scored them.
const ARTS = [
  { artifact_id: 'a1', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h1' },
  { artifact_id: 'a2', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h2' },
  { artifact_id: 'a3', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h3' },
  { artifact_id: 'ev', producer_agent_id: '__runtime__', artifact_type: '__run_event__', payload_hash: 'hz' },
]
const REVIEWS = [
  { artifact_id: 'a1', reviewer_agent_id: 'sentinel_shadow', verdict: 'PASS' },
  { artifact_id: 'a2', reviewer_agent_id: 'sentinel_shadow', verdict: 'QUARANTINE' },
  { artifact_id: 'a3', reviewer_agent_id: 'sentinel_shadow', verdict: 'PASS' },
]
const SCORES = [
  { artifact_id: 'a1', scorer_agent_id: 'darwin_shadow' },
  { artifact_id: 'a2', scorer_agent_id: 'darwin_shadow' },
]
const LAB_RUN = { run_id: 'r1', agent_id: 'watch_producer_shadow', status: 'COMPLETED', updated_at: '2026-07-27T11:00:00Z' }
const BATCH_URL = '/api/v3/agent-runtime/evidence?limit=50'

// The same evidence, one batch request.
function batchFetch(overrides: Record<string, unknown> = {}): typeof fetch {
  const payload = {
    read_only: true, kind: 'run_evidence_batch', authority: { ...ZERO },
    data: {
      runs: [{ ...LAB_RUN }],
      evidence: { r1: { artifacts: ARTS, reviews: REVIEWS, scores: SCORES } },
    },
  }
  const map: Record<string, unknown> = {
    [BATCH_URL]: envelope(payload),
    '/api/v3/agent-runtime/knowledge/lessons?limit=200': ok('lessons', [{ lifecycle: 'CANDIDATE' }, { lifecycle: 'CANDIDATE' }, { lifecycle: 'RATIFIED' }]),
    '/api/v3/agent-runtime/knowledge/cases?limit=200': ok('cases', [{ case_type: 'known_bad_fixture' }]),
    ...overrides,
  }
  return (async (url: string) => (map[url] ?? ok('empty', []))) as unknown as typeof fetch
}

// Wraps a fetch so every requested URL is recorded — the request count is the point.
function counting(inner: typeof fetch): { impl: typeof fetch; urls: string[] } {
  const urls: string[] = []
  const impl = (async (url: string, init?: RequestInit) => { urls.push(url); return inner(url, init) }) as unknown as typeof fetch
  return { impl, urls }
}

async function run() {
  check('normalizeAgentId strips _shadow', normalizeAgentId('sentinel_shadow') === 'sentinel')
  check('normalizeAgentId leaves canonical', normalizeAgentId('sentinel') === 'sentinel')

  // sentinel = reviewer: 3 reviewed, verdict spread, __run_event__ excluded (batch path)
  {
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl: batchFetch() })
    check('sentinel live', v.live && v.role === 'reviewer')
    check('sentinel reviewed 3 (run-event excluded)', v.counts.reviewed === 3 && v.artifacts.length === 3)
    check('sentinel verdict spread', v.counts.byVerdict.PASS === 2 && v.counts.byVerdict.QUARANTINE === 1)
    check('sentinel produced/scored 0', v.counts.produced === 0 && v.counts.scored === 0)
    check('knowledge aggregated', v.lessons.total === 3 && v.lessons.byLifecycle.CANDIDATE === 2 && v.cases.total === 1)
    check('run attributed', v.runs.length === 1 && v.runs[0].status === 'COMPLETED')
  }

  // darwin = scorer: 2 scored (batch path)
  {
    const v = await resolveAgentRuntimeDetail('darwin', { baseUrl: '', fetchImpl: batchFetch() })
    check('darwin scorer, scored 2', v.role === 'scorer' && v.counts.scored === 2 && v.counts.reviewed === 0)
  }

  // an agent with no engagement -> live but empty, invents nothing (batch path)
  {
    const v = await resolveAgentRuntimeDetail('iris', { baseUrl: '', fetchImpl: batchFetch() })
    check('iris live-but-empty', v.live && v.role === 'none' && v.artifacts.length === 0 && v.runs.length === 0)
  }

  // ---- the request count: 153 before, 3 now --------------------------------
  {
    const batch = counting(batchFetch())
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl: batch.impl })
    check('batch: three requests for a whole load', batch.urls.length === 3)
    check('batch: the one fleet read is the evidence endpoint', batch.urls[0] === BATCH_URL)
    check('batch: no per-run request', !batch.urls.some(u => /\/runs\/[^/]+\/(artifacts|reviews|scores)$/.test(u)))
    check('batch: no separate run listing', !batch.urls.some(u => u.includes('/runs?limit=')))
    check('batch: detail claims no fallback', v.live && !v.detail.includes('fallback'))
  }

  // The fan-out is GONE, not kept behind a probe: a release that cannot answer the batch
  // leaves the desk with nothing it can trust, and re-creating the 150-request path to
  // cover that would revive the load the fix exists to remove.
  {
    const runs = Array.from({ length: 50 }, (_, i) => ({
      run_id: `r${i}`, agent_id: 'watch_producer_shadow', status: 'COMPLETED', updated_at: `2026-07-27T11:${String(i).padStart(2, '0')}:00Z`,
    }))
    const map: Record<string, unknown> = {
      '/api/v3/agent-runtime/runs?limit=200': ok('runs', runs),
      [BATCH_URL]: missing(),
      '/api/v3/agent-runtime/knowledge/lessons?limit=200': ok('lessons', []),
      '/api/v3/agent-runtime/knowledge/cases?limit=200': ok('cases', []),
    }
    const gone = counting((async (url: string) => (map[url] ?? ok('empty', []))) as unknown as typeof fetch)
    const v = await resolveAgentRuntimeDetail('watch_producer', { baseUrl: '', fetchImpl: gone.impl })
    check('no fallback: a missing batch ends the load at one request', gone.urls.length === 1)
    check('no fallback: that request is the batch', gone.urls[0] === BATCH_URL)
    check('no fallback: not one per-run child request', !gone.urls.some(u => /\/runs\/[^/]+\/(artifacts|reviews|scores)$/.test(u)))
    check('no fallback: the desk says it has nothing', !v.live && v.artifacts.length === 0 && v.runs.length === 0)
  }

  // An incomplete batch (a named run with no evidence entry) is not "no evidence": it is an
  // answer the desk cannot trust, so it shows nothing rather than an invented zero.
  {
    const partial = envelope({
      read_only: true, authority: { ...ZERO },
      data: { runs: [{ ...LAB_RUN }], evidence: {} },
    })
    const f = counting(batchFetch({ [BATCH_URL]: partial }))
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl: f.impl })
    check('incomplete batch: one request, no per-run retry', f.urls.length === 1)
    check('incomplete batch: fails closed instead of zeroing', !v.live && v.artifacts.length === 0)
    check('incomplete batch: the reason is stated', v.detail.includes('usable run evidence'))
  }

  // A batch response advertising authority is refused.
  {
    const bad = envelope({ read_only: true, authority: { mutation: true }, data: { runs: [LAB_RUN], evidence: { r1: {} } } })
    const v = await resolveAgentRuntimeDetail('sentinel', {
      baseUrl: '', fetchImpl: batchFetch({ [BATCH_URL]: bad }),
    })
    check('refuses non-zero authority', !v.live)
  }

  // fail-closed: nothing reachable at all
  {
    const fetchImpl = (async () => { throw new Error('ECONNREFUSED') }) as unknown as typeof fetch
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl })
    check('fail-closed on unreachable', !v.live && v.artifacts.length === 0)
  }

  console.log(`\n${pass} passed, ${fail} failed`)
  if (fail > 0) process.exit(1)
}
run()
