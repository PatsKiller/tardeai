import { type VocabConfig } from './journalVocab'

function titleRegime(raw: string): string {
  const t = raw.trim()
  if (!t) return ''
  return t.split(/\s+/).map(w => {
    const lower = w.toLowerCase()
    if (lower === 'vix') return 'VIX'
    return lower.charAt(0).toUpperCase() + lower.slice(1)
  }).join(' ')
}

export const MARKET_REGIME_CONFIG: VocabConfig = {
  storageKey: 'tradeai.marketRegimes.v1',
  defaults: [
    'Trending',
    'Choppy',
    'Ranging',
    'Bullish',
    'Bearish',
    'News Catalyst',
    'High Volatility',
    'Low Volume',
    'Gap Day',
    'Earnings Week',
    'Sector Rotation',
    'Risk-Off',
    'Risk-On',
  ],
  selectPlaceholder: 'Select market regime…',
  addTitle: 'Add market regime',
  addHint: 'Saved for this browser and available in future reviews.',
  addPlaceholder: 'e.g. trending, choppy, news catalyst',
  addConfirmLabel: 'Add regime',
  emptyError: 'Enter a market regime label.',
  normalize: titleRegime,
  loadDbOptions: async () => {
    const r = await fetch('/api/v2/journal/analytics')
    const d = await r.json()
    const rows = d?.data?.by_market_regime ?? d?.by_market_regime ?? []
    return (Array.isArray(rows) ? rows : [])
      .map((row: any) => String(row?.regime ?? row?.market_regime ?? row?.family ?? '').trim())
      .filter((x: string) => x && x.toLowerCase() !== 'unclassified')
  },
}