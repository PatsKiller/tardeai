import { type VocabConfig } from './journalVocab'

function titlePsychology(raw: string): string {
  const t = raw.trim()
  if (!t) return ''
  if (t.toLowerCase() === 'fomo') return 'FOMO'
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase()
}

export const PSYCHOLOGY_BEFORE_CONFIG: VocabConfig = {
  storageKey: 'tradeai.psychologyBefore.v1',
  defaults: [
    'Calm',
    'Confident',
    'Impatient',
    'FOMO',
    'Distracted',
    'Overconfident',
    'Anxious',
    'Hesitant',
    'Excited',
    'Revenge',
  ],
  selectPlaceholder: 'Select pre-trade psychology…',
  addTitle: 'Add psychology tag',
  addHint: 'Saved for this browser and available in future reviews.',
  addPlaceholder: 'e.g. calm, confident, FOMO',
  addConfirmLabel: 'Add tag',
  emptyError: 'Enter a psychology label.',
  normalize: titlePsychology,
  loadDbOptions: async () => {
    const r = await fetch('/api/v2/journal/analytics')
    const d = await r.json()
    const rows = d?.data?.emotion_before ?? d?.emotion_before ?? []
    return (Array.isArray(rows) ? rows : [])
      .map((row: any) => String(row?.emotion_before ?? row?.tag ?? '').trim())
      .filter(Boolean)
  },
}