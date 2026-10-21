/** Learning loop PR1 (operator 2026-10-21) — where a closed trade came from, for TradeInView.
 *
 * Projects the `recommendation` block that /api/v2/journal attaches to each trade (and the response-level
 * `recommendation_link_status`) into what the journal shows: "From recommendation …" with its source and link
 * confidence, the plan, R achieved and planned R:R — or "Your own trade" when the linker found no plausible
 * recommendation. When the link is not known (migration not applied, linker not run on this trade) it says so and
 * never claims the trade was the operator's own idea. Pure; no React.
 */
import type { Tone } from './designTokens.ts'

export type RecBlock = {
  rec_id?: string | null
  rec_source?: string | null
  link_confidence?: string | null
  origin?: string | null
  plan_entry_low?: number | null
  plan_entry_high?: number | null
  plan_stop?: number | null
  plan_target?: number | null
  r_achieved?: number | null
  r_null_reason?: string | null
  planned_rr?: number | null
  target_hit?: boolean | null
  stop_hit?: boolean | null
  stop_source?: string | null
  rec_issued_at?: string | null
  conviction_at_issue?: number | null
}

export type RecOriginKind = 'recommendation' | 'own' | 'unknown'

export type RecOrigin = {
  kind: RecOriginKind
  headline: string
  sourceLabel: string | null
  confidenceLabel: string | null
  tone: Tone
  recId: string | null
  plan: string | null
  rAchieved: string
  rAchievedValue: number | null
  rNote: string | null
  plannedRr: string
  outcome: string | null
  chip: string
}

export const SOURCE_LABEL: Record<string, string> = {
  cio_opportunity: 'CIO opportunity',
  paper_trade_proposal: 'Trade proposal',
  scalp_alert: 'Scalp alert',
  entry_alert: 'Entry alert',
}

export const CONFIDENCE_LABEL: Record<string, string> = {
  exact: 'exact — filled inside the entry zone',
  zone: 'near the entry zone',
  window_only: 'timing only — fill was away from the entry zone',
}

const CONFIDENCE_TONE: Record<string, Tone> = { exact: 'success', zone: 'info', window_only: 'warning' }

const R_REASON: Record<string, string> = {
  no_stop: 'no stop on record',
  no_linked_or_journal_stop: 'the recommendation had no stop and none is on the journal',
  operator_initiated_no_journal_stop: 'no stop on the journal',
  stop_on_wrong_side_of_entry: 'stop was on the wrong side of the fill',
  missing_fill_price: 'fill price missing',
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const px = (v: number | null): string => (v == null ? '—' : v >= 100 ? v.toFixed(2) : v >= 1 ? v.toFixed(2) : v.toFixed(4))

export function shortRecId(id: string | null | undefined): string | null {
  if (!id) return null
  return id.length > 12 ? `${id.slice(0, 12)}…` : id
}

export function formatR(v: number | null): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}R`
}

export function formatRr(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(1)} : 1`
}

export function planText(b: RecBlock): string | null {
  const lo = num(b.plan_entry_low), hi = num(b.plan_entry_high), st = num(b.plan_stop), tg = num(b.plan_target)
  if (lo == null && hi == null && st == null && tg == null) return null
  const entry = lo != null && hi != null && Math.abs(hi - lo) > 1e-9 ? `${px(lo)}–${px(hi)}` : px(lo ?? hi)
  return `Entry ${entry} · Stop ${px(st)} · Target ${px(tg)}`
}

export function recommendationOrigin(rec: RecBlock | null | undefined, linkStatus?: string | null): RecOrigin {
  const base = { sourceLabel: null, confidenceLabel: null, recId: null, plan: null, outcome: null,
    rAchieved: '—', rAchievedValue: null, rNote: null, plannedRr: '—' }
  if (linkStatus !== 'ok' || !rec || !rec.origin) {
    const why = linkStatus === 'unavailable' ? 'recommendation links are not available yet'
      : 'not linked yet — the linker runs after the evening journal build'
    return { ...base, kind: 'unknown', headline: `Origin unknown · ${why}`, tone: 'neutral', chip: 'origin ?' }
  }
  const r = num(rec.r_achieved)
  const rNote = r == null && rec.r_null_reason ? (R_REASON[rec.r_null_reason] ?? rec.r_null_reason) : null
  const stopNote = r != null && rec.stop_source === 'journal' ? 'R uses the journal stop' : null
  const outcome = rec.target_hit ? 'target reached at exit' : rec.stop_hit ? 'stopped out at or below the plan stop' : null
  if (rec.origin === 'operator_initiated') {
    return { ...base, kind: 'own', headline: 'Your own trade — no matching recommendation was active', tone: 'neutral',
      rAchieved: formatR(r), rAchievedValue: r, rNote: rNote ?? stopNote, chip: 'own trade' }
  }
  const src = rec.rec_source ? (SOURCE_LABEL[rec.rec_source] ?? rec.rec_source) : 'recommendation'
  const conf = rec.link_confidence ?? ''
  const id = shortRecId(rec.rec_id)
  return {
    kind: 'recommendation',
    headline: `From recommendation ${id ?? ''} · ${src}`.replace(/\s+·/, ' ·'),
    sourceLabel: src,
    confidenceLabel: CONFIDENCE_LABEL[conf] ?? (conf || null),
    tone: CONFIDENCE_TONE[conf] ?? 'neutral',
    recId: rec.rec_id ?? null,
    plan: planText(rec),
    rAchieved: formatR(r),
    rAchievedValue: r,
    rNote: rNote ?? stopNote,
    plannedRr: formatRr(num(rec.planned_rr)),
    outcome,
    chip: `${src} · ${conf === 'window_only' ? 'timing' : conf || 'linked'}`,
  }
}
