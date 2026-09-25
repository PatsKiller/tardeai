// Runtime model shown on the Agents hub. The page used to hardcode
// 'gemma3:12b' for every agent as if it were a live fact; the summary API
// (/api/v2/agents/summary) reports no model, and Alex runs on the governed
// DeepSeek lane. Show only what the API row says; otherwise say so.
// (Governance truth repair, 2026-09-25.)
export const MODEL_NOT_REPORTED = 'not reported by API'

export function agentModelLabel(row: Record<string, unknown> | null | undefined): string {
  if (!row) return MODEL_NOT_REPORTED
  for (const key of ['runtime_model', 'model', 'provider_model']) {
    const v = row[key]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return MODEL_NOT_REPORTED
}
