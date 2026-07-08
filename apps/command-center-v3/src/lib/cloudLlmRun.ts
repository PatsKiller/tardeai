/** Free OAuth manual runs — Grok :8645 / ChatGPT :8646 via consumption API. */

export type LanePolicy = 'grok_only' | 'chatgpt_only' | 'either' | 'both_preferred' | 'ensemble'

export function lanesForPolicy(policy: LanePolicy | string | undefined): ('grok' | 'chatgpt')[] {
  const p = (policy || 'either') as LanePolicy
  if (p === 'grok_only') return ['grok']
  if (p === 'chatgpt_only') return ['chatgpt']
  if (p === 'both_preferred' || p === 'ensemble') return ['grok', 'chatgpt']
  return ['grok', 'chatgpt'] // either — show both, operator picks
}

export async function runManualCloud(params: {
  process_id: string
  lane: 'grok' | 'chatgpt'
  prompt: string
  task_summary?: string
  timeout?: number
}): Promise<{ ok: boolean; text?: string; error?: string; manual_required?: boolean }> {
  const res = await fetch('/api/v2/consumption/run-manual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  const j = await res.json()
  const d = j?.data ?? j
  return d
}

export async function runBrokerCloudLane(proposalId: number, lane: 'grok' | 'chatgpt', timeout = 120) {
  const res = await fetch('/api/v2/broker-proposals/run-cloud-oversight', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposal_id: proposalId, lanes: [lane], timeout }),
  })
  return res.json().then(j => j?.data ?? j)
}

export async function runStopAdvisoryBatch(opts?: { limit?: number; lane?: 'grok' | 'chatgpt'; symbols?: string }) {
  const res = await fetch('/api/v2/consumption/stop-advisory-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts || {}),
  })
  return res.json().then(j => j?.data ?? j)
}

export async function runWatchlistCioSynthesis(symbol: string, lane: 'grok' | 'chatgpt') {
  const sym = symbol.trim().toUpperCase()
  const res = await fetch(`/api/v2/watchlist/${encodeURIComponent(sym)}/cio-synthesis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lanes: [lane] }),
  })
  return res.json().then(j => j?.data ?? j)
}

export async function runRotationOversight(lanes: ('grok' | 'chatgpt')[]) {
  const res = await fetch('/api/v2/rotation/oversight', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lanes }),
  })
  const text = await res.text()
  try {
    return text ? JSON.parse(text) : { error: 'Empty response — try again.' }
  } catch {
    return { error: 'Non-JSON response — try again.' }
  }
}

export async function runPortfolioAsk(question: string, lane: 'grok' | 'chatgpt') {
  const res = await fetch('/api/v2/portfolio/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, lane }),
  })
  const j = await res.json()
  return j?.data ?? j
}

export async function runJournalAsk(params: {
  question: string
  lane: 'grok' | 'chatgpt'
  account?: string
  days?: number
}) {
  const res = await fetch('/api/v2/journal/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  const j = await res.json()
  return j?.data ?? j
}

export type EnsembleLane = 'grok' | 'chatgpt' | 'local'

export async function requestEnsemble(params: {
  targetType: string
  targetId: string | number
  content: string
  subject?: string
  task?: string
  /** Omit for default grok+chatgpt+local; pass subset for per-lane manual runs. */
  lanes?: EnsembleLane[]
}) {
  const res = await fetch('/api/v2/inference/ensemble/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_type: params.targetType,
      target_id: params.targetId,
      subject: params.subject,
      content: params.content,
      task: params.task || 'inference_quality',
      lanes: params.lanes,
    }),
  })
  return res.json().then(j => j?.data ?? j)
}

/** Human-readable lane policy for UI badges. */
export function lanePolicyHint(policy: LanePolicy | string | undefined): string {
  const p = (policy || 'either') as LanePolicy
  const map: Record<LanePolicy, string> = {
    grok_only: 'Grok only',
    chatgpt_only: 'ChatGPT only',
    either: 'Grok or ChatGPT',
    both_preferred: 'Both preferred',
    ensemble: 'Run both',
  }
  return map[p] || p
}