/**
 * FQ-030 / FQ-031 (/consumption). The page listed 109 process rows with their controls and 40
 * fully-expanded call records, which is a ~78,000px scroll on a phone. These helpers let the page
 * lead with spend and failed calls, collapse the registry and log by default, and keep the
 * internal process id and the raw request text one disclosure away instead of in the title line.
 *
 * Rules: nothing is removed — collapsing hides rows behind a control that reveals them again.
 */

export type ConsumptionLog = {
  id: number
  created_at: string
  model_lane: string
  process_id?: string
  process_name: string
  task_summary: string
  trigger_mode: string
  success: boolean
}

/** How many rows stay visible before the reader asks for the rest. Phones get fewer. */
export const PHONE_PROCESS_PREVIEW = 6
export const PHONE_LOG_PREVIEW = 5
export const DESK_PROCESS_PREVIEW = 12
export const DESK_LOG_PREVIEW = 10

/** Calls that failed. The page leads with these, so they must keep their original order. */
export function failedCalls<T extends { success: boolean }>(logs: T[]): T[] {
  return logs.filter(l => !l.success)
}

/** Slice a list for display, and say how many rows the collapse is holding back. */
export function previewRows<T>(rows: T[], expanded: boolean, limit: number): { shown: T[]; hidden: number } {
  if (expanded || rows.length <= limit) return { shown: rows, hidden: 0 }
  return { shown: rows.slice(0, limit), hidden: rows.length - limit }
}

/** Label for the control that reveals the rest; empty when there is nothing left to reveal. */
export function hiddenLabel(noun: string, hidden: number, expanded: boolean): string {
  if (expanded || hidden <= 0) return ''
  return `Show all — ${hidden} more ${noun}`
}

/** "social_scalp_scanner" -> "Social scalp scanner". */
function humaniseKey(key: string): string {
  const words = key.replace(/_/g, ' ').trim().toLowerCase()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key
}

/** Cut at a word boundary so a long request reads as a preview rather than a truncated word. */
function preview(text: string, limit = 90): string {
  if (text.length <= limit) return text
  const cut = text.slice(0, limit)
  const space = cut.lastIndexOf(' ')
  return `${(space > 40 ? cut.slice(0, space) : cut).trimEnd()}…`
}

/**
 * FQ-031. The call history showed the raw `task_summary` value, which for many processes is an
 * internal key, not a summary: "agent_flash:agent_narrative:agent_narrative:NVDA:social_scalp_scanner"
 * or the char-count breakdown "system:1557chars; user:18987chars". Turn those into something a
 * reader can act on; when the value genuinely carries no summary, say that instead of printing it.
 */
export function readableSummary(l: { task_summary?: string }): string {
  const raw = (l.task_summary || '').trim()
  if (!raw) return 'No summary recorded'
  // An opaque identifier is not a description of the work. A hex digest or a UUID used to survive as the primary
  // line — the bare-key branch humanised it into "0123456789abcdef…" and the prose branch printed the UUID verbatim
  // (cx-openai-3's CX3-F2 on PR 2676). The raw value is still in Technical detail; the face says what it is.
  if (isOpaqueId(raw)) return 'No summary recorded — an identifier only'
  // A size breakdown of the prompt, not a description of the work.
  if (/^((system|user|assistant):\d+chars;?\s*)+$/i.test(raw)) return 'No summary recorded — request text only'
  // A prompt rather than a summary: 3,744 live rows (2.2% of the table) start with a control directive the model reads
  // ("/no_think Analyze stock catalyst … output JSON only …"), so the operator's line showed an internal token plus a
  // prompt excerpt (cc-deepseek-8's F2 on PR 2676). Same wording as the size breakdown, for the same reason.
  if (/^\/\S/.test(raw) || /\boutput JSON only\b/i.test(raw)) return 'No summary recorded — request text only'
  // A composite internal key: producer : task : (status) : ticker. The segment that says what the work was is the
  // longest one that is not the ticker — a producer prefix is a short word ("agent_flash", "cloud_review") and a
  // trailing status is short too ("deepseek_ok"), while the task is the descriptive one. Taking the LAST segment
  // instead printed the ticker twice ("NVDA · Nvda") and reduced a research task to "Deepseek ok"
  // (cc-deepseek-5's P3 on PR 2676). When nothing but the ticker survives, say so rather than repeat it.
  if (raw.includes(':') && !/\s/.test(raw)) {
    const parts = raw.split(':').filter(Boolean)
    const symbol = parts.find(p => /^[A-Z]{1,5}$/.test(p))
    const task = parts.filter(p => p !== symbol).sort((a, b) => b.length - a.length)[0] ?? ''
    const label = humaniseKey(task)
    if (!task || label.toLowerCase() === String(symbol ?? '').toLowerCase()) return 'No summary recorded'
    return symbol ? `${symbol} · ${label}` : label
  }
  // A bare snake_case task key.
  if (/^[a-z0-9_]+$/.test(raw)) return humaniseKey(raw)
  // Prose already: keep it, shortened to a preview.
  return preview(raw)
}

/**
 * The line a reader sees for a call: which process ran, and what it was doing.
 * FQ-031 — no internal process id and no raw key in this line; both live in the details.
 */
export function callPrimaryText(l: ConsumptionLog): string {
  const name = l.process_name || 'Unnamed process'
  const summary = readableSummary(l)
  // cc-deepseek-8's F3 on PR 2676: the old default rendered ANY unknown trigger as "ran automatically" — a claim about a
  // value the payload does not carry, and the opposite of llm_spend.py's default. Only the two known modes assert.
  // A manual trigger is a MODE, not an identity: any operator, agent or script can start one. "started by you"
  // attributed the call to whoever is reading the screen (codex-cloud round 1 at 0b3eebe29).
  const trigger = l.trigger_mode === 'manual' ? 'started manually'
    : l.trigger_mode === 'automated' ? 'ran automatically'
    : 'trigger not recorded'
  return `${name} · ${summary} · ${trigger}`
}

/** What a developer needs to diagnose the call, shown only when the reader asks for it. */
export function callDetailText(l: ConsumptionLog): string {
  const id = l.process_id ? `Process id: ${l.process_id}` : 'Process id: not recorded'
  return `${id}\nRequest: ${l.task_summary || 'not recorded'}`
}

/** A hex digest or a UUID: an identifier, never a description of work. */
export function isOpaqueId(v: string): boolean {
  const s = String(v || '').trim()
  if (!s) return false
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) return true
  // A long all-hex token that mixes letters and digits; a long run of pure digits is a number, not a digest.
  return /^[0-9a-f]{16,}$/i.test(s) && /[a-f]/i.test(s) && /\d/.test(s)
}

export type ActivityCensus =
  | { state: 'current'; reason: null }
  | { state: 'retained'; reason: string }
  | { state: 'unavailable'; reason: string }

/**
 * Whether the activity log read is a census the page may count from.
 *
 * The banner used to be gated on `logRead.data` alone, so an empty object (the log was not in the response) and a
 * refusal (`{ok: false}`) both rendered "No failed calls in the last 0" — an affirmative healthy window invented from
 * an absence (cx-openai-3's CX3-F1 on PR 2676). A `current` census needs an accepted object that CARRIES a logs
 * array; a failing refresh over retained rows is `retained`; anything else is `unavailable`.
 */
export function activityCensus(read: { data?: unknown; error?: unknown; stale?: unknown } | null | undefined): ActivityCensus {
  const d = read?.data
  const isObj = d != null && typeof d === 'object'
  const row = (isObj ? d : {}) as { ok?: unknown; logs?: unknown; error?: unknown }
  const refused = isObj && row.ok === false
  const err = String(read?.error || '')
  if (refused) {
    return { state: 'unavailable', reason: String(row.error || err || 'the source refused the read') }
  }
  if (!isObj || !Array.isArray(row.logs)) {
    return { state: 'unavailable', reason: err || 'the activity log was not in the response' }
  }
  if (read?.stale === true || err) return { state: 'retained', reason: err || 'the refresh is failing' }
  return { state: 'current', reason: null }
}
