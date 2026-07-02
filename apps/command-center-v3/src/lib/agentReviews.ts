/** Normalize agent review rows — fixes duplicate Maria/maria, pending vs reviewed conflicts. */

export const REQUIRED_AGENTS = ['maria', 'risk_agent', 'steph'] as const

const AGENT_LABELS: Record<string, string> = {
  maria: 'Maria',
  risk_agent: 'Risk',
  steph: 'Steph',
  aegis: 'Aegis',
}

const CLOUD_LANES = new Set(['grok', 'chatgpt', 'local', 'ensemble'])

export function normalizeAgentKey(name: string | null | undefined): string {
  const raw = String(name || '').trim()
  if (!raw) return ''
  const lower = raw.toLowerCase().replace(/\s+/g, '_')
  if (lower === 'risk' || lower === 'risk_agent') return 'risk_agent'
  if (lower === 'maria') return 'maria'
  if (lower === 'steph') return 'steph'
  if (lower === 'aegis') return 'aegis'
  if (CLOUD_LANES.has(lower)) return ''
  return lower
}

export function agentDisplayName(key: string): string {
  return AGENT_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export type NormalizedReview = {
  key: string
  agent: string
  status: string
  verdict: string | null
  model: string | null
  summary: string | null
  reviewed_at: string | null
  pending: boolean
  isFallback: boolean
}

function reviewComplete(r: any): boolean {
  const v = String(r.verdict || r.vote || '').trim()
  const st = String(r.status || '').toLowerCase()
  return Boolean(v) && st !== 'pending'
}

function reviewScore(r: any): number {
  let s = 0
  if (reviewComplete(r)) s += 10
  if (r.reviewed_at) s += 5
  if (r.summary) s += 1
  if (String(r.model || '').includes('gemma')) s += 2
  return s
}

export function dedupeAgentReviews(reviews: any[]): NormalizedReview[] {
  const byKey = new Map<string, any>()
  for (const r of reviews || []) {
    const key = normalizeAgentKey(r.agent)
    if (!key) continue
    const prev = byKey.get(key)
    if (!prev || reviewScore(r) > reviewScore(prev)) byKey.set(key, r)
  }
  return Array.from(byKey.entries()).map(([key, r]) => {
    const verdict = String(r.verdict || r.vote || '').trim() || null
    const st = String(r.status || '').toLowerCase()
    const pending = !verdict || st === 'pending'
    const model = r.model ? String(r.model) : null
    return {
      key,
      agent: agentDisplayName(key),
      status: pending ? 'pending' : (st || 'reviewed'),
      verdict,
      model,
      summary: r.summary ? String(r.summary).trim() : null,
      reviewed_at: r.reviewed_at ? String(r.reviewed_at) : null,
      pending,
      isFallback: model === 'deterministic_fallback' || !model,
    }
  })
}

export function computeAgentPending(
  reviews: any[],
  serverPending?: string[] | null,
): string[] {
  const deduped = dedupeAgentReviews(reviews)
  const missingRequired = REQUIRED_AGENTS.filter(req => {
    const hit = deduped.find(r => r.key === req)
    return !hit || hit.pending
  }).map(agentDisplayName)
  // Prefer deduped review rows over stale server pending (Maria vs maria duplicate fix)
  if (missingRequired.length) return missingRequired
  if (serverPending?.length) {
    return serverPending.map(k => agentDisplayName(normalizeAgentKey(k) || k))
  }
  return []
}

export function agentVerdictColor(verdict: string | null | undefined): string {
  const v = String(verdict || '').toUpperCase()
  if (v === 'BLOCK' || v === 'REJECT') return 'var(--red)'
  if (v === 'APPROVE_TEST' || v === 'APPROVE_READY') return 'var(--green)'
  if (v === 'CAUTIOUS_TEST' || v === 'WAIT_FOR_DATA') return 'var(--amber)'
  return 'var(--text3)'
}

export function modelTierLabel(model: string | null | undefined): { label: string; tier: 'cloud' | 'local' | 'fallback' } {
  const m = String(model || '').toLowerCase()
  if (!m || m === 'deterministic_fallback') return { label: 'Rule-based fallback', tier: 'fallback' }
  if (m.includes('gpt') || m.includes('grok') || m.includes('claude')) return { label: model!, tier: 'cloud' }
  return { label: model!, tier: 'local' }
}