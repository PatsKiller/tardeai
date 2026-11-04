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
  // A size breakdown of the prompt, not a description of the work.
  if (/^((system|user|assistant):\d+chars;?\s*)+$/i.test(raw)) return 'No summary recorded — request text only'
  // A composite internal key: the ticker (if any) plus the last segment, in plain words.
  if (raw.includes(':') && !/\s/.test(raw)) {
    const parts = raw.split(':').filter(Boolean)
    const symbol = parts.find(p => /^[A-Z]{1,5}$/.test(p))
    const tail = humaniseKey(parts[parts.length - 1] ?? '')
    return symbol ? `${symbol} · ${tail}` : tail
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
  const trigger = l.trigger_mode === 'manual' ? 'started by you' : 'ran automatically'
  return `${name} · ${summary} · ${trigger}`
}

/** What a developer needs to diagnose the call, shown only when the reader asks for it. */
export function callDetailText(l: ConsumptionLog): string {
  const id = l.process_id ? `Process id: ${l.process_id}` : 'Process id: not recorded'
  return `${id}\nRequest: ${l.task_summary || 'not recorded'}`
}
