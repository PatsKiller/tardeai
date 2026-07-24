export const SHARED_CONTEXT_KEY = 'portfolio.shared-symbol-context.v1'
export const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
export const EVENT_KEY = 'portfolio.reentry.event-classifications.v1'
export const DISPOSITION_KEY = 'portfolio.reentry.dispositions.v1'
export const EXIT_CACHE_KEY = 'portfolio.reentry.exit-universe.v1'
export const RESISTANCE_KEY = 'portfolio.reentry.resistance.v1'

export const REENTRY_FLAGS = ['growth', 'compounding', 'dividend', 'swing', 'short', 'defensive', 'hedge', 'rotation'] as const
export const EXIT_TYPES = ['stopped_out', 'discretionary_sale', 'partial_trim', 'rebalance', 'tax_sale', 'rotation', 'day_trade', 'momentum_scalp', 'assignment_expiration', 'not_relevant', 'other'] as const

export type ReEntryFlag = typeof REENTRY_FLAGS[number]
export type ReEntryMandate = {
  mandate: 'core' | 'satellite' | 'hedge' | 'unclassified'
  flags: Record<ReEntryFlag, boolean>
  targetAccount: string
  targetWeightPct: number | null
  priority: 'HIGH' | 'NORMAL' | 'LOW'
  thesis: string
  updatedAt: string
}
export type ReEntryEvent = { eventType: typeof EXIT_TYPES[number]; reason: string; notes: string; updatedAt: string }
export type ReEntryDisposition = { state: 'review' | 'monitor' | 'suppressed'; reason: string; updatedAt: string }
export type ExitEvidenceField = 'account' | 'trade_date' | 'trade_time' | 'quantity' | 'price' | 'proceeds_usd' | 'action' | 'description'
export type ExitEvidenceRow = {
  event_key: string
  symbol: string
  account?: string | null
  trade_date?: string | null
  trade_time?: string | null
  quantity?: number | null
  price?: number | null
  proceeds_usd?: number | null
  action?: string | null
  description?: string | null
  import_source?: string | null
  matched_event_id?: number | null
  reconciliation?: string | null
  event_status?: string | null
  completion_status?: string | null
  operator_status?: string | null
  external_id?: string | null
  field_sources?: Partial<Record<ExitEvidenceField, string>>
  evidence_gaps?: string[]
  derived_fields?: string[]
}

export type ClassificationState = 'CLASSIFIED' | 'AUTO-TAGGED' | 'UNCLASSIFIED'

export function unwrap(value: any): any {
  let result = value
  for (let index = 0; index < 3 && result?.data && typeof result.data === 'object'; index += 1) result = result.data
  return result ?? {}
}
export function prefValue(value: any): any { const payload = unwrap(value); return payload?.value ?? payload }
export function prefMap(value: any): Record<string, any> { const payload = prefValue(value); return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {} }
export function finite(...values: any[]): number | null { for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value); return null }
export function text(...values: any[]): string { for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim(); return '' }
export function defaultMandate(): ReEntryMandate { return { mandate: 'unclassified', flags: Object.fromEntries(REENTRY_FLAGS.map(flag => [flag, false])) as Record<ReEntryFlag, boolean>, targetAccount: '', targetWeightPct: null, priority: 'NORMAL', thesis: '', updatedAt: '' } }
export function defaultEvent(): ReEntryEvent { return { eventType: 'other', reason: '', notes: '', updatedAt: '' } }
export function defaultDisposition(): ReEntryDisposition { return { state: 'review', reason: '', updatedAt: '' } }
export function rowShares(row: ExitEvidenceRow): number | null { const value = finite(row.quantity); return value === null ? null : Math.abs(value) }
export function rowPrice(row: ExitEvidenceRow): number | null { const direct = finite(row.price); if (direct !== null) return direct; const shares = rowShares(row); const proceeds = finite(row.proceeds_usd); return shares && proceeds !== null ? Math.abs(proceeds) / shares : null }

export function inferExitEvent(row: ExitEvidenceRow): ReEntryEvent {
  const evidence = `${row.action ?? ''} ${row.description ?? ''} ${row.event_status ?? ''} ${row.completion_status ?? ''} ${row.operator_status ?? ''}`
  if (/\b(stop(?:ped)?|stop[- ]loss|trailing stop|protective stop)\b/i.test(evidence)) return { eventType: 'stopped_out', reason: text(row.description, 'Broker/journal evidence indicates a stop execution.'), notes: 'Auto-tagged from broker action/description. Review and edit if needed.', updatedAt: '' }
  if (/\b(partial|trim|reduce|scaled? out)\b/i.test(evidence)) return { eventType: 'partial_trim', reason: text(row.description, 'Broker/journal evidence indicates a partial reduction.'), notes: 'Auto-tagged from broker action/description.', updatedAt: '' }
  if (/\b(assign(?:ed|ment)|expire(?:d|ation))\b/i.test(evidence)) return { eventType: 'assignment_expiration', reason: text(row.description, 'Option assignment or expiration event.'), notes: 'Auto-tagged from broker/journal description.', updatedAt: '' }
  if (/\b(day[ -]?trade|intraday|scalp|round trip)\b/i.test(evidence)) return { eventType: 'momentum_scalp', reason: text(row.description, 'Detected short-duration tactical trade.'), notes: 'Auto-tagged from journal/broker description.', updatedAt: '' }
  if (/\b(sell|sold|closed|exit)\b/i.test(evidence)) return { eventType: 'discretionary_sale', reason: text(row.description, 'Broker/journal evidence indicates a discretionary sale.'), notes: 'Auto-tagged from broker action/description.', updatedAt: '' }
  return { eventType: 'other', reason: text(row.description, 'Exit reason is not explicit in source data.'), notes: '', updatedAt: '' }
}

export function normalizedMandate(value: any): ReEntryMandate {
  return { ...defaultMandate(), ...(value ?? {}), flags: { ...defaultMandate().flags, ...(value?.flags ?? {}) } }
}
export function normalizedEvent(row: ExitEvidenceRow, value: any): ReEntryEvent {
  const inferred = inferExitEvent(row)
  const saved = { ...defaultEvent(), ...(value ?? {}) }
  return saved.updatedAt || saved.reason || saved.eventType !== 'other' ? saved : inferred
}
export function normalizedDisposition(value: any): ReEntryDisposition { return { ...defaultDisposition(), ...(value ?? {}) } }

export function isOperatorClassified(mandate: ReEntryMandate, events: ReEntryEvent[], dispositions: ReEntryDisposition[]): boolean {
  return Boolean(
    mandate.updatedAt
    || mandate.mandate !== 'unclassified'
    || REENTRY_FLAGS.some(flag => mandate.flags[flag])
    || mandate.targetAccount
    || mandate.targetWeightPct !== null
    || mandate.thesis
    || events.some(event => Boolean(event.updatedAt))
    || dispositions.some(disposition => Boolean(disposition.updatedAt)),
  )
}

export function classificationState(mandate: ReEntryMandate, rows: ExitEvidenceRow[], eventMap: Record<string, any>, dispositionMap: Record<string, any>, shared?: any): ClassificationState {
  const events = rows.map(row => normalizedEvent(row, eventMap[row.event_key]))
  const dispositions = rows.map(row => normalizedDisposition(dispositionMap[row.event_key]))
  if (isOperatorClassified(mandate, events, dispositions)) return 'CLASSIFIED'
  if (shared?.classification_status === 'AUTO_TAGGED' || rows.some(row => inferExitEvent(row).eventType !== 'other')) return 'AUTO-TAGGED'
  return 'UNCLASSIFIED'
}

export function suggestedNotes(row: ExitEvidenceRow, shared: any): string {
  const annotations: any[] = Array.isArray(shared?.annotations) ? shared.annotations : []
  const lines = annotations.slice(0, 8).map(item => `${text(item.label)}${text(item.detail) ? ` — ${text(item.detail)}` : ''}`)
  if (!lines.length) {
    const inferred = inferExitEvent(row)
    if (inferred.notes) lines.push(inferred.notes)
  }
  return lines.join('\n')
}

export function classificationLabel(state: ClassificationState): string {
  return state === 'AUTO-TAGGED' ? 'AUTO-TAGGED' : state
}

export async function saveUiPref(key: string, value: any): Promise<void> {
  const response = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, value }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed')
}
