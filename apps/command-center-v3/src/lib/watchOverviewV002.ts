/** Watch v002 Overview — the section model (LQ-20261107-2993 · W-04, lead 00:47 ET).
 *
 *  The Overview is ordered Action/Triggers → Validation Gates → Since Last Visit → Watch Status → Details. Two of the
 *  five sections (Action/Triggers, Since Last Visit) are new, so this module names their data contract instead of leaving
 *  it implied:
 *
 *   - Action/Triggers: what needs a decision NOW. Pullback/MACD TRIGGER-tier candidates (the screener's own triggers, with
 *     entry/stop/target and whether their proposal is still live) plus armed alerts that have FIRED. Read-only; the rows
 *     link to the symbol page. Never a buy instruction — the screen lists, the operator decides.
 *   - Since Last Visit: the same two sources filtered to events after the last recorded visit. The anchor is the
 *     server-side `watch.last_seen` pref (stamped like home.last_seen: the server owns the time, the client only says
 *     which device). When there is no recorded visit the window is an explicit 24 h fallback and says so — a read that
 *     could not be made never silently becomes "nothing happened".
 *
 *  Pure: no fetch, no writes. `lastVisit()` reads a pref body; the page POSTs the visit after it has computed the window.
 */
import { etText, unwrap } from './watchSetupsV002.ts'

export const ALERTS_LIST_API = '/api/v2/watch/alerts/list'
export const PULLBACK_TRIGGERS_API = '/api/v2/pullback-macd/candidates?tier=trigger'
export const LAST_SEEN_KEY = 'watch.last_seen'
export const LAST_SEEN_API = `/api/v2/ui/prefs/get?key=${LAST_SEEN_KEY}`
export const LAST_SEEN_POST = '/api/v2/ui/prefs'
export const FALLBACK_WINDOW_HOURS = 24

const asRec = (v: unknown): Record<string, any> | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, any>) : null)
const ms = (v: unknown): number | null => (typeof v === 'string' && v ? (Number.isFinite(Date.parse(v)) ? Date.parse(v) : null) : null)

export type LastVisit = {
  /** false when there is no trustworthy anchor: the window is the fallback and the label says why. */
  recorded: boolean
  status: 'RECORDED' | 'NOT_RECORDED' | 'UNKNOWN'
  startMs: number
  label: string
  seenAt: string | null
}

const READ_STATES = new Set(['OK', 'LOADING', 'UNKNOWN', 'TIMED OUT'])
/** The read wrapper's own state (readOnce shape), or null for a bare body. */
function readStateOf(v: unknown): string | null {
  const r = asRec(v)
  if (!r || !READ_STATES.has(String(r.state))) return null
  return 'source' in r || 'at' in r || 'error' in r ? String(r.state) : null
}

/** The Since-Last-Visit window from the `watch.last_seen` pref read. A read that did not answer OK is UNKNOWN (the
 *  fallback, with the reason) and a record that exists but has no parseable seen_at falls back too — never treated as
 *  "just now", which would hide every event, and never as "nothing happened". */
export function lastVisit(pref: unknown, nowMs: number): LastVisit {
  const readState = readStateOf(pref)
  const startMs = nowMs - FALLBACK_WINDOW_HOURS * 3600_000
  if (readState !== null && readState !== 'OK') {
    // LOADING is transient and says so; a failed read is UNKNOWN and the page names it as unread.
    return readState === 'LOADING'
      ? { recorded: false, status: 'NOT_RECORDED', startMs, label: `last ${FALLBACK_WINDOW_HOURS} h — still reading your last visit`, seenAt: null }
      : { recorded: false, status: 'UNKNOWN', startMs, label: `last ${FALLBACK_WINDOW_HOURS} h — the last-visit record could not be read`, seenAt: null }
  }
  const b = unwrap(pref)
  const read = asRec(b?.read)
  const fallback: LastVisit = {
    recorded: false, status: read?.status === 'UNKNOWN' ? 'UNKNOWN' : 'NOT_RECORDED',
    startMs: nowMs - FALLBACK_WINDOW_HOURS * 3600_000,
    label: read?.status === 'UNKNOWN' ? `last ${FALLBACK_WINDOW_HOURS} h — the last-visit record could not be read`
      : `last ${FALLBACK_WINDOW_HOURS} h — your last visit is not recorded`,
    seenAt: null,
  }
  // The server `read` block is authoritative once the key is a registered last-seen key; before that the raw value is
  // all there is, and a stored seen_at is still a real anchor.
  const seenAt = (read?.status === 'RECORDED' ? read.seen_at : null) ?? asRec(b?.value)?.seen_at
  const t = ms(seenAt)
  if (t === null) return fallback
  if (t - nowMs > 300_000) return fallback  // a future stamp is a clock fault, not a visit
  return { recorded: true, status: 'RECORDED', startMs: t, label: `since ${etText(seenAt) ?? 'your last visit'}`, seenAt: String(seenAt) }
}

export type ActionRow = {
  id: string
  kind: 'trigger' | 'alert'
  symbol: string
  text: string
  detail: string
  href: string
  tone: 'ok' | 'warn' | 'bad'
}

const sym = (v: unknown): string => (typeof v === 'string' && v.trim() ? v.trim().toUpperCase() : '')
const detailHref = (symbol: string): string => `/watch/intelligence/${encodeURIComponent(symbol)}`
const num = (v: unknown): number | null => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v))

/** Action/Triggers: pullback triggers first (they are the screener's decision points), then alerts that have fired. */
export function actionRows(alertsBody: unknown, candidatesBody: unknown): ActionRow[] {
  const out: ActionRow[] = []
  const cands = unwrap(candidatesBody)?.candidates
  if (Array.isArray(cands)) {
    for (const c of cands) {
      const symbol = sym(c?.symbol)
      if (!symbol || String(c?.tier || '') !== 'trigger') continue
      const entry = num(c?.entry), stop = num(c?.stop), target = num(c?.target1), score = num(c?.score)
      const plan = [entry !== null ? `entry ${entry}` : null, stop !== null ? `stop ${stop}` : null, target !== null ? `target ${target}` : null].filter(Boolean).join(' · ')
      const queue = c?.proposal_live === true ? 'proposal in queue' : c?.proposal_live === false ? 'its proposal is dead — re-check' : 'no proposal'
      const held = c?.held_conflict ? ' · HELD, near its stop' : ''
      out.push({ id: `trigger-${symbol}`, kind: 'trigger', symbol, href: detailHref(symbol),
        text: `Pullback/MACD trigger${score !== null ? ` · score ${Math.round(score)}` : ''}${c?.held_conflict ? ' · held, near stop' : ''}`,
        detail: [plan, queue].filter(Boolean).join(' · ') + held, tone: c?.held_conflict ? 'bad' : 'ok' })
    }
  }
  const alerts = unwrap(alertsBody)?.alerts
  if (Array.isArray(alerts)) {
    for (const a of alerts) {
      if (a?.active !== true) continue
      const fired = ms(a?.last_fired_at)
      if (fired === null) continue
      const symbol = sym(a?.symbol) || sym(a?.directive_id)
      if (!symbol) continue
      const cond = String(a?.condition_type || 'alert').replace(/_/g, ' ')
      const th = a?.threshold === null || a?.threshold === undefined ? '' : ` ${a.threshold}`
      out.push({ id: `alert-${a.id ?? symbol}`, kind: 'alert', symbol, href: detailHref(symbol),
        text: `Alert: ${symbol} ${cond}${th}`.trim(), detail: `fired ${etText(a.last_fired_at) ?? 'at an unknown time'}`, tone: 'warn' })
    }
  }
  return out
}

export type SinceRow = { id: string; kind: 'trigger' | 'alert'; symbol: string; text: string; at: string; atText: string | null }

/** Events after `startMs`, newest first. An event with no usable timestamp is not claimed as "since" — it is not shown here. */
export function sinceRows(alertsBody: unknown, candidatesBody: unknown, startMs: number, cap = 25): SinceRow[] {
  const rows: SinceRow[] = []
  const cands = unwrap(candidatesBody)?.candidates
  if (Array.isArray(cands)) {
    for (const c of cands) {
      const t = ms(c?.first_seen_at)
      const symbol = sym(c?.symbol)
      if (t === null || t < startMs || !symbol) continue
      rows.push({ id: `since-trigger-${symbol}`, kind: 'trigger', symbol, at: String(c.first_seen_at),
        text: `${symbol} entered the Pullback/MACD screen (${String(c?.tier || 'watch')})`, atText: etText(c.first_seen_at) })
    }
  }
  const alerts = unwrap(alertsBody)?.alerts
  if (Array.isArray(alerts)) {
    for (const a of alerts) {
      const t = ms(a?.last_fired_at)
      const symbol = sym(a?.symbol) || sym(a?.directive_id)
      if (t === null || t < startMs || !symbol) continue
      const th = a?.threshold === null || a?.threshold === undefined ? '' : ` ${a.threshold}`
      rows.push({ id: `since-alert-${a.id ?? symbol}`, kind: 'alert', symbol, at: String(a.last_fired_at),
        text: `${symbol} alert fired: ${String(a?.condition_type || 'alert').replace(/_/g, ' ')}${th}`, atText: etText(a.last_fired_at) })
    }
  }
  // Newest first. A row with no parseable time sorts last instead of pretending to be at the epoch.
  const sortKey = (r: SinceRow): number => ms(r.at) ?? Number.NEGATIVE_INFINITY
  return rows.sort((x, y) => sortKey(y) - sortKey(x)).slice(0, cap)
}

/** The reads a section depends on that did NOT answer OK. Empty = the section can state its own result. */
export function unreadReads(sources: { name: string; state: string }[]): string[] {
  return sources.filter(s => s.state !== 'OK').map(s => s.name)
}

/** What the prefs route said about this visit. `null` = the server stamped it.
 *
 *  HTTP 200 alone is not a stamp (W-04 review C1): the route answers 200 with `{ok, key}` and no `value` when the key
 *  is not registered as a last-seen key, and only the registered branch writes the server-owned `seen_at`
 *  (`api_v2.py` `_ui_prefs_set`). Classifying the body keeps the line drawn today and keeps it correct after the
 *  registration lands. */
export function stampResult(body: unknown): string | null {
  const r = asRec(body)
  if (!r) return 'the server did not confirm the visit'
  if (r.ok === false) return typeof r.error === 'string' && r.error ? r.error : 'the server refused the visit'
  const seenAt = asRec(r.value)?.seen_at
  return typeof seenAt === 'string' && seenAt ? null : 'the server did not stamp a visit'
}

/** The Action/Triggers meta line. A count over a read that did not answer is "unknown beats wrong" inverted: while any
 *  source is unread the meta says the list is incomplete instead of stating a total (W-04 review C2). */
export function actionMeta(rows: number, unread: number, loading: boolean): string {
  if (loading) return 'reading…'
  if (unread > 0) return 'incomplete — a source could not be read'
  return `${rows} to look at`
}
