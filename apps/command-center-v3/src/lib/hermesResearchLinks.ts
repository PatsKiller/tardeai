// HermesResearchLinks@v1 — pure helpers for the Hermes run → CIO decision reverse index.
// Links are router-relative (BrowserRouter basename="/v3"); never prefix "/v3".
// A link the backend reports NOT_RECORDED is rendered as NOT_RECORDED — the client never
// infers a decision from symbol or time.

export type LinkState = 'RECORDED' | 'NOT_RECORDED'

export interface HermesDecisionRef {
  id: string
  kind?: string
  as_of?: string
  impact?: string
  sources?: string[]
}

export interface HermesResearchLinkItem {
  result_id: string
  research_id?: string | null
  plan_id?: string | null
  completed_at?: string | null
  classification?: string | null
  agent?: string | null
  symbol?: string | null
  decision_ids: string[]
  decisions?: HermesDecisionRef[]
  decision_link?: { state: LinkState; reason?: string | null }
  thesis_refs: string[]
  workflow_ids?: string[]
}

export interface HermesResearchLinksPayload {
  schema?: string
  composition_as_of?: string
  source_as_of?: string | null
  items?: HermesResearchLinkItem[]
  counts?: Record<string, number>
}

export const HERMES_RESEARCH_LINKS_ROUTE = '/api/v3/hermes/research-links'

export function researchLinksUrl(opts: { symbol?: string; decisionId?: string; resultId?: string; limit?: number } = {}): string {
  const qs = new URLSearchParams()
  qs.set('limit', String(opts.limit ?? 25))
  if (opts.resultId) qs.set('result_id', opts.resultId)
  if (opts.symbol) qs.set('symbol', opts.symbol.toUpperCase())
  if (opts.decisionId) qs.set('decision_id', opts.decisionId)
  return `${HERMES_RESEARCH_LINKS_ROUTE}?${qs.toString()}`
}

export function decisionLineageHref(decisionId: string): string {
  return `/cio?tab=evidence-comms&sub=decision-lineage&decision=${encodeURIComponent(decisionId)}`
}

export function symbolResearchHref(symbol: string): string {
  return `/research-intelligence?symbol=${encodeURIComponent(symbol)}`
}

export function thesisHref(ref: string): string {
  return `/research-intelligence?q=${encodeURIComponent(ref)}`
}

export function hermesProvenanceHref(resultId: string): string {
  return `/hermes?tab=Provenance&result_id=${encodeURIComponent(resultId)}`
}

export function decisionLinkState(item: HermesResearchLinkItem): LinkState {
  if (item.decision_link?.state === 'RECORDED' && item.decision_ids.length > 0) return 'RECORDED'
  return 'NOT_RECORDED'
}

export function linkItems(payload: HermesResearchLinksPayload | null | undefined): HermesResearchLinkItem[] {
  const items = payload?.items
  if (!Array.isArray(items)) return []
  return items.filter(item => item && typeof item.result_id === 'string').map(item => ({
    ...item,
    decision_ids: Array.isArray(item.decision_ids) ? item.decision_ids : [],
    thesis_refs: Array.isArray(item.thesis_refs) ? item.thesis_refs : [],
  }))
}

// ── AgentRuntimeProof@v1 ──────────────────────────────────────────────────────────────
export const AGENT_RUNTIME_PROOF_ROUTE = '/api/v3/agents/runtime-proof'
export type ProofState = 'RECORDED' | 'NOT_RECORDED' | 'NOT_EXPOSED'
export interface ProofField {
  state: ProofState
  value?: string | number | null
  at?: string | null
  reason?: string | null
  recent_ids?: string[]
  fleet_last_at?: string | null
}
export interface AgentRuntimeProofPayload {
  schema?: string
  fields?: Record<string, { attributable: boolean; source_ref?: string }>
  agents?: Record<string, Record<string, ProofField>>
}

export const PROOF_FIELDS: Array<[label: string, key: string]> = [
  ['Last natural wake', 'last_natural_wake'],
  ['Last research action', 'last_research_action'],
  ['Memory retrieval', 'last_memory_retrieval'],
  ['Decisions contributed to', 'decisions_contributed'],
]

/** Returns [displayValue, sourceTag] for one proof row. Never promotes an absent proof to RUNTIME. */
export function proofRow(payload: AgentRuntimeProofPayload | null | undefined, agentId: string, key: string): [string, string] {
  if (!payload || !payload.fields) return ['NOT EXPOSED BY READ CONTRACT', 'UNKNOWN']
  const field = payload.fields[key]
  if (!field) return ['NOT EXPOSED BY READ CONTRACT', 'UNKNOWN']
  const row = payload.agents?.[agentId.toLowerCase()]?.[key]
  if (!field.attributable || row?.state === 'NOT_EXPOSED') {
    const fleet = row?.fleet_last_at ? ` · fleet last ${row.fleet_last_at.slice(0, 19)}Z, unattributed` : ''
    return [`NOT EXPOSED: ${row?.reason ?? 'store carries no agent attribution'}${fleet}`, 'NOT_EXPOSED']
  }
  if (!row || row.state !== 'RECORDED') return ['NOT RECORDED', 'NOT_RECORDED']
  const at = row.at ? String(row.at).slice(0, 19) + 'Z' : ''
  if (key === 'decisions_contributed') {
    const recent = row.recent_ids?.length ? ` · latest ${row.recent_ids[0]}` : ''
    return [`${row.value ?? 0} decision${row.value === 1 ? '' : 's'}${recent}`, 'RUNTIME']
  }
  return [[row.value, at].filter(Boolean).join(' · ') || 'RECORDED', 'RUNTIME']
}
