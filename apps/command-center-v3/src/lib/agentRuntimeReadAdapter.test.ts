// Pure-logic tests for agentRuntimeReadAdapter.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/agentRuntimeReadAdapter.test.ts
// No test framework required (the repo has none). fetch is injected, so this runs headlessly and
// proves every explicit fallback state: FIXTURE, NOT_CONNECTED, UNAVAILABLE, STALE, SHADOW.
import { resolveAgentRuntimeView, readApiBaseFromEnv, type ReadApiConfig } from './agentRuntimeReadAdapter.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const NOW = Date.parse('2026-07-26T12:00:00Z')
const now = () => NOW

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response
}

function listing(rows: Array<Record<string, unknown>>, extra: Record<string, unknown> = {}) {
  return { contract: 'agent-runtime-command-center-read-api-v1', read_only: true, kind: 'runs', data: rows,
    authority: { mutation: false, provider_call: false, service_control: false, schedule_change: false, financial_action: false }, ...extra }
}

async function run() {
  // FIXTURE — only on an explicit null baseUrl
  {
    const view = await resolveAgentRuntimeView({ baseUrl: null, now })
    check('FIXTURE when baseUrl is explicitly null', view.state === 'FIXTURE' && !view.live && view.snapshot.source === 'FIXTURE')
  }

  // SAME-ORIGIN default — unset env yields '' and the adapter fetches the same-origin path
  {
    check('readApiBaseFromEnv unset => same-origin ""', readApiBaseFromEnv({}) === '')
    let fetchedUrl = ''
    const rows = [{ status: 'COMPLETED', environment: 'SHADOW', updated_at: '2026-07-26T11:59:00Z' }]
    const fetchImpl = (async (url: string) => { fetchedUrl = url; return jsonResponse(200, listing(rows)) }) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: readApiBaseFromEnv({}), now, fetchImpl })
    check('same-origin fetch path', fetchedUrl === '/api/v3/agent-runtime/runs?limit=200')
    check('SHADOW live on same-origin', view.state === 'SHADOW' && view.live)
  }

  // NOT_CONNECTED — API reachable but reader adapter not wired (503)
  {
    const fetchImpl = (async () => jsonResponse(503, { adapterState: 'NOT_CONNECTED' })) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl })
    check('NOT_CONNECTED on HTTP 503', view.state === 'NOT_CONNECTED' && !view.live && view.snapshot.adapterState === 'FIXTURE_ONLY')
  }

  // UNAVAILABLE — network throw
  {
    const fetchImpl = (async () => { throw new Error('ECONNREFUSED') }) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl })
    check('UNAVAILABLE on fetch throw', view.state === 'UNAVAILABLE' && !view.live)
  }

  // UNAVAILABLE — response advertises authority (defense in depth)
  {
    const bad = listing([{ status: 'RUNNING' }], { authority: { mutation: true } })
    const fetchImpl = (async () => jsonResponse(200, bad)) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl })
    check('UNAVAILABLE when authority is non-zero', view.state === 'UNAVAILABLE' && !view.live)
  }

  // UNAVAILABLE — not a read-only listing
  {
    const fetchImpl = (async () => jsonResponse(200, { read_only: false })) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl })
    check('UNAVAILABLE when not read_only', view.state === 'UNAVAILABLE')
  }

  // SHADOW — fresh live read-only data
  {
    const rows = [
      { status: 'RUNNING', environment: 'SHADOW', updated_at: '2026-07-26T11:59:00Z' },
      { status: 'FAILED', environment: 'SHADOW', updated_at: '2026-07-26T11:58:00Z' },
      { status: 'COMPLETED', environment: 'SHADOW', updated_at: '2026-07-26T11:57:00Z' },
    ]
    const fetchImpl = (async () => jsonResponse(200, listing(rows))) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl })
    check('SHADOW on fresh live data', view.state === 'SHADOW' && view.live && view.snapshot.adapterState === 'CONNECTED_READ_ONLY')
    check('SHADOW run counts', view.snapshot.runs.total === 3 && view.snapshot.runs.running === 1 && view.snapshot.runs.failed === 1)
    check('SHADOW not stale', view.snapshot.runs.stale === 0)
  }

  // STALE — live data older than the freshness budget
  {
    const rows = [{ status: 'RUNNING', environment: 'SHADOW', updated_at: '2026-07-26T10:00:00Z' }]
    const fetchImpl = (async () => jsonResponse(200, listing(rows))) as unknown as typeof fetch
    const view = await resolveAgentRuntimeView({ baseUrl: 'http://x', now, fetchImpl, staleAfterMs: 5 * 60 * 1000 })
    check('STALE when data older than budget', view.state === 'STALE' && view.live && view.snapshot.runs.stale === 1)
  }

  // env helper
  {
    check('readApiBaseFromEnv unset => same-origin ""', readApiBaseFromEnv({}) === '')
    check('readApiBaseFromEnv trims trailing slash', readApiBaseFromEnv({ VITE_AGENT_RUNTIME_API_BASE: 'http://h/ ' }) === 'http://h')
  }

  console.log(`\n${pass} passed, ${fail} failed`)
  if (fail > 0) process.exit(1)
}

run()
