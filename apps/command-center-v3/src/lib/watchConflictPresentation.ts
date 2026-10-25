/** Formatting only. Conflict classification and ordering belong to the engine. */
export type ConflictSide = {source?: string | null; source_label?: string | null; value: unknown; as_of?: string | null; at?: string | null}

export function conflictSource(side: ConflictSide): string {
  if (side.source_label) return side.source_label
  const raw = side.source || ''
  if (/cio|instrument.record/i.test(raw)) return 'CIO record'
  if (/trade.ai/i.test(raw)) return 'Trade AI check'
  if (/[/.@]/.test(raw)) return 'Source label not supplied'
  return raw ? raw.replace(/_/g, ' ') : 'Source not recorded'
}

export function conflictValue(raw: unknown): string {
  if (raw == null || raw === '') return 'Not recorded'
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw.toLocaleString('en-US', {maximumFractionDigits: 2}) : 'Not recorded'
  if (typeof raw === 'boolean') return raw ? 'Yes' : 'No'
  if (typeof raw === 'string') return raw.replace(/_/g, ' ')
  if (Array.isArray(raw)) return raw.map(conflictValue).join(' · ')
  return 'See recorded evidence'
}

export function conflictTime(raw: string | null | undefined): string {
  if (!raw) return 'Time not recorded'
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return `${raw} · time not recorded`
  const time = new Date(raw)
  return Number.isFinite(time.getTime()) ? time.toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }) + ' ET' : 'Time not recorded'
}

/** Labels for the durable ledger state, never inferred from a request or research answer. */
export function reviewPresentation(record: {state?: string} | null | undefined) {
  switch (record?.state) {
    case 'OPEN': return {state: 'open', label: 'Open · awaiting review', pending: false}
    case 'REOPENED': return {state: 'reopened', label: 'Reopened · review needed', pending: false}
    case 'UNDER_REVIEW': return {state: 'under_review', label: 'Review in progress', pending: true}
    case 'DECIDED': return {state: 'decided', label: 'Decision recorded · awaiting engine re-evaluation', pending: true}
    case 'CLEARED': return {state: 'cleared', label: 'Cleared by the engine', pending: false}
    case 'SUPERSEDED': return {state: 'superseded', label: 'Superseded by newer evidence', pending: false}
    default: return {state: 'unknown', label: 'Saved review state unavailable', pending: false}
  }
}

export function conflictGap(raw: string | {reason?: string} | null | undefined): string {
  return typeof raw === 'string' ? raw : raw?.reason || ''
}
