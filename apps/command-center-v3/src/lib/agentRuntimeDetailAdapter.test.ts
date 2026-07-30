// Pure-logic tests for agentRuntimeDetailAdapter.ts (Node 22 type-stripping):
//   node apps/command-center-v3/src/lib/agentRuntimeDetailAdapter.test.ts
// fetch is injected; proves role attribution, _shadow normalization, __run_event__
// exclusion, knowledge aggregation, and fail-closed behaviour.
import { resolveAgentRuntimeDetail, normalizeAgentId } from './agentRuntimeDetailAdapter.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

function ok(kind: string, data: unknown) {
  return { ok: true, status: 200, json: async () => ({ read_only: true, kind, data,
    authority: { mutation: false, provider_call: false, service_control: false, schedule_change: false, financial_action: false } }) } as unknown as Response
}

// Real LAB shape: watch_producer_shadow produced 3 artifacts (+1 internal run-event),
// sentinel_shadow reviewed them, darwin_shadow scored them.
function labFetch(overrides: Record<string, unknown> = {}): typeof fetch {
  const arts = [
    { artifact_id: 'a1', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h1' },
    { artifact_id: 'a2', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h2' },
    { artifact_id: 'a3', producer_agent_id: 'watch_producer_shadow', artifact_type: 'watch_review', payload_hash: 'h3' },
    { artifact_id: 'ev', producer_agent_id: '__runtime__', artifact_type: '__run_event__', payload_hash: 'hz' },
  ]
  const reviews = [
    { artifact_id: 'a1', reviewer_agent_id: 'sentinel_shadow', verdict: 'PASS' },
    { artifact_id: 'a2', reviewer_agent_id: 'sentinel_shadow', verdict: 'QUARANTINE' },
    { artifact_id: 'a3', reviewer_agent_id: 'sentinel_shadow', verdict: 'PASS' },
  ]
  const scores = [
    { artifact_id: 'a1', scorer_agent_id: 'darwin_shadow' },
    { artifact_id: 'a2', scorer_agent_id: 'darwin_shadow' },
  ]
  const map: Record<string, unknown> = {
    '/api/v3/agent-runtime/runs?limit=200': ok('runs', [{ run_id: 'r1', agent_id: 'watch_producer_shadow', status: 'COMPLETED', updated_at: '2026-07-27T11:00:00Z' }]),
    '/api/v3/agent-runtime/runs/r1/artifacts': ok('artifacts', arts),
    '/api/v3/agent-runtime/runs/r1/reviews': ok('reviews', reviews),
    '/api/v3/agent-runtime/runs/r1/scores': ok('scores', scores),
    '/api/v3/agent-runtime/knowledge/lessons?limit=200': ok('lessons', [{ lifecycle: 'CANDIDATE' }, { lifecycle: 'CANDIDATE' }, { lifecycle: 'RATIFIED' }]),
    '/api/v3/agent-runtime/knowledge/cases?limit=200': ok('cases', [{ case_type: 'known_bad_fixture' }]),
    ...overrides,
  }
  return (async (url: string) => (map[url] ?? ok('empty', []))) as unknown as typeof fetch
}

async function run() {
  check('normalizeAgentId strips _shadow', normalizeAgentId('sentinel_shadow') === 'sentinel')
  check('normalizeAgentId leaves canonical', normalizeAgentId('sentinel') === 'sentinel')

  // sentinel = reviewer: 3 reviewed, verdict spread, __run_event__ excluded
  {
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl: labFetch() })
    check('sentinel live', v.live && v.role === 'reviewer')
    check('sentinel reviewed 3 (run-event excluded)', v.counts.reviewed === 3 && v.artifacts.length === 3)
    check('sentinel verdict spread', v.counts.byVerdict.PASS === 2 && v.counts.byVerdict.QUARANTINE === 1)
    check('sentinel produced/scored 0', v.counts.produced === 0 && v.counts.scored === 0)
    check('knowledge aggregated', v.lessons.total === 3 && v.lessons.byLifecycle.CANDIDATE === 2 && v.cases.total === 1)
    check('run attributed', v.runs.length === 1 && v.runs[0].status === 'COMPLETED')
  }

  // darwin = scorer: 2 scored
  {
    const v = await resolveAgentRuntimeDetail('darwin', { baseUrl: '', fetchImpl: labFetch() })
    check('darwin scorer, scored 2', v.role === 'scorer' && v.counts.scored === 2 && v.counts.reviewed === 0)
  }

  // an agent with no engagement -> live but empty, invents nothing
  {
    const v = await resolveAgentRuntimeDetail('iris', { baseUrl: '', fetchImpl: labFetch() })
    check('iris live-but-empty', v.live && v.role === 'none' && v.artifacts.length === 0 && v.runs.length === 0)
  }

  // fail-closed: runs endpoint unreachable
  {
    const fetchImpl = (async () => { throw new Error('ECONNREFUSED') }) as unknown as typeof fetch
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl })
    check('fail-closed on unreachable', !v.live && v.artifacts.length === 0)
  }

  // defense-in-depth: a surface advertising authority is refused
  {
    const bad = { ok: true, status: 200, json: async () => ({ read_only: true, data: [], authority: { mutation: true } }) } as unknown as Response
    const v = await resolveAgentRuntimeDetail('sentinel', { baseUrl: '', fetchImpl: labFetch({ '/api/v3/agent-runtime/runs?limit=200': bad }) })
    check('refuses non-zero authority', !v.live)
  }

  console.log(`\n${pass} passed, ${fail} failed`)
  if (fail > 0) process.exit(1)
}
run()
