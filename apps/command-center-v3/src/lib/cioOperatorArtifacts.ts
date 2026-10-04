export type CioOperatorArtifact = {
  original_schema?: string
  artifact_id?: string
  artifact_id_basis?: string
  producer?: string
  source_as_of?: string | null
  persisted_at?: string | null
  evidence_class?: string
  decision_id?: string | null
  symbol?: string | null
  source_ref?: string | null
  payload_truncated?: boolean
  payload?: unknown
}

export const ARTIFACT_LABELS: Record<string, string> = {
  'CIOAdvisoryMessage@v1': 'Advisory message',
  'CIOAdvisorySynthesis@v1': 'Advisory synthesis',
  'CIOAgentBrief@v1': 'Agent brief',
  'CIOAttentionAnswer@v1': 'Attention answer',
  'CIOWhatChanged@v1': 'What changed',
  'CioComposedNarrative@v1': 'Composed narrative',
  'CioModelNarration@v1': 'Model narration',
  'CioWakeComposition@v1': 'Wake composition',
  'GrokCritique@v1': 'Grok critique',
  'InvestmentDecision@v1': 'Investment decision',
  'InvestmentIntelligenceCard@v1': 'Intelligence card',
  'BuyReadyInstitutionalPacket@v2': 'Buy-ready packet',
  'AlertQuality@v1': 'Alert quality',
}

const MAX = 280

function clip(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > MAX ? `${t.slice(0, MAX - 1)}…` : t
}

/** The human-readable core of an artifact: its own text first, never raw JSON. */
export function artifactSummary(row: CioOperatorArtifact | null | undefined): string {
  const p = (row?.payload && typeof row.payload === 'object') ? row.payload as Record<string, unknown> : {}
  if (p._truncated) return `Payload truncated (${String(p._original_bytes ?? '?')} bytes); open details for the stored prefix.`
  for (const key of ['text', 'rendered_text', 'reply', 'summary', 'verdict', 'final_position', 'conclusion']) {
    const v = p[key]
    if (typeof v === 'string' && v.trim()) return clip(v)
  }
  const sentences = p.sentences
  if (Array.isArray(sentences)) {
    const joined = sentences.map(s => (s && typeof s === 'object' ? String((s as Record<string, unknown>).sentence ?? '') : String(s))).join(' ').trim()
    if (joined) return clip(joined)
  }
  const changed = p.what_changed
  if (Array.isArray(changed)) return `${changed.length} change${changed.length === 1 ? '' : 's'} recorded`
  return 'No readable text field; open details.'
}

/** Top-level scalar fields as label/value pairs for the details view. */
export function artifactFields(row: CioOperatorArtifact | null | undefined, limit = 12): [string, string][] {
  const p = (row?.payload && typeof row.payload === 'object') ? row.payload as Record<string, unknown> : {}
  const out: [string, string][] = []
  for (const [k, v] of Object.entries(p)) {
    if (v === null || v === undefined || typeof v === 'object') continue
    out.push([k, clip(String(v))])
    if (out.length >= limit) break
  }
  return out
}
