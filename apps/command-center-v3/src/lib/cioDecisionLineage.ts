export const CIO_LINEAGE_STATES = [
  'LIVE', 'PARTIAL', 'UNWIRED', 'NOT_RUN', 'NOT_APPLICABLE', 'PENDING', 'UNAVAILABLE', 'UNKNOWN',
] as const

export type CioLineageState = typeof CIO_LINEAGE_STATES[number]

export function decisionLineageHref(decisionId: string): string {
  // BrowserRouter owns basename="/v3". Internal links must be basename-relative.
  return `/cio?tab=evidence-comms&sub=decision-lineage&decision=${encodeURIComponent(decisionId)}`
}

export function isCioLineageState(value: unknown): value is CioLineageState {
  return typeof value === 'string' && (CIO_LINEAGE_STATES as readonly string[]).includes(value)
}
