// Ops › Jobs & n8n › n8n catalog (LQ-20261107-150, operator 2026-11-07). What n8n is configured to handle, by
// category, with each lane's mode, relay-list membership and audit verdict. One read-only GET:
// /api/v2/ops/n8n-catalog (N8nCatalog@v1). Pure: no React, no DOM, no fetch.
//
// Operator rules carried here: never a bare "dry" (say "Dry run"); every mode chip, verdict chip and top stat has a
// plain-language tooltip; a lane is "working" only with verdict PASS or PASS_IDLE; no verdict = "not audited".

export const N8N_CATALOG_API = '/api/v2/ops/n8n-catalog'

export type CatalogMode = 'live' | 'both' | 'dry' | 'none'
export type VerdictClass = 'pass' | 'fail' | 'not_provable' | 'not_audited'
export type Tone = 'success' | 'danger' | 'warning' | 'info' | 'neutral'

export type CatalogLane = {
  lane_id: string
  title?: string | null
  does?: string | null
  category_key: string
  scheduler?: string | null
  state?: string | null
  status?: string | null
  schedule?: string[] | null
  timezone?: string | null
  last_run_mode?: string | null
  mode: CatalogMode
  in_relay?: boolean
  paused_on_n8n?: boolean
  verdict?: string | null
  verdict_class?: VerdictClass | null
  defect?: string | null
  fix_suggestion?: string | null
  work_item?: string | null
  audited_at?: string | null
}
export type CatalogCategory = {
  key: string; label: string; blurb?: string | null; modes: Record<CatalogMode, number>; lanes: string[]
  /** LQ-20261107-180: every job in the category (active + paused/retired) and the Job catalog's status mix. */
  jobs?: number; inactive?: number; status_mix?: Record<string, number>
}
export type WorkItem = { id: string; owner?: string | null; priority?: string | null; status?: string | null; title?: string | null }
export type N8nCatalogWire = {
  schema?: string
  computed_at?: string | null
  stats?: {
    modes?: Partial<Record<CatalogMode, number>>
    verdicts?: Record<string, number>
    audit?: { pass?: number; fail?: number; not_provable?: number; audited?: number }
    retired_not_counted?: number
  }
  categories?: CatalogCategory[]
  lanes?: Record<string, CatalogLane>
  relay?: { source?: string | null; lanes?: number | null; paused?: string[]; note?: string | null }
  audit?: { state?: string; written_at?: string | null; by?: string | null; rows?: number; note?: string | null }
  notes?: string[]
  work_items?: Record<string, WorkItem>
}

/** The four mode labels, verbatim from the operator's addendum. */
export const MODE_LABEL: Record<CatalogMode, string> = {
  live: 'Live on n8n',
  both: 'n8n + cron (both)',
  dry: 'Dry run on n8n',
  none: 'Not on n8n',
}
/** The four mode tooltips, verbatim from the operator's addendum (11:18 ET). */
export const MODE_TIP: Record<CatalogMode, string> = {
  live: 'n8n is the only scheduler; the cron line is retired. Being live does not prove the data is right — see the audit verdict.',
  both: 'n8n and cron are both scheduled. They share a lock, so whichever fires first runs and the other skips. The cron line is retired only after a verified live n8n run.',
  dry: 'n8n runs it in report-only mode and writes nothing. It shows what it would do before the cutover.',
  none: 'Stays on cron/systemd: broker, send class, always-on services, or not migrated yet.',
}
export const MODE_TONE: Record<CatalogMode, Tone> = { live: 'success', both: 'info', dry: 'warning', none: 'neutral' }
export const MODES: readonly CatalogMode[] = ['live', 'both', 'dry', 'none']

export const NOT_AUDITED = 'not audited'
/** One sentence per verdict (the audit's own meanings), plus "not audited". */
export const VERDICT_MEANING: Record<string, string> = {
  PASS: 'All six audit checks are proven: config, runs, output, data accurate against an independent source, AI claims sourced, and the page you read matches.',
  PASS_IDLE: 'Correctly idle on the weekend, and its last weekday run passed the output and data checks.',
  FAIL_DATA: 'The output exists, but values are wrong, stale, null or duplicated when checked against an independent source.',
  FAIL_RUN: 'The recent live runs failed, timed out or missed their slots.',
  FAIL_CONFIG: 'A cron or systemd twin is still running it, or it is missing from the relay live list.',
  FAIL_NO_OUTPUT: 'The run says done, but no matching output row or file was written.',
  FAIL_CONSUMER: 'The data is fine, but the page you look at shows different or stale values.',
  HALLUCINATION: 'An AI-written claim had no source or contradicted its source.',
  UNVERIFIABLE: 'Not provable yet: evidence is missing (no live run since the cutover, or no independent source). It is re-audited at its next run.',
  [NOT_AUDITED]: 'This lane has not been through the six-check audit, so nothing is claimed about whether it works.',
}
const VERDICT_LABEL: Record<string, string> = {
  PASS: 'PASS', PASS_IDLE: 'PASS · weekend idle', FAIL_DATA: 'FAIL · data', FAIL_RUN: 'FAIL · run', FAIL_CONFIG: 'FAIL · config',
  FAIL_NO_OUTPUT: 'FAIL · no output', FAIL_CONSUMER: 'FAIL · page', HALLUCINATION: 'FAIL · AI claim', UNVERIFIABLE: 'Not provable yet',
}

/** Same rule as the server: only PASS / PASS_IDLE are working. */
export function verdictClassOf(verdict: string | null | undefined): VerdictClass {
  if (!verdict) return 'not_audited'
  if (verdict === 'PASS' || verdict === 'PASS_IDLE') return 'pass'
  if (verdict === 'UNVERIFIABLE') return 'not_provable'
  if (verdict.startsWith('FAIL') || verdict === 'HALLUCINATION') return 'fail'
  return 'not_provable'
}
export const VERDICT_TONE: Record<VerdictClass, Tone> = { pass: 'success', fail: 'danger', not_provable: 'warning', not_audited: 'neutral' }

export function verdictLabel(verdict: string | null | undefined): string {
  if (!verdict) return 'Not audited'
  return VERDICT_LABEL[verdict] ?? verdict.replace(/_/g, ' ')
}

/** The verdict chip's tooltip: the meaning, then the lane's defect and work item when present. */
export function verdictTip(lane: Pick<CatalogLane, 'verdict' | 'defect' | 'work_item' | 'fix_suggestion'>): string {
  const v = lane.verdict || NOT_AUDITED
  const parts = [VERDICT_MEANING[v] ?? `Audit verdict ${v}.`]
  if (lane.defect) parts.push(`Defect: ${lane.defect}`)
  if (lane.fix_suggestion) parts.push(`Suggested fix: ${lane.fix_suggestion}`)
  if (lane.work_item) parts.push(`Work item: ${lane.work_item}`)
  return parts.join(' ')
}

export type CatalogStat = { key: string; label: string; value: number | null; tone: Tone; tip: string }
/** The top stats: four mode counts, then the audit PASS / FAIL / not-provable counts. A missing count is null ("—"). */
export function catalogStats(w: N8nCatalogWire | null | undefined): CatalogStat[] {
  const m = w?.stats?.modes
  const a = w?.stats?.audit
  const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null)
  const audited = num(a?.audited)
  return [
    ...MODES.map(k => ({ key: `mode:${k}`, label: MODE_LABEL[k], value: num(m?.[k]), tone: MODE_TONE[k], tip: MODE_TIP[k] })),
    { key: 'audit:pass', label: 'Audit PASS', value: num(a?.pass), tone: 'success' as Tone,
      tip: `Lanes whose audit verdict is PASS or PASS_IDLE, out of ${audited ?? '—'} audited. Only these count as working. ${VERDICT_MEANING.PASS}` },
    { key: 'audit:fail', label: 'Audit FAIL', value: num(a?.fail), tone: 'danger' as Tone,
      tip: 'Lanes with a FAIL verdict (data, run, config, no output, page, or an unsourced AI claim). Each lane shows its defect and the work item that fixes it.' },
    { key: 'audit:not_provable', label: 'Not provable yet', value: num(a?.not_provable), tone: 'warning' as Tone, tip: VERDICT_MEANING.UNVERIFIABLE },
  ]
}

/** The lanes of one category, in the server's order (live, both, dry; then by title). Unknown ids are skipped. */
export function categoryLanes(w: N8nCatalogWire | null | undefined, cat: CatalogCategory): CatalogLane[] {
  const lanes = w?.lanes ?? {}
  return (cat.lanes ?? []).map(id => lanes[id]).filter((x): x is CatalogLane => !!x)
}

/** "0 7 * * 1-5 · 30 16 * * 1-5", or "event / no schedule". */
export function scheduleText(lane: Pick<CatalogLane, 'schedule'>): string {
  const s = (lane.schedule ?? []).filter(Boolean)
  return s.length ? s.join(' · ') : 'event / no schedule'
}

/** Tapping a lane opens the existing full-screen lane sheet on the n8n lanes tab. */
export function laneHref(laneId: string): string {
  return `/ops/jobs-n8n?tab=n8n&lane=${encodeURIComponent(laneId)}`
}

/** A lane on n8n that is not in the relay live list cannot run live: say so on the row. Dry-run lanes never are. */
export function notInRelay(lane: Pick<CatalogLane, 'mode' | 'in_relay'>): boolean {
  return lane.mode !== 'dry' && lane.mode !== 'none' && !lane.in_relay
}

/** Every chip a lane row shows, with its tooltip (the vitest asserts none is empty). */
export function laneChips(lane: CatalogLane): Array<{ kind: 'mode' | 'verdict'; label: string; tip: string; tone: Tone }> {
  const vc = lane.verdict_class ?? verdictClassOf(lane.verdict)
  return [
    { kind: 'mode', label: MODE_LABEL[lane.mode] ?? lane.mode, tip: MODE_TIP[lane.mode] ?? '', tone: MODE_TONE[lane.mode] ?? 'neutral' },
    { kind: 'verdict', label: verdictLabel(lane.verdict), tip: verdictTip(lane), tone: VERDICT_TONE[vc] },
  ]
}
