// Live per-agent detail for the Runtime desks (Run timeline, Artifact review desk,
// Knowledge). Read-only, same-origin, fail-closed. Attributes evidence by governed
// ROLE (produced / reviewed / scored) and normalizes deployment-suffixed ids
// (sentinel_shadow -> sentinel), mirroring the maturity bridge. Internal
// __run_event__ journal rows are excluded — they are not reviewable artifacts.

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
  severity?: string
  artifactKind?: string
  providerFamily?: string
  model?: string
  primaryFindingCode?: string
  primaryFindingVerdict?: string
  primaryLessonId?: string
}

export interface IrisLessonVerdict {
  code: string
  verdict: string
  severity?: string
  artifactId?: string
}

export interface LessonItem {
  lessonId: string
  title: string
  lifecycle: string
  statement: string
  createdAt?: string
}

export interface AgentDetailView {
  live: boolean
  agentId: string
  role: 'producer' | 'reviewer' | 'scorer' | 'mixed' | 'none'
  runs: Array<{ runId: string; status: string; startedAt: string; completedAt: string | null; updatedAt: string }>
  artifacts: JoinedArtifact[]
  counts: { produced: number; reviewed: number; scored: number; byVerdict: Record<string, number> }
  lessons: { total: number; byLifecycle: Record<string, number>; items: LessonItem[] }
  cases: { total: number; byType: Record<string, number> }
  irisLessonVerdicts: Record<string, IrisLessonVerdict>
  detail: string
}

const SUFFIX = /_(shadow|lab)$/i
export function normalizeAgentId(raw: unknown): string {
  return String(raw ?? '').trim().replace(SUFFIX, '')
}

export function irisVerdictLabel(code?: string, verdict?: string): string | null {
  const c = String(code ?? '').toLowerCase()
  if (c === 'contradiction_confirmed' || verdict === 'contradiction') return 'CONTRADICTION'
  if (c === 'duplicate_lesson' || verdict === 'duplicate') return 'DUPLICATE'
  if (c === 'support_ratification' || verdict === 'support') return 'NOVEL'
  if (c === 'classification_deferred') return 'DEFERRED'
  if (c === 'provenance_thin') return 'THIN PROVENANCE'
  return verdict ? verdict.toUpperCase() : null
}

export function severityTone(severity?: string): 'blue' | 'green' | 'amber' | 'red' | 'slate' {
  const s = String(severity ?? '').toLowerCase()
  if (s === 'critical') return 'red'
  if (s === 'high') return 'red'
  if (s === 'warning') return 'amber'
  if (s === 'info') return 'slate'
  return 'slate'
}

export function laneChipLabel(family?: string, model?: string): string {
  const f = String(family ?? '').toLowerCase()
  const m = String(model ?? '').trim()
  if (!f || f === 'deterministic' || m === 'none') return 'deterministic'
  if (f.includes('grok')) return m ? `grok/${m}` : 'grok'
  if (f.includes('chatgpt') || f.includes('openai')) return m ? `chatgpt/${m}` : 'chatgpt'
  if (f === 'local' || f.includes('ollama')) return m ? `local/${m}` : 'local/ollama'
  return m ? `${f}/${m}` : f
}

function emptyView(agentId: string, live: boolean, detail: string): AgentDetailView {
  return {
    live, agentId, role: 'none', runs: [], artifacts: [],
    counts: { produced: 0, reviewed: 0, scored: 0, byVerdict: {} },
    lessons: { total: 0, byLifecycle: {}, items: [] }, cases: { total: 0, byType: {} },
    irisLessonVerdicts: {},
    detail,
  }
}

function artifactFromRow(a: Row): JoinedArtifact {
  const aid = String(a.artifact_id ?? '')
  const producer = normalizeAgentId(a.producer_agent_id)
  return {
    artifactId: aid,
    producer,
    artifactType: String(a.artifact_type ?? ''),
    payloadHash: String(a.payload_hash ?? ''),
    createdAt: String(a.created_at ?? ''),
    severity: a.severity ? String(a.severity) : undefined,
    artifactKind: a.artifact_kind ? String(a.artifact_kind) : undefined,
    providerFamily: a.provider_family ? String(a.provider_family) : undefined,
    model: a.model ? String(a.model) : undefined,
    primaryFindingCode: a.primary_finding_code ? String(a.primary_finding_code) : undefined,
    primaryFindingVerdict: a.primary_finding_verdict ? String(a.primary_finding_verdict) : undefined,
    primaryLessonId: a.primary_lesson_id ? String(a.primary_lesson_id) : undefined,
  }
}

// Fetch a read-only listing; null on any failure or a surface that advertises authority.
async function getRows(baseUrl: string, path: string, fetchImpl: typeof fetch): Promise<Row[] | null> {
  let resp: Response
  try {
    resp = await fetchImpl(`${baseUrl}${path}`, { method: 'GET', headers: { accept: 'application/json' } })
  } catch {
    return null
  }
  if (!resp.ok) return null
  let body: unknown
  try { body = await resp.json() } catch { return null }
  const p = body as { read_only?: boolean; authority?: Record<string, boolean>; data?: unknown }
  if (p?.read_only !== true) return null
  if (p.authority && Object.values(p.authority).some(Boolean)) return null
  return Array.isArray(p.data) ? (p.data as Row[]) : []
}

export async function resolveAgentRuntimeDetail(
  agentId: string,
  config: { baseUrl?: string; fetchImpl?: typeof fetch } = {},
): Promise<AgentDetailView> {
  const baseUrl = config.baseUrl ?? ''
  const fetchImpl = config.fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!fetchImpl) return emptyView(agentId, false, 'No fetch implementation available.')

  const runs = await getRows(baseUrl, '/api/v3/agent-runtime/runs?limit=200', fetchImpl)
  if (runs === null) return emptyView(agentId, false, 'Read API not connected.')

  const artifactById = new Map<string, JoinedArtifact>()
  const engaged = new Set<string>()
  const runInfo: AgentDetailView['runs'] = []
  const irisLessonVerdicts: Record<string, IrisLessonVerdict> = {}

  for (const run of runs.slice(0, 50)) {
    const runId = String(run.run_id ?? '')
    if (!runId) continue
    const [arts, reviews, scores] = await Promise.all([
      getRows(baseUrl, `/api/v3/agent-runtime/runs/${runId}/artifacts`, fetchImpl),
      getRows(baseUrl, `/api/v3/agent-runtime/runs/${runId}/reviews`, fetchImpl),
      getRows(baseUrl, `/api/v3/agent-runtime/runs/${runId}/scores`, fetchImpl),
    ])
    let touched = normalizeAgentId(run.agent_id) === agentId
    for (const a of arts ?? []) {
      const aid = String(a.artifact_id ?? '')
      if (!aid || String(a.artifact_type ?? '') === '__run_event__') continue
      const joined = artifactFromRow(a)
      artifactById.set(aid, joined)
      if (joined.producer === 'iris' && joined.artifactType === 'knowledge_review' && joined.primaryLessonId) {
        irisLessonVerdicts[joined.primaryLessonId] = {
          code: joined.primaryFindingCode ?? '',
          verdict: joined.primaryFindingVerdict ?? '',
          severity: joined.severity,
          artifactId: aid,
        }
      }
      if (joined.producer === agentId) { engaged.add(aid); touched = true }
    }
    for (const r of reviews ?? []) {
      const aid = String(r.artifact_id ?? '')
      const j = artifactById.get(aid)
      const reviewer = normalizeAgentId(r.reviewer_agent_id)
      if (j) { j.reviewer = reviewer; j.verdict = String(r.verdict ?? '') }
      if (reviewer === agentId) { engaged.add(aid); touched = true }
    }
    for (const s of scores ?? []) {
      const aid = String(s.artifact_id ?? '')
      const j = artifactById.get(aid)
      const scorer = normalizeAgentId(s.scorer_agent_id)
      if (j) j.scorer = scorer
      if (scorer === agentId) { engaged.add(aid); touched = true }
    }
    if (touched) runInfo.push({
      runId,
      status: String(run.status ?? ''),
      startedAt: String(run.started_at ?? run.updated_at ?? ''),
      completedAt: run.completed_at ? String(run.completed_at) : null,
      updatedAt: String(run.updated_at ?? run.started_at ?? ''),
    })
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
  const lessonItems: LessonItem[] = []
  for (const l of lessonRows) {
    const k = String(l.lifecycle ?? 'UNKNOWN')
    byLifecycle[k] = (byLifecycle[k] ?? 0) + 1
    lessonItems.push({
      lessonId: String(l.lesson_id ?? ''),
      title: String(l.title ?? ''),
      lifecycle: k,
      statement: String(l.statement ?? ''),
      createdAt: l.created_at ? String(l.created_at) : undefined,
    })
  }
  const byType: Record<string, number> = {}
  for (const c of caseRows) { const k = String(c.case_type ?? 'UNKNOWN'); byType[k] = (byType[k] ?? 0) + 1 }

  return {
    live: true, agentId, role,
    runs: runInfo,
    artifacts: mine.slice(0, 40),
    counts: { produced, reviewed, scored, byVerdict },
    lessons: { total: lessonRows.length, byLifecycle, items: lessonItems },
    cases: { total: caseRows.length, byType },
    irisLessonVerdicts,
    detail: 'Live read-only detail from the agent-runtime read API.',
  }
}
