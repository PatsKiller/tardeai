// Ops › Job catalog: each job's n8n audit verdict as a badge (LQ-20261107-506, operator-approved 2026-11-07 20:34 ET).
// Pure: no React, no fetch. The verdict comes from the same GET /api/v2/ops/n8n-catalog that Jobs & n8n > n8n audit
// reads, keyed by lane_id, so the two pages cannot give different answers for the same job.
import {
  NOT_AUDITED, VERDICT_MEANING, VERDICT_TONE, verdictClassOf, verdictLabel, verdictTip,
  type N8nCatalogWire, type Tone,
} from './n8nCatalog.ts'

export const N8N_AUDIT_PATH = '/ops/jobs-n8n?tab=catalog'

export type JobAuditBadge = {
  state: 'audited' | 'not_audited'
  /** "n8n audit: PASS", "n8n audit: FAIL · data", "n8n audit: UNVERIFIABLE", "n8n audit: not audited". */
  label: string
  tone: Tone
  tip: string
  /** The fix's LQ id when the audit assigned one. */
  lq: string | null
  verdict: string | null
}

const CLASS_WORD = { pass: 'PASS', fail: 'FAIL', not_provable: 'UNVERIFIABLE', not_audited: 'not audited' } as const

/** The badge for one job, or null while the audit has not loaded: an unread audit is "unknown", never "not audited". */
export function jobAuditBadge(laneId: string, wire: N8nCatalogWire | null | undefined): JobAuditBadge | null {
  if (!wire || !wire.lanes) return null
  const lane = wire.lanes[laneId]
  if (!lane || !lane.verdict) {
    return { state: 'not_audited', label: `n8n audit: ${CLASS_WORD.not_audited}`, tone: VERDICT_TONE.not_audited, lq: null, verdict: null,
      tip: `${VERDICT_MEANING[NOT_AUDITED]} Only jobs that n8n runs (and a few cron twins) are audited.` }
  }
  const cls = lane.verdict_class ?? verdictClassOf(lane.verdict)
  // FAIL keeps its reason ("FAIL · data"); PASS_IDLE keeps "weekend idle"; UNVERIFIABLE is spelled as the operator names it.
  const detail = cls === 'fail' || lane.verdict === 'PASS_IDLE' ? verdictLabel(lane.verdict) : CLASS_WORD[cls]
  return { state: 'audited', label: `n8n audit: ${detail}`, tone: VERDICT_TONE[cls], lq: lane.work_item || null, verdict: lane.verdict, tip: verdictTip(lane) }
}

/** The header line under the tiles: where the full audit lives. */
export const AUDIT_LINK_TEXT = 'Open the n8n audit tab (Jobs & n8n) for every lane, defect and fix'
