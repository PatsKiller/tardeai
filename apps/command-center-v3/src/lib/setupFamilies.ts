import { type VocabConfig } from './journalVocab'

export const DEFAULT_SETUP_FAMILIES = [
  'Scalp',
  'Momentum',
  'Mean Reversion',
  'Swing',
  'Core Position',
  'Value',
  'Catalyst',
  'Income',
  'Breakout',
  'Pullback',
  'Trend Follow',
  'Earnings Play',
  'Dividend Play',
  'Income',
  'Options',
  'Other',
] as const

export const SETUP_FAMILY_CONFIG: VocabConfig = {
  storageKey: 'tradeai.setupFamilies.v1',
  defaults: DEFAULT_SETUP_FAMILIES,
  selectPlaceholder: 'Select strategy / setup family…',
  addTitle: 'Add setup family',
  addHint: 'New families are saved for this browser and appear in the dropdown for all future reviews.',
  addPlaceholder: 'e.g. Pullback MACD, Core Position, Day Trade',
  addConfirmLabel: 'Add family',
  emptyError: 'Enter a name for the new setup family.',
  loadDbOptions: async () => {
    const r = await fetch('/api/v2/journal/analytics')
    const d = await r.json()
    const rows = d?.data?.by_setup_family ?? d?.by_setup_family ?? []
    return (Array.isArray(rows) ? rows : [])
      .map((row: any) => String(row?.family ?? row?.setup_family ?? '').trim())
      .filter((f: string) => f && f.toLowerCase() !== 'unclassified')
  },
}