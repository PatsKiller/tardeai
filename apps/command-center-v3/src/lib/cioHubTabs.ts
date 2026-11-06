/**
 * CIO Desk hub tab IA — Intel consolidation (design intel/v001, operator-approved 2026-11-06):
 * Today · Holdings verdicts · My questions · Report. Every former tab keeps a home:
 *  - Overview + Decisions → Today
 *  - Advisory per-holding verdicts → Holdings verdicts
 *  - /cio/questions → My questions (the Home alias stays)
 *  - Research, Capital & Policy and Evidence & Comms → Report (as sub-sections)
 */

export const CIO_HUB_TABS = [
  'today',
  'holdings',
  'questions',
  'report',
] as const

export type CioHubTab = (typeof CIO_HUB_TABS)[number]

export const CIO_HUB_TAB_LABEL: Record<CioHubTab, string> = {
  today: 'Today',
  holdings: 'Holdings verdicts',
  questions: 'My questions',
  report: 'Report',
}

/** Old query-param values → new primary tab (bookmarks / deep links). */
export const CIO_HUB_TAB_ALIASES: Record<string, CioHubTab> = {
  today: 'today',
  holdings: 'holdings',
  questions: 'questions',
  report: 'report',
  // The 5-tab IA (2026-10)
  overview: 'today',
  decisions: 'today',
  research: 'report',
  'capital-policy': 'report',
  'evidence-comms': 'report',
  // Advisory Desk folded in
  advisory: 'holdings',
  verdicts: 'holdings',
  // Legacy 13-tab strip
  'cio-brain': 'report',
  'cio-now': 'today',
  opportunities: 'today',
  'universe-theses': 'report',
  'investment-books': 'report',
  'capital-plan': 'report',
  posture: 'report',
  'operator-policy': 'report',
  evidence: 'report',
  'notification-gate': 'report',
  'telegram-receipts': 'report',
  'senses-evidence': 'report',
  // Evidence subsection deep links (still land on Report)
  brain: 'report',
  'full-brain': 'report',
}

export const CIO_HUB_DEFAULT_TAB: CioHubTab = 'today'

export function resolveCioHubTab(raw: string | null | undefined): CioHubTab {
  const key = String(raw || '').trim()
  if (!key) return CIO_HUB_DEFAULT_TAB
  return CIO_HUB_TAB_ALIASES[key] || CIO_HUB_DEFAULT_TAB
}

/** Optional Report sub-section when aliasing a legacy tab into Report. */
export function resolveEvidenceSubtab(raw: string | null | undefined): string | null {
  const key = String(raw || '').trim()
  const map: Record<string, string> = {
    report: 'report',
    evidence: 'audit',
    'notification-gate': 'notification-gate',
    'telegram-receipts': 'telegram-receipts',
    'senses-evidence': 'senses-evidence',
    brain: 'full-brain',
    'full-brain': 'full-brain',
    'cio-brain': 'full-brain',
    research: 'research',
    'universe-theses': 'research',
    'investment-books': 'research',
    'capital-policy': 'capital-policy',
    'capital-plan': 'capital-policy',
    posture: 'capital-policy',
    'operator-policy': 'capital-policy',
  }
  return map[key] || null
}
