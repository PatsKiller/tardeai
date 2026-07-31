import type { BriefAction, BriefSeverity } from '../components/intelligence/ActionBriefCard'

export type IntelItem = {
  id: string
  source: string
  type: string
  symbol?: string
  title: string
  summary?: string
  severity: BriefSeverity
  confidence: number
  freshnessH: number | null
  model?: string
  lane?: string
  action?: string
  raw: any
  ensemble?: { score: number; decision: 'approve' | 'block'; consensus: boolean; lanes: string[] }
}

export interface ActionBriefModel {
  what: string
  why: string
  who: string
  when: string
  how: string
  severity: BriefSeverity
  symbol?: string
  primaryAction: BriefAction
  secondaryActions: BriefAction[]
}

const SOURCE_LABEL: Record<string, string> = {
  '/api/v2/risk': 'Risk feed',
  '/api/v2/command': 'Command center',
  '/api/v2/open-trades/intelligence': 'Open trades desk',
  '/api/v2/morning-brief': 'Morning brief',
  '/api/v2/hermes/subject-intel-map?type=report': 'External LM report',
  '/api/v2/market-intelligence': 'Market intelligence',
  '/api/v2/trade-ai': 'Trade AI scanner',
  '/api/v2/watchlist/items': 'Watchlist',
  '/api/v2/research-topics': 'Research topics',
  '/api/v2/inference/latest': 'Inference engine',
  '/api/v2/overview': 'Market overview',
  '/api/v2/rotation/summary': 'Rotation desk',
}

const TYPE_LABEL: Record<string, string> = {
  risk: 'Stop / protection',
  'telegram/action': 'Action alert',
  'open-trade': 'Open position',
  'external-lm-report': 'LM report',
  'aegis_thesis': 'Aegis safety rail',
  setup: 'Trade setup',
  watchlist: 'Watchlist candidate',
  'research-gap': 'Research gap',
  'market-signal': 'Market signal',
  'brief-action': 'Brief action',
  'portfolio-news': 'Portfolio news',
  inference: 'Inference',
  regional_impact: 'Regional impact',
  opportunity: 'Opportunity',
  nav_signal: 'NAV / income',
  sector_rotation: 'Sector rotation',
  market_regime: 'Market regime',
}

function humanizeSource(source: string, lane?: string, model?: string): string {
  if (lane) return `${lane}${model ? ` (${model})` : ''}`
  if (SOURCE_LABEL[source]) return SOURCE_LABEL[source]
  if (source.startsWith('/api/')) return TYPE_LABEL[source.split('/').pop() ?? ''] ?? 'Intelligence feed'
  return source.replace(/_/g, ' ')
}

function humanizeType(type: string): string {
  return TYPE_LABEL[type] ?? type.replace(/_/g, ' ').replace(/\//g, ' · ')
}

function agoLabel(hours: number | null, raw?: any): string {
  const iso = raw?.created_at ?? raw?.at ?? raw?.updated_at ?? raw?.generated_at
  if (iso) {
    const t = new Date(iso).getTime()
    if (Number.isFinite(t)) {
      const h = Math.max(0, (Date.now() - t) / 36e5)
      if (h < 1) return 'just now'
      if (h < 48) return `${Math.round(h)}h ago`
      return `${Math.round(h / 24)}d ago`
    }
  }
  if (hours == null) return 'time unknown'
  if (hours < 1) return 'just now'
  if (hours < 48) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

const STRUCTURAL = /^(risk|telegram\/action|open-trade|setup)$/

function qualityWhy(item: IntelItem): string {
  const parts: string[] = []
  if (STRUCTURAL.test(item.type)) {
    if (item.confidence < 0.55) parts.push('Incomplete price/stop data')
    else if (item.confidence < 0.72) parts.push('Marginal breach — confirm before acting')
    else parts.push('Structural fact — verify broker readback')
    if (item.summary) parts.push(item.summary.split('·')[0]?.trim())
    return parts.filter(Boolean).join('. ')
  }
  if (item.summary && item.summary.length > 12) return item.summary.slice(0, 220)
  if (item.confidence < 0.6) return `Low confidence (${Math.round(item.confidence * 100)}%) — verify source before acting`
  if (item.ensemble?.consensus && item.ensemble.decision === 'block') {
    return `Ensemble BLOCK (${item.ensemble.lanes.join('+')}) — do not act without review`
  }
  return item.action ? String(item.action) : 'Signal looks usable — still verify portfolio impact'
}

function howStep(item: IntelItem): string {
  switch (item.type) {
    case 'risk':
    case 'telegram/action':
      return 'Verify live price vs stop on Risk desk, then confirm protection with broker readback'
    case 'open-trade':
      return 'Review open position — cost basis, stop, and operator decision before any change'
    case 'external-lm-report':
      return 'Read report narrative and reconcile against current holdings before acting'
    case 'research-gap':
      return 'Assign research or close the gap before using as a trading signal'
    case 'watchlist':
      return 'Check entry/stop/target freshness and analyst consensus on Watchlist'
    case 'setup':
      return 'Confirm catalyst and entry price are current before proposal'
    case 'aegis_thesis':
      return 'Review Aegis thesis and stop placement — adjust only after quote verification'
    default:
      return item.action ? `Next: ${item.action}` : 'Open detail and verify freshness + portfolio impact'
  }
}

function actionsForIntelItem(item: IntelItem): { primary: BriefAction; secondary: BriefAction[] } {
  const sym = item.symbol
  const symQ = sym ? `?symbol=${encodeURIComponent(sym)}` : ''
  switch (item.type) {
    case 'risk':
    case 'telegram/action':
      return {
        primary: { label: 'Verify stop on Risk desk', url: `/v3/risk${symQ}`, primary: true },
        secondary: [
          { label: 'Open position', url: '/v3/trading?tab=Open+Trades' },
          ...(sym ? [{ label: 'Portfolio', url: `/v3/portfolio` }] : []),
        ],
      }
    case 'open-trade':
      return {
        primary: { label: 'Review open position', url: '/v3/trading?tab=Open+Trades', primary: true },
        secondary: [{ label: 'Risk desk', url: `/v3/risk${symQ}` }],
      }
    case 'external-lm-report':
      return {
        primary: { label: 'Read report & reconcile', url: '/v3/hermes', primary: true },
        secondary: [{ label: 'Portfolio', url: '/v3/portfolio' }],
      }
    case 'research-gap':
      return {
        primary: { label: 'Assign research', url: '/v3/research-intelligence', primary: true },
        secondary: [{ label: 'Topics', url: '/v3/intelligence?tab=research' }],
      }
    case 'watchlist':
      return {
        primary: { label: 'Review watchlist card', url: '/v3/watch?tab=watchlist', primary: true },
        secondary: sym ? [{ label: `Check ${sym}`, url: `/v3/portfolio` }] : [],
      }
    case 'setup':
      return {
        primary: { label: 'Review setup', url: '/v3/rotation', primary: true },
        secondary: [{ label: 'Watchlist', url: '/v3/watch?tab=watchlist' }],
      }
    default:
      return {
        primary: { label: 'Open detail', url: '/v3/intelligence', primary: true },
        secondary: [{ label: 'Portfolio', url: '/v3/portfolio' }],
      }
  }
}

export function briefFromIntelItem(item: IntelItem): ActionBriefModel {
  const { primary, secondary } = actionsForIntelItem(item)
  return {
    what: item.title,
    why: qualityWhy(item),
    who: humanizeSource(item.source, item.lane ?? item.model, item.model),
    when: agoLabel(item.freshnessH, item.raw),
    how: howStep(item),
    severity: item.severity,
    symbol: item.symbol,
    primaryAction: primary,
    secondaryActions: secondary,
  }
}

const INFERENCE_ACTIONS: Record<string, { primary: string; url: string; secondary?: { label: string; url: string }[] }> = {
  aegis_thesis: { primary: 'Review thesis on Risk desk', url: '/v3/risk', secondary: [{ label: 'Hermes briefs', url: '/v3/hermes' }] },
  risk: { primary: 'Verify protection', url: '/v3/risk' },
  opportunity: { primary: 'Review watchlist candidate', url: '/v3/watch?tab=watchlist', secondary: [{ label: 'Rotation desk', url: '/v3/rotation' }] },
  nav_signal: { primary: 'Check portfolio impact', url: '/v3/portfolio' },
  journal_pattern: { primary: 'Review journal pattern', url: '/v3/journal' },
  regional_impact: { primary: 'Check ETF exposure', url: '/v3/portfolio', secondary: [{ label: 'Rotation', url: '/v3/rotation' }] },
  research_gap: { primary: 'Assign research', url: '/v3/research-intelligence' },
  market_regime: { primary: 'Review portfolio posture', url: '/v3/portfolio' },
  sector_rotation: { primary: 'Review rotation ideas', url: '/v3/rotation', secondary: [{ label: 'Watchlist', url: '/v3/watch?tab=watchlist' }] },
}

function inferSeverity(r: any): BriefSeverity {
  if (r.severity === 'critical') return 'critical'
  if (r.severity === 'high') return 'warning'
  if (r.inference_type === 'opportunity') return 'positive'
  return 'info'
}

export function briefFromInference(row: any, runLabel?: string): ActionBriefModel {
  const t = String(row.inference_type || 'inference')
  const sym = /^[A-Z]{1,5}$/.test(String(row.subject || '')) ? row.subject : undefined
  const act = INFERENCE_ACTIONS[t] ?? { primary: 'Review inference', url: '/v3/intelligence' }
  const symQ = sym ? `?symbol=${encodeURIComponent(sym)}` : ''
  const url = act.url.includes('?') ? act.url : `${act.url}${symQ}`

  const body = String(row.body || '').trim()
  const firstSentence = body.match(/^.{20,200}?[.!?](\s|$)/)?.[0]?.trim() ?? body.slice(0, 180)

  return {
    what: row.title || `${humanizeType(t)} signal`,
    why: firstSentence || 'Higher-order inference from Layer-4 reasoning cycle',
    who: humanizeSource('/api/v2/inference/latest', row.source_lane || row.layer, row.source_lane),
    when: `${agoLabel(null, row)}${runLabel ? ` · ${runLabel}` : ''}`,
    how: t === 'aegis_thesis'
      ? 'Verify stop thesis against live quote before adjusting protection'
      : t === 'regional_impact'
        ? 'Check US ETF/holding exposure to the regional theme'
        : 'Confirm inference against portfolio and risk posture before acting',
    severity: inferSeverity(row),
    symbol: sym,
    primaryAction: { label: sym && t === 'aegis_thesis' ? `Review thesis for ${sym}` : act.primary, url, primary: true },
    secondaryActions: (act.secondary ?? []).map(s => ({ ...s, url: s.url })),
  }
}

/** Build legacy SynthesizedReportCard item for side-by-side preview (current UI). */
export function legacyCardFromIntelItem(item: IntelItem) {
  return {
    id: item.id,
    type: item.type,
    channel: item.model || item.lane,
    title: item.title,
    summary: item.summary,
    severity: item.severity,
    symbol: item.symbol,
    symbols: item.symbol ? [item.symbol] : [],
    created_at: item.raw?.created_at ?? item.raw?.at,
    quality_score: Math.round(item.confidence * 100),
    ensemble: item.ensemble ?? null,
  }
}

export function legacyCardFromInference(row: any) {
  const sym = /^[A-Z]{1,5}$/.test(String(row.subject || '')) ? row.subject : undefined
  const t = String(row.inference_type || 'inference')
  const actions: { label: string; url: string }[] = []
  const act = INFERENCE_ACTIONS[t]
  if (act) {
    actions.push({ label: act.primary.replace('Review ', 'Open ').split(' ')[0] === 'Open' ? `Open ${t}` : act.primary, url: act.url })
    act.secondary?.forEach(s => actions.push(s))
  }
  return {
    id: String(row.id),
    type: t.replace(/_/g, ' '),
    channel: `${row.layer ?? 'L4'} · ${row.source_lane || 'local'}`,
    title: row.title,
    summary: row.body || '',
    severity: inferSeverity(row) === 'critical' ? 'critical' : inferSeverity(row) === 'warning' ? 'warning' : 'info',
    symbol: sym,
    symbols: sym ? [sym] : [],
    created_at: row.created_at,
    quality_score: row.confidence != null ? Math.round(Number(row.confidence) * 100) : undefined,
    actions,
  }
}

/** Noisy footer reproducing current Command Center ItemCard (for preview left column). */
export function legacyFooterFromIntelItem(item: IntelItem, estErrorPct: number) {
  return {
    source: item.source,
    estError: estErrorPct,
    action: item.action,
  }
}

export function estErrorFromConfidence(confidence: number): number {
  return Math.max(0.02, Math.min(0.75, 1 - confidence))
}
