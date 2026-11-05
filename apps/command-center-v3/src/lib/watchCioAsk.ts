/** Watch "Ask the CIO" question and the card status after the existing ask endpoint answers.
 *  Display only. The ask endpoint owns identity and budget. Answer prose is never parsed for a stance. */
import type { ProspectRow } from './watchProspectsModel.ts'

/** Same ceiling as askCioModel.MAX_QUESTION_CHARS. Kept local so this file stays a plain node test. */
export const WATCH_ASK_QUESTION_CHARS = 2000

export type WatchAskPhase = 'asked' | 'answering' | 'answered' | 'failed'

export type WatchAskView = {
  phase: WatchAskPhase
  message: string
  threadId: string | null
  stance: string | null
  stanceGap: string | null
  queueNote: string | null
}

export const STANCE_GAP = 'CIO stance was not in this answer.'

type AskRow = Pick<ProspectRow, 'symbol' | 'stance' | 'conviction' | 'why' | 'summary' | 'price' | 'price_as_of' | 'conflicts' | 'next_action'>

export function watchAskQuestion(row: AskRow): string {
  const lines = [`Review ${row.symbol} for my watchlist: stance, conviction, what would change it`]
  if (row.stance) lines.push(`Card stance: ${row.stance}`)
  if (row.conviction != null && Number.isFinite(row.conviction)) lines.push(`Card conviction: ${row.conviction}`)
  if (row.why) lines.push(`Why: ${row.why}`)
  if (row.summary) lines.push(`Summary: ${row.summary}`)
  if (row.next_action?.reason) lines.push(`Next: ${row.next_action.reason}`)
  const conflicts = (row.conflicts || []).map(item => item.summary).filter(Boolean).slice(0, 3)
  if (conflicts.length) lines.push(`Conflicts: ${conflicts.join('; ')}`)
  if (row.price != null && Number.isFinite(row.price)) {
    lines.push(`Price: ${row.price}${row.price_as_of ? ` as of ${row.price_as_of}` : ''}`)
  }
  return clipQuestion(lines.join('\n'))
}

export function clipQuestion(text: string): string {
  if (text.length <= WATCH_ASK_QUESTION_CHARS) return text
  return `${text.slice(0, WATCH_ASK_QUESTION_CHARS - 1).trimEnd()}…`
}

/** A stance is shown only when the ask payload carries a structured string. */
export function stanceFromAskPayload(payload: unknown): { stance: string | null; stanceGap: string | null } {
  if (!payload || typeof payload !== 'object') return { stance: null, stanceGap: STANCE_GAP }
  const stance = (payload as { stance?: unknown }).stance
  if (typeof stance === 'string' && stance.trim()) return { stance: stance.trim(), stanceGap: null }
  return { stance: null, stanceGap: STANCE_GAP }
}

export function askedView(): WatchAskView {
  return { phase: 'asked', message: 'Asked', threadId: null, stance: null, stanceGap: null, queueNote: null }
}

export function answeringView(): WatchAskView {
  return { phase: 'answering', message: 'Answering', threadId: null, stance: null, stanceGap: null, queueNote: null }
}

export function finishAsk(args: {
  askOk: boolean
  askMessage: string
  threadId?: string | null
  stance?: string | null
  queueMessage?: string | null
}): WatchAskView {
  const queueNote = args.queueMessage || null
  if (!args.askOk || !args.threadId) {
    return {
      phase: 'failed',
      message: args.askMessage || 'The CIO did not return a thread.',
      threadId: null,
      stance: null,
      stanceGap: null,
      queueNote,
    }
  }
  const stance = args.stance?.trim() || null
  return {
    phase: 'answered',
    message: 'Answered',
    threadId: args.threadId,
    stance,
    stanceGap: stance ? null : STANCE_GAP,
    queueNote,
  }
}
