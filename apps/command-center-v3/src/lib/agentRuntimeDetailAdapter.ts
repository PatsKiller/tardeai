// Live per-agent detail for the Runtime desks (Run timeline, Artifact review desk,
// Knowledge). Read-only, same-origin, fail-closed. Attributes evidence by governed
// ROLE (produced / reviewed / scored) and normalizes deployment-suffixed ids
// (sentinel_shadow -> sentinel), mirroring the maturity bridge. Internal
// __run_event__ journal rows are excluded — they are not reviewable artifacts.
//
// Cost (2026-11-07, LQ-20261107-90): the desk used to issue one request per run per
// evidence kind for the newest fifty runs — 150 requests at 4-5 s apiece, re-issued on
// every agent selection, against a server near its memory ceiling. It now issues ONE:
// `/api/v3/agent-runtime/evidence?limit=50`. The per-run fan-out is deleted, not kept as
// a fallback (operator 2026-11-07, remove-the-old-code) — the desk and the read API ship
// together, so a batch that cannot be read means the desk has no evidence it can trust.

type Row = Record<string, unknown>

export interface JoinedArtifact {
  artifactId: string
  producer: string
  artifactType: string
  payloadHash: string
  reviewer?: string
  verdict?: string
  scorer?: string
  createdAt?: string
}

export interface AgentDetailView {
  live: boolean
  agentId: string
  role: 'producer' | 'reviewer' | 'scorer' | 'mixed' | 'none'
  runs: Array<{ runId: string; status: string; updatedAt: string }>
  artifacts: JoinedArtifact[]
  lastRunAt: string | null
  lastArtifactAt: string | null
  retrievalCount: number | null
  counts: { produced: number; reviewed: number; scored: number; byVerdict: Record<string, number> }
  lessons: { total: number; byLifecycle: Record<string, number> }
  cases: { total: number; byType: Record<string, number> }
  detail: string
}

// The newest runs the desk shows, in ONE request.
const RUN_LIMIT = 50
const BATCH_PATH = '/api/v3/agent-runtime/evidence'

// One run with the three row sets the desk joins it with, however they were fetched.
interface RunEvidence {
  run: Row
  artifacts: Row[]
  reviews: Row[]
  scores: Row[]
}

const SUFFIX = /_(shadow|lab)$/i
export function normalizeAgentId(raw: unknown): string {
  return String(raw ?? '').trim().replace(SUFFIX, '')
}

function emptyView(agentId: string, live: boolean, detail: string): AgentDetailView {
  return {
    live, agentId, role: 'none', runs: [], artifacts: [],
    lastRunAt: null, lastArtifactAt: null, retrievalCount: null,
    counts: { produced: 0, reviewed: 0, scored: 0, byVerdict: {} },
    lessons: { total: 0, byLifecycle: {} }, cases: { total: 0, byType: {} }, detail,
  }
}

// One read-only GET. null means the request never produced a response at all.
async function fetchRead(
  baseUrl: string, path: string, fetchImpl: typeof fetch,
): Promise<{ ok: boolean; body: unknown } | null> {
  let resp: Response
  try {
    resp = await fetchImpl(`${baseUrl}${path}`, { method: 'GET', headers: { accept: 'application/json' } })
  } catch {
    return null
  }
  let body: unknown = null
  try { body = await resp.json() } catch { body = null }
  return { ok: resp.ok, body }
}

// The read surface's own envelope. undefined means "do not trust this response": not
// read-only, or a surface advertising any authority.
function readOnlyData(body: unknown): unknown {
  const p = body as { read_only?: boolean; authority?: Record<string, boolean>; data?: unknown } | null
  if (p?.read_only !== true) return undefined
  if (p.authority && Object.values(p.authority).some(Boolean)) return undefined
  return p.data
}

function asRows(value: unknown): Row[] {
  return Array.isArray(value) ? (value as Row[]) : []
}

// Fetch a read-only listing; null on any failure or a surface that advertises authority.
async function getRows(baseUrl: string, path: string, fetchImpl: typeof fetch): Promise<Row[] | null> {
  const resp = await fetchRead(baseUrl, path, fetchImpl)
  if (!resp || !resp.ok) return null
  const data = readOnlyData(resp.body)
  if (data === undefined) return null
  return asRows(data)
}

// The whole fleet slice in ONE request, or an honest reason the desk has nothing to show.
//
// There is no per-run fallback: the old 1 + 3*N fan-out is deleted, not retained behind a
// probe (operator 2026-11-07, remove-the-old-code). A release ships the desk and the read
// API together, so a desk that cannot get the batch has no trustworthy evidence to join —
// and re-creating the 150-request path as a "compatibility" branch would revive the very
// load the fix exists to remove. It fails closed and says which failure it was.
async function readRunEvidence(
  baseUrl: string, fetchImpl: typeof fetch,
): Promise<{ evidence: RunEvidence[] } | { detail: string }> {
  const notConnected = { detail: 'Read API not connected.' }
  const resp = await fetchRead(baseUrl, `${BATCH_PATH}?limit=${RUN_LIMIT}`, fetchImpl)
  if (!resp || !resp.ok) return notConnected
  // Not read-only, or a surface advertising authority: the desk treats it as unreachable.
  const data = readOnlyData(resp.body) as { runs?: unknown; evidence?: unknown } | undefined
  if (data === undefined || typeof data !== 'object' || data === null) return notConnected
  const unusable = {
    detail: 'Read API answered without usable run evidence; the desk shows nothing rather than a partial board.',
  }
  if (!Array.isArray(data.runs)) return unusable
  const evidence = data.evidence
  if (typeof evidence !== 'object' || evidence === null || Array.isArray(evidence)) return unusable
  const grouped = evidence as Record<string, { artifacts?: unknown; reviews?: unknown; scores?: unknown } | null>
  const out: RunEvidence[] = []
  for (const run of data.runs as Row[]) {
    const runId = String(run?.run_id ?? '')
    if (!runId) continue
    // A named run with no evidence entry is an incomplete answer, not "this run produced
    // nothing" — rendering it as an empty row would invent a zero.
    const entry = grouped[runId]
    if (typeof entry !== 'object' || entry === null) return unusable
    out.push({ run, artifacts: asRows(entry.artifacts), reviews: asRows(entry.reviews), scores: asRows(entry.scores) })
  }
  return { evidence: out }
}

export async function resolveAgentRuntimeDetail(
  agentId: string,
  config: { baseUrl?: string; fetchImpl?: typeof fetch } = {},
): Promise<AgentDetailView> {
  const baseUrl = config.baseUrl ?? ''
  const fetchImpl = config.fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!fetchImpl) return emptyView(agentId, false, 'No fetch implementation available.')

  const read = await readRunEvidence(baseUrl, fetchImpl)
  if (!('evidence' in read)) return emptyView(agentId, false, read.detail)
  const evidence = read.evidence

  const artifactById = new Map<string, JoinedArtifact>()
  const engaged = new Set<string>()
  const runInfo: AgentDetailView['runs'] = []
  let lastRunAt: string | null = null
  let retrievalCount = 0
  let sawRetrievalCount = false

  for (const { run, artifacts, reviews, scores } of evidence) {
    const runId = String(run.run_id ?? '')
    let touched = normalizeAgentId(run.agent_id) === agentId
    if (touched) {
      const runAt = String(run.updated_at ?? run.started_at ?? '')
      if (runAt && (!lastRunAt || runAt > lastRunAt)) lastRunAt = runAt
      if (run.retrieval_count !== undefined && run.retrieval_count !== null) {
        retrievalCount += Number(run.retrieval_count) || 0
        sawRetrievalCount = true
      }
    }
    for (const a of artifacts) {
      const aid = String(a.artifact_id ?? '')
      if (!aid || String(a.artifact_type ?? '') === '__run_event__') continue
      const producer = normalizeAgentId(a.producer_agent_id)
      artifactById.set(aid, {
        artifactId: aid, producer, artifactType: String(a.artifact_type ?? ''),
        payloadHash: String(a.payload_hash ?? ''), createdAt: String(a.created_at ?? ''),
      })
      if (producer === agentId) { engaged.add(aid); touched = true }
    }
    for (const r of reviews) {
      const aid = String(r.artifact_id ?? '')
      const j = artifactById.get(aid)
      const reviewer = normalizeAgentId(r.reviewer_agent_id)
      if (j) { j.reviewer = reviewer; j.verdict = String(r.verdict ?? '') }
      if (reviewer === agentId) { engaged.add(aid); touched = true }
    }
    for (const s of scores) {
      const aid = String(s.artifact_id ?? '')
      const j = artifactById.get(aid)
      const scorer = normalizeAgentId(s.scorer_agent_id)
      if (j) j.scorer = scorer
      if (scorer === agentId) { engaged.add(aid); touched = true }
    }
    if (touched) runInfo.push({ runId, status: String(run.status ?? ''), updatedAt: String(run.updated_at ?? run.started_at ?? '') })
  }

  const mine: JoinedArtifact[] = []
  let produced = 0, reviewed = 0, scored = 0
  const byVerdict: Record<string, number> = {}
  for (const aid of engaged) {
    const a = artifactById.get(aid)
    if (!a) continue
    mine.push(a)
    if (a.producer === agentId) produced++
    if (a.reviewer === agentId) { reviewed++; if (a.verdict) byVerdict[a.verdict] = (byVerdict[a.verdict] ?? 0) + 1 }
    if (a.scorer === agentId) scored++
  }
  const role: AgentDetailView['role'] =
    produced && (reviewed || scored) ? 'mixed' : reviewed ? 'reviewer' : scored ? 'scorer' : produced ? 'producer' : 'none'

  const lessonRows = (await getRows(baseUrl, '/api/v3/agent-runtime/knowledge/lessons?limit=200', fetchImpl)) ?? []
  const caseRows = (await getRows(baseUrl, '/api/v3/agent-runtime/knowledge/cases?limit=200', fetchImpl)) ?? []
  const byLifecycle: Record<string, number> = {}
  for (const l of lessonRows) { const k = String(l.lifecycle ?? 'UNKNOWN'); byLifecycle[k] = (byLifecycle[k] ?? 0) + 1 }
  const byType: Record<string, number> = {}
  for (const c of caseRows) { const k = String(c.case_type ?? 'UNKNOWN'); byType[k] = (byType[k] ?? 0) + 1 }

  const artifactTimes = mine.map(a => a.createdAt || '').filter(Boolean).sort()
  const lastArtifactAt = artifactTimes.length > 0 ? artifactTimes[artifactTimes.length - 1] : null

  return {
    live: true, agentId, role,
    runs: runInfo,
    artifacts: mine.slice(0, 40),
    lastRunAt,
    lastArtifactAt,
    retrievalCount: sawRetrievalCount ? retrievalCount : null,
    counts: { produced, reviewed, scored, byVerdict },
    lessons: { total: lessonRows.length, byLifecycle },
    cases: { total: caseRows.length, byType },
    detail: 'Live read-only detail from the agent-runtime read API.',
  }
}
