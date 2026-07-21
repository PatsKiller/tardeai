import { useState, type CSSProperties } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  buttonStyle,
  confidenceTooltip,
  planValidatedTooltip,
  enrichedTooltip,
  cioViewTooltip,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  cioRecColor,
  targetVsStreetLabel,
  dataQualityFlags,
  actionReasoning,
  deriveSecondaryActions,
  rrTooltip,
  type CardActionType,
} from '../lib/watchlistCardAction'
import { WL, heroStateStyle, verdictWord, numStyle } from '../lib/watchlistCardTokens'
import CountryFlag from './CountryFlag'
import { LadderLine, VerdictBanner } from './primitives/cardPrimitives'
import { type ProposalAccount, type RiskPct } from '../lib/watchlistProposeSizing'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import SizingTable from './SizingTable'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import CloudLlmRunButtons from './CloudLlmRunButtons'
import {
  resolvePlanVolContext,
  stopVolatilityLine,
  stopVolatilityTooltip,
  volatilityBadgeStyle,
  volatilityBadgeText,
  volatilityBadgeTooltip,
} from '../lib/watchlistVolatility'

// Security Card v3 — dashboard condensation. Two tight top lines (header, single-line banner)
// over a 2×2 module grid (Trade Plan ⟷ Sizing & Account Risk, Conviction ⟷ Intelligence) and one
// footer strip. One surface, hairline separations; the banner stays the only tinted element and
// color remains signal-only. Expander bodies render full-width below their grid row.

function ago(v: any) {
  if (!v) return ''
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return ''
  const h = Math.round((Date.now() - t) / 36e5)
  if (h < 1) return 'just now'
  if (h < 48) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

function money(v: any) {
  const n = Number(v)
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : '—'
}

function pct(from: number | null, to: number | null): string | null {
  if (from == null || to == null || !from) return null
  const p = ((to - from) / from) * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%`
}

function fmtPc(v: any): string {
  if (v == null) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

/** Quiet inline expander toggle. */
function Expander({ open, onToggle, label }: { open: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={e => { e.stopPropagation(); onToggle() }}
      style={{ fontSize: 10.5, fontWeight: 700, color: WL.text.dim, background: 'none', border: 'none', cursor: 'pointer', padding: 0, letterSpacing: 'normal', textTransform: 'none' }}
    >{label} {open ? '▴' : '▾'}</button>
  )
}

const moduleLabel: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase',
  color: WL.text.dim, marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
}

const LLM_NAMES: Record<string, string> = { grok: 'Grok', chatgpt: 'ChatGPT', claude: 'Claude' }
const llmName = (lane?: string) => LLM_NAMES[lane || ''] || lane || 'LLM'

const linkStyle: CSSProperties = {
  color: WL.text.secondary,
  textDecoration: 'underline',
  textDecorationColor: 'rgba(148,163,184,.35)',
  textUnderlineOffset: 2,
}

const ctxLine: CSSProperties = { fontSize: 11, color: WL.text.secondary, lineHeight: 1.55 }
const ctxKey: CSSProperties = { color: WL.text.dim, fontWeight: 700 }

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
}

function cleanNewsSource(raw?: string): string {
  if (!raw) return 'news'
  return String(raw)
    .replace(/^(google_news|yahoo_rss|finviz_news|hermes):\s*/i, '')
    .replace(/^hermes\s*·\s*/i, '')
    .trim() || 'news'
}

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1).trimEnd()}…`
}

function rrColor(rr: number): string {
  return rr >= 2 ? WL.signal.teal : rr >= 1.5 ? WL.signal.amber : WL.signal.red
}

export type WatchlistCardProps = {
  it: any
  adv?: any
  sc?: any
  pa?: any
  outcome?: any
  llms: any[]
  fv?: any
  reportEntry?: any
  paMap: Record<string, any>
  /** Proposal accounts for the Sizing & Account Risk module (from /api/v2/proposal-accounts). */
  accounts?: ProposalAccount[]
  /** Current per-account positions in this symbol (from /api/v2/portfolio/holdings). */
  heldPositions?: { account: string; shares: number; market_value: number }[]
  /** Desk concentration policy from proposal-accounts (max % of cash deployed per position). */
  maxDeployPctOfCash?: number
  ensOpen: boolean
  refreshState?: string
  onDrill: (ctx: DrillContext) => void
  onToggleStar: (e: React.MouseEvent) => void
  onRefresh: (e: React.MouseEvent) => void
  onToggleEns: () => void
  isStarred: boolean
  onPropose?: (it: any, opts?: { account_key?: string; risk_pct?: RiskPct }) => void
  onAdjust?: (it: any) => void
  onBuildPlan?: (symbol: string) => void
  onOpenDesk?: (symbol: string) => void
  onCioDone?: () => void
}

export default function WatchlistCard({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap, accounts, heldPositions, maxDeployPctOfCash,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
  onPropose, onAdjust, onBuildPlan, onOpenDesk, onCioDone,
}: WatchlistCardProps) {
  const enriched = !!it.last_enriched_at
  const stale = enriched && (Date.now() - new Date(it.last_enriched_at).getTime()) > 3600 * 1000
  const needsRefresh = watchlistNeedsRefresh(it, stale)
  const street = pa?.target != null && Number(pa.target) > 0 ? Number(pa.target) : null
  const entry = it.entry_limit != null ? Number(it.entry_limit) : null
  const stop = it.entry_stop != null ? Number(it.entry_stop) : null
  const planTarget = it.entry_target != null ? Number(it.entry_target) : null
  const rr = it.entry_rr != null ? Number(it.entry_rr)
    : (entry && stop && planTarget && entry > stop && planTarget > entry ? (planTarget - entry) / (entry - stop) : null)
  const hasPlan = entry != null && stop != null
  const volCtx = resolvePlanVolContext(it, fv, entry, stop)
  const volBadge = volatilityBadgeStyle(volCtx.band)
  const ladder = entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null
  const warns = entry != null || stop != null
    ? planWarnings({
      entry, stop, planTarget, rr, pctCash: null, streetTarget: street,
      analystUpside: pa?.upside != null ? Number(pa.upside) : null,
      stopAtrMult14: volCtx.stopAtrMult14, stopAtrMult20: volCtx.stopAtrMult20,
      atrPct14: volCtx.atrPct14, atrPct20: volCtx.atrPct20,
    })
    : []
  const stopVolLine = stopVolatilityLine(volCtx)
  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''
  const action = deriveRecommendedAction({
    it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh,
  })
  const heroState = heroStateStyle(action.verdict, action.urgency)
  const focusIdx = ladderFocusIndex(ladder)
  const cioRec = it.latest_recommendation
    ? String(it.latest_recommendation).replace(/_/g, ' ')
    : null
  const cioLabel = cioRec ?? (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const cioAccent = cioRecColor(it.latest_recommendation || cioLabel)
  const confNum = it.research_confidence != null
    ? Number(it.research_confidence)
    : (it.hermes_score_components?._confidence != null ? Number(it.hermes_score_components._confidence) : null)
  // synthesis age first — the CIO row's "validated" is the CIO check, not the entry plan (v4 parity)
  const validatedVal = ago(it.synthesis_updated_at) || ago(it.entry_planned_at) || ago(it.last_validated_at) || null

  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [ladderOpen, setLadderOpen] = useState(false)
  const [ctxOpen, setCtxOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  const drillCtx: DrillContext = {
    title: `${it.symbol}${it.hermes_rank != null ? ` — Hermes #${it.hermes_rank}` : ''}`,
    subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.status}`,
    endpoint: `/api/v2/hermes/intel/${it.symbol}`,
    rows: [adv ? { ...it, setup_advisory_note: adv.note, setup_advisory_flag: adv.advisory_flag, current_rsi: adv.rsi, rsi_band: adv.band } : it],
  }

  const originLabel = ({ trade_ai_screener: 'Screener', agent_discovery: 'AI', operator: 'Operator', hermes: 'Hermes', portfolio: 'Portfolio', social: 'Social' } as Record<string, string>)[it.origin_system || ''] || (it.origin_system || 'screener')
  const sectorLine = sc?.sector || it.profile_sector
    ? [sc?.sector || it.profile_sector, sc?.industry || it.profile_industry].filter(Boolean).join(' / ')
    : null
  const companyName = sc?.name || sc?.company_name || it.profile_name || null
  const tenureDays = it.first_seen_at
    ? Math.max(0, Math.floor((Date.now() - new Date(it.first_seen_at).getTime()) / 864e5))
    : null
  const provenanceText = [
    companyName,
    it.hermes_rank != null ? `Hermes #${it.hermes_rank}` : null,
    originLabel,
    sectorLine,
    tenureDays != null && tenureDays > 0 ? `on watchlist ${tenureDays}d` : null,
  ].filter(Boolean).join(' · ')
  // Live portfolio only. outcomes.held is purchase/sale history and must NOT drive HELD.
  const isHeld = !!it.in_portfolio
  const heldTip = 'Currently held in live portfolio'

  const companyDesc = sc?.description || it.profile_description || null
  const allNews: any[] = sc?.news ?? []
  const topNews = allNews[0] ?? null
  const moreNews = allNews.slice(1, 4)
  const zoneLo = it.entry_zone_low != null ? Number(it.entry_zone_low) : null
  const zoneHi = it.entry_zone_high != null ? Number(it.entry_zone_high) : null
  const hasZone = zoneLo != null && zoneHi != null && Number.isFinite(zoneLo) && Number.isFinite(zoneHi)
  const setupLabel = it.entry_setup ? String(it.entry_setup).replace(/_/g, ' ') : null
  const urgencyLabel = it.entry_urgency
    ? String(it.entry_urgency).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    : null
  const strategyLabel = it.strategy_type ? String(it.strategy_type).replace(/_/g, ' ') : null
  const entryTag = it.entry_tag ? String(it.entry_tag).replace(/_/g, ' ').toLowerCase() : null
  const idealEntry = it.ideal_entry != null && Number(it.ideal_entry) > 0 ? Number(it.ideal_entry) : null
  const entryConf = it.entry_confidence != null ? Number(it.entry_confidence) : null

  const entryLine = [
    strategyLabel ? `${strategyLabel} strategy` : null,
    setupLabel && setupLabel !== strategyLabel ? `${setupLabel} setup` : null,
    urgencyLabel,
    !hasZone && !hasPlan ? 'zone pending entry planner' : null,
    idealEntry != null ? `ideal ${money(idealEntry)}` : null,
    entryConf != null ? `plan conf ${entryConf.toFixed(2)}` : null,
    entryTag && !['ok', 'ready'].includes(entryTag) ? entryTag : null,
  ].filter(Boolean).join(' · ')

  const reasoning = actionReasoning({ it, pa, adv, action, hasPlan, rr, stale, enriched })
  const dqFlags = dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt, adv })
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const analystDivergent = pa?.divergence === 'divergent'
  const secondaryActions = deriveSecondaryActions(action, hasPlan)

  // Rule of one — the banner why-line owns the blocking reason; nothing repeats it below.
  const whyParts: string[] = []
  if (action.warning?.text) whyParts.push(action.warning.text)
  if (reasoning && reasoning !== action.warning?.text) whyParts.push(reasoning)
  const whyLine = whyParts.join(' · ')

  const tightStopWarn = warns.find(w => w.text.includes('ATR₂₀') || w.text.includes('ATR₁₄')) ?? null
  const planNote = tightStopWarn
    ? { text: tightStopWarn.text, color: tightStopWarn.color }
    : (!action.warning && action.verdict !== 'FIX' && warns.length)
      ? { text: warns[0].text, color: warns[0].color }
      : null

  const hasEvidence = !!(it.synthesis_evidence?.length || action.detail || adv?.note)

  const executeAction = (e: React.MouseEvent, type: CardActionType) => {
    e.stopPropagation()
    setMenuOpen(false)
    switch (type) {
      case 'REFRESH_DATA': onRefresh(e); break
      case 'VIEW_INTEL':
      case 'REVIEW_SETUP': onDrill(drillCtx); break
      case 'PROPOSE_ENTRY': onPropose?.(it); break
      case 'ADJUST_PLAN':
      case 'REVIEW_EXIT': onAdjust?.(it); break
      case 'BUILD_PLAN': onBuildPlan?.(it.symbol); break
      case 'WATCH_ON_DESK':
      case 'QUEUE_PROPOSAL': onOpenDesk?.(it.symbol); break
      case 'REC_INTEL': window.location.href = `/v3/rec-intel?symbol=${encodeURIComponent(it.symbol)}`; break
      case 'ENSEMBLE': onToggleEns(); break
      default: break
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    if (!action.allowPrimary) return
    executeAction(e, action.type)
  }

  const inlineSecondary = secondaryActions[0] ?? null
  const menuItems: { type: CardActionType; label: string }[] = []
  const addMenuItem = (type: CardActionType, label: string) => {
    if (type === action.type) return
    if (inlineSecondary && type === inlineSecondary.type) return
    if (!menuItems.some(m => m.type === type)) menuItems.push({ type, label })
  }
  for (const sec of secondaryActions.slice(1)) addMenuItem(sec.type, sec.label)
  addMenuItem('VIEW_INTEL', 'Intel drawer')
  addMenuItem('REC_INTEL', 'Rec-Intel')
  addMenuItem('ENSEMBLE', ensOpen ? 'Hide ensemble' : 'Ensemble check')
  if (hasPlan) addMenuItem('WATCH_ON_DESK', 'Monitor on desk')

  const worstDq = dqFlags.find(f => f.severity === 'red')
    ?? dqFlags.find(f => f.label.startsWith('Tight stop'))
    ?? dqFlags[0] ?? null
  const dqColor = worstDq ? (worstDq.severity === 'red' ? WL.signal.red : WL.signal.amber) : WL.signal.teal
  const dqText = worstDq
    ? `${worstDq.label}${dqFlags.length > 1 ? ` · ${dqFlags.length - 1} more issue${dqFlags.length > 2 ? 's' : ''}` : ''}`
    : `Data healthy — enriched ${ago(it.last_enriched_at) || 'recently'}`
  const dqTip = dqFlags.length
    ? dqFlags.map(f => f.label).join('\n')
    : [enrichedTooltip(it), planValidatedTooltip(it)].join('\n')

  const convictionMeta = [
    it.models_agree === true ? 'Grok + ChatGPT agree' : it.models_agree === false ? 'models split' : null,
    validatedVal ? `validated ${validatedVal}` : null,
    (it.cio_model_used || it.entry_model) ? `${it.cio_model_used || it.entry_model}` : null,
  ].filter(Boolean).join(' · ')
  const confBand = confNum == null ? null : confNum >= 0.7 ? 'High' : confNum >= 0.5 ? 'Moderate' : 'Low'
  const confColor = confNum == null ? WL.text.dim : confNum >= 0.7 ? WL.signal.teal : confNum >= 0.5 ? WL.signal.amber : WL.signal.red
  const cioNote = it.synthesis_narrative_snip ? truncate(String(it.synthesis_narrative_snip), 220) : null
  const cioNoteAgeH = it.synthesis_updated_at
    ? (Date.now() - new Date(it.synthesis_updated_at).getTime()) / 36e5
    : null
  const cioNoteAge = cioNoteAgeH != null && Number.isFinite(cioNoteAgeH) ? ago(it.synthesis_updated_at) : null
  const cioNoteStale = cioNoteAgeH != null && cioNoteAgeH > 24

  const canPropose = action.type === 'PROPOSE_ENTRY'

  // "+X% since added" — first_seen_price is stamped at first enrichment (backfilled for the
  // Hermes top-250); omitted rather than faked when no baseline exists.
  const sinceAdded = (it.first_seen_price != null && Number(it.first_seen_price) > 0 && it.price != null)
    ? ((Number(it.price) - Number(it.first_seen_price)) / Number(it.first_seen_price)) * 100
    : null
  // Next scheduled earnings from symbol_profiles.next_earnings_date (earnings_enrich cron,
  // held + Hermes-top-200 scope). Amber inside 14 days — that's an event window, not a defect.
  // Parse the date-ONLY string as local, not new Date(iso): UTC-midnight parsing rendered
  // 2026-09-03 as "Sep 2" in ET (audit finding 2026-07-03).
  const nextEarningsDate = (() => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(it.next_earnings_date ?? ''))
    return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12) : null
  })()
  const nextEarningsDays = nextEarningsDate && Number.isFinite(nextEarningsDate.getTime())
    ? Math.round((nextEarningsDate.getTime() - Date.now()) / 864e5)
    : null
  const nextEarningsLabel = nextEarningsDate && nextEarningsDays != null && nextEarningsDays >= 0
    ? nextEarningsDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null
  const nextEarningsValid = nextEarningsDays != null && nextEarningsDays >= 0 && nextEarningsDays <= 120
  const planSubLabel: CSSProperties = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: WL.text.dim, textTransform: 'uppercase' }

  return (
    <div
      onClick={() => onDrill(drillCtx)}
      style={{
        background: WL.surface.card,
        border: `1px solid ${WL.surface.edge}`,
        borderLeft: `3px solid ${heroState.rail}`,
        borderRadius: WL.card.radius,
        cursor: 'pointer',
        boxShadow: WL.card.shadow,
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'hidden',
        color: WL.text.primary,
      }}
    >
      {/* ① Header — one line */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, padding: '11px 16px 9px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: 0, color: isStarred ? WL.signal.amber : WL.text.dim }}
          >{isStarred ? '★' : '☆'}</button>
          <span style={{ ...numStyle, fontWeight: 800, fontSize: 21 }}>{it.symbol}</span>
          <CountryFlag symbol={it.symbol} country={it.country} countryName={it.country_name} size={22} />
          {isHeld && (
            <span title={heldTip} style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.08em', color: WL.signal.amber, border: '1px solid rgba(245,166,35,.35)', borderRadius: 4, padding: '1px 5px', flexShrink: 0 }}>HELD</span>
          )}
          <span onClick={e => e.stopPropagation()} style={{ flexShrink: 0 }}><ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={false} /></span>
          {analystDivergent && <span style={{ fontSize: 10, color: WL.signal.red, fontWeight: 700, flexShrink: 0 }}>CIO ≠ Street</span>}
          {provenanceText && (
            <span style={{ fontSize: 11, color: WL.text.dim, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={provenanceText}>{provenanceText}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
          <div style={{ textAlign: 'right', minWidth: 0 }}>
            <div style={{ ...numStyle, fontSize: 18, fontWeight: 800 }}>{it.price != null ? money(it.price) : '—'}</div>
            {it.change_pct != null && (
              <div style={{ ...numStyle, fontSize: 11.5, fontWeight: 700, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
                {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
              </div>
            )}
            {volatilityBadgeText(volCtx) && (
              <div
                title={volatilityBadgeTooltip(volCtx)}
                style={{
                  marginTop: 5,
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: '.03em',
                  lineHeight: 1.4,
                  color: volBadge.color,
                  border: `1px solid ${volBadge.border}`,
                  background: volBadge.bg,
                  borderRadius: 4,
                  padding: '3px 6px',
                  whiteSpace: 'normal',
                  cursor: 'help',
                }}
              >
                {volatilityBadgeText(volCtx)}
              </div>
            )}
          </div>
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz + re-queue synthesis"
            style={{
              fontSize: 10.5, fontWeight: 600, padding: '4px 10px', borderRadius: 5,
              cursor: refreshState ? 'wait' : 'pointer', border: '1px solid rgba(148,163,184,.25)',
              background: 'transparent', color: needsRefresh ? WL.signal.amber : WL.text.dim,
            }}
          >{refreshState ? `Refresh ${refreshState}` : 'Refresh'}</button>
        </div>
      </div>

      {/* ② Status banner — one line, the only tinted element (shared VerdictBanner primitive) */}
      <VerdictBanner
        verdict={action.verdict}
        urgency={action.urgency}
        heroText={action.heroText}
        whyLine={whyLine || null}
        whyTitle={[whyLine, action.detail].filter(Boolean).join('\n')}
        chip={rr != null && hasPlan ? { text: `${rr.toFixed(1)}R`, color: rrColor(rr), tooltip: rrTooltip(entry, stop, planTarget, rr) } : null}
        primary={action.allowPrimary ? { label: action.primaryLabel, onClick: handlePrimary, style: buttonStyle(action.buttonVariant, true) } : null}
        secondary={inlineSecondary ? { label: inlineSecondary.label, onClick: (e) => executeAction(e, inlineSecondary.type), style: buttonStyle('neutral', true) } : null}
        menuItems={menuItems.map(m => ({ label: m.label, onClick: (e) => executeAction(e, m.type) }))}
        menuButtonStyle={buttonStyle('neutral', true)}
      />

      {/* ③ Trade plan ⟷ Sizing & account risk */}
      <div className="wlc-grid" onClick={e => e.stopPropagation()}>
        <div className="wlc-cell">
          <div style={moduleLabel}>
            <span>Trade plan</span>
            {ladder && <Expander open={ladderOpen} onToggle={() => setLadderOpen(v => !v)} label="Plan detail" />}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6 }}>
            <div>
              <div style={planSubLabel}>Limit</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1 }}>{money(it.entry_limit)}</div>
              {hasZone && <div style={{ fontSize: 9.5, color: WL.text.dim }}>zone {money(zoneLo)}–{money(zoneHi)}</div>}
            </div>
            <div>
              <div style={planSubLabel}>Stop</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: hasPlan && stop == null ? WL.signal.red : WL.text.primary }}>{money(it.entry_stop)}</div>
              {stopVolLine && (
                <div
                  title={stopVolatilityTooltip(volCtx, entry, stop)}
                  style={{
                    fontSize: 9.5,
                    color: volCtx.tightVsAtr ? WL.signal.amber : WL.text.dim,
                    fontWeight: volCtx.tightVsAtr ? 700 : 400,
                    cursor: 'help',
                  }}
                >
                  {stopVolLine}{volCtx.tightVsAtr ? ' ⚠' : ''}
                </div>
              )}
            </div>
            <div>
              <div style={planSubLabel}>Target</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1 }}>{money(it.entry_target)}</div>
              {entry != null && planTarget != null && (
                <div style={{ fontSize: 9.5, color: WL.text.dim }} title={exitVsStreet ?? undefined}>
                  {pct(entry, planTarget)}{street != null && planTarget != null && Math.abs((planTarget - street) / street) < 0.03 ? ' ≈ Street' : ''}
                </div>
              )}
            </div>
            <div title={rrTooltip(entry, stop, planTarget, rr)}>
              <div style={planSubLabel}>R : R</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: rr != null ? rrColor(rr) : WL.text.primary }}>
                {rr != null ? rr.toFixed(1) : '—'}
              </div>
              {ladder && <div style={{ fontSize: 9.5, color: WL.text.dim }}>R ${ladder.R.toFixed(2)}/sh</div>}
            </div>
          </div>
          {entryLine && (
            <div style={{ fontSize: 10.5, color: WL.text.secondary, marginTop: 7, lineHeight: 1.45 }}>
              <span style={ctxKey}>Entry </span>
              <span style={{ textTransform: 'capitalize' }}>{entryLine}</span>
            </div>
          )}
          {ladder && (
            <LadderLine steps={ladder.steps} focusIdx={focusIdx} stepTooltip={ladderStepTooltip} />
          )}
          {planNote && (
            <div style={{ marginTop: 6, fontSize: 10.5, color: planNote.color === '#ef5350' ? WL.signal.red : WL.signal.amber, lineHeight: 1.45 }}>
              {planNote.text}
            </div>
          )}
        </div>
        <div className="wlc-cell">
          <SizingTable
            accounts={accounts}
            heldPositions={heldPositions}
            entry={entry}
            stop={stop}
            target={planTarget}
            canPropose={canPropose}
            maxDeployPctOfCash={maxDeployPctOfCash}
            onSize={(accountKey, riskPct) => onPropose?.(it, { account_key: accountKey, risk_pct: riskPct })}
          />
        </div>
      </div>

      {/* Plan detail — full width under the grid */}
      {ladderOpen && ladder && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 16px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {ladder.steps.map((s, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11, color: WL.text.secondary, lineHeight: 1.5 }}>
              <b style={{ ...numStyle, color: WL.text.dim, flex: 'none', width: 108, fontWeight: 700 }}>{s.label}</b>
              <span>{s.px.toFixed(2)} — {s.action}</span>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 10, fontSize: 11, color: WL.text.secondary, lineHeight: 1.5 }}>
            <b style={{ ...numStyle, color: WL.text.dim, flex: 'none', width: 108, fontWeight: 700 }}>Rules</b>
            <span>{MONITOR_RULES}</span>
          </div>
        </div>
      )}

      {/* ④ Conviction ⟷ Intelligence */}
      <div className="wlc-grid" onClick={e => e.stopPropagation()}>
        <div className="wlc-cell">
          <div style={moduleLabel}>
            <span>Conviction</span>
            <CloudLlmRunButtons
              processId="watchlist_cio_synthesis"
              lanePolicy="ensemble"
              symbol={it.symbol}
              compact
              onDone={() => onCioDone?.()}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              title={cioViewTooltip(it)}
              style={{
                fontSize: 11, fontWeight: 800, color: cioAccent, textTransform: 'capitalize',
                border: `1px solid ${cioAccent}4d`, borderRadius: 5, padding: '3px 8px', whiteSpace: 'nowrap',
              }}
            >CIO · {cioLabel}</span>
            {confNum != null && (
              <span title={confidenceTooltip(it)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: WL.text.secondary }}>
                {confNum.toFixed(2)}
                <span style={{ width: 56, height: 4, borderRadius: 2, background: 'rgba(148,163,184,.18)', position: 'relative', display: 'inline-block' }}>
                  <span style={{
                    position: 'absolute', top: 0, left: 0, bottom: 0, borderRadius: 2,
                    width: `${Math.round(Math.min(1, Math.max(0, confNum)) * 100)}%`,
                    background: confColor,
                  }} />
                </span>
                {confBand && <b style={{ color: confColor }}>{confBand}</b>}
              </span>
            )}
            <span style={{ fontSize: 10.5, color: WL.text.dim }}>{convictionMeta}</span>
          </div>
          {cioNote && (
            <div
              title={String(it.synthesis_narrative_snip)}
              style={{
                marginTop: 6, fontSize: 11, color: WL.text.secondary, fontStyle: 'italic', lineHeight: 1.5,
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
              }}
            >
              <span style={{ ...ctxKey, fontStyle: 'normal' }}>CIO note </span>
              {cioNoteAge && (
                <span
                  title={cioNoteStale ? 'Synthesis older than 24h — a holdings change auto-queues a refresh.' : 'When the CIO synthesis last ran.'}
                  style={{ color: cioNoteStale ? WL.signal.amber : WL.text.dim, fontWeight: 600, fontStyle: 'normal', marginRight: 5 }}
                >{cioNoteAge}{cioNoteStale ? ' ⚠' : ''} ·</span>
              )}
              {cioNote}
            </div>
          )}
          <div title={dqTip} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: WL.text.secondary, marginTop: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: dqColor, flex: 'none' }} />
            {dqText}
          </div>
        </div>
        <div className="wlc-cell">
          <div style={moduleLabel}>
            <span>Intelligence</span>
            <Expander open={ctxOpen} onToggle={() => setCtxOpen(v => !v)} label="More" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <div style={ctxLine}>
              <span style={ctxKey}>Catalyst </span>
              {it.catalyst_headline ? (
                <>
                  {it.catalyst_url ? (
                    <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={linkStyle}>{truncate(String(it.catalyst_headline), 80)}</a>
                  ) : truncate(String(it.catalyst_headline), 80)}
                  {it.catalyst_at && <span style={{ color: WL.text.dim }}> · {ago(it.catalyst_at)}</span>}
                </>
              ) : (
                <span style={{ color: WL.text.dim }}>none detected (45d window)</span>
              )}
              {nextEarningsValid && nextEarningsLabel ? (
                <span style={{ color: nextEarningsDays! <= 14 ? WL.signal.amber : WL.text.dim }} title="Next scheduled earnings report (yfinance)">
                  {' · '}next earnings {nextEarningsLabel} ({nextEarningsDays}d)
                </span>
              ) : !it.catalyst_headline ? (
                <span style={{ color: WL.text.dim }}> · none scheduled next 14d</span>
              ) : null}
            </div>
            <div style={{ ...ctxLine, overflowWrap: 'anywhere' }}>
              <span style={ctxKey}>News </span>
              {topNews ? (
                <>
                  <span style={{ color: WL.text.dim }}>{cleanNewsSource(topNews.source)}{topNews.at ? ` · ${ago(topNews.at)}` : ''} </span>
                  {topNews.url
                    ? <a href={topNews.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={linkStyle}>{truncate(String(topNews.title), 90)}</a>
                    : truncate(String(topNews.title), 90)}
                </>
              ) : (
                <span style={{ color: WL.text.dim }}>no indexed news</span>
              )}
            </div>
            <div style={ctxLine}>
              <span style={ctxKey}>Trend </span>
              {fv?.perf_ytd != null ? `${fmtPc(fv.perf_ytd)} YTD` : '—'}
              {sinceAdded != null && (
                <span style={{ color: sinceAdded >= 0 ? WL.signal.teal : WL.signal.red }} title={`vs first-seen price ${money(it.first_seen_price)} on ${String(it.first_seen_at).slice(0, 10)}`}>
                  {' · '}{sinceAdded >= 0 ? '+' : ''}{sinceAdded.toFixed(1)}% since added
                </span>
              )}
              {sc?.vs_sector_week != null && (
                <span style={{ color: sc.vs_sector_week >= 0 ? WL.signal.teal : WL.signal.red }}>
                  {' · '}{fmtPc(sc.vs_sector_week)} vs sector (1w)
                </span>
              )}
            </div>
            {fv && (
              <div style={ctxLine} title="Finviz daily metrics">
                <span style={ctxKey}>Technicals </span>
                RSI {fv.rsi == null ? '—' : Math.round(Number(fv.rsi))} · 1W {fmtPc(fv.perf_week)} · 1M {fmtPc(fv.perf_month)} · vs 50d {fmtPc(fv.sma50)}
              </div>
            )}
            {(companyDesc || llms.length > 0) && (
              <div style={{ ...ctxLine, color: WL.text.dim }}>
                {companyDesc ? truncate(companyDesc, 90) : ''}
                {llms.length > 0 ? `${companyDesc ? ' · ' : ''}intel: ${llms.map((e: any) => llmName(e.lane)).join(' · ')}` : ''}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* More — full width under the grid */}
      {ctxOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 16px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 5 }}>
          {moreNews.map((n, i) => (
            <div key={i} style={{ ...ctxLine, overflowWrap: 'anywhere' }}>
              <span style={ctxKey}>News </span>
              <span style={{ color: WL.text.dim }}>{cleanNewsSource(n.source)}{n.at ? ` · ${ago(n.at)}` : ''} </span>
              {n.url ? <a href={n.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={linkStyle}>{n.title}</a> : n.title}
            </div>
          ))}
          {companyDesc && companyDesc.trim().length > 90 && (
            <div style={ctxLine}>
              <span style={ctxKey}>Company </span>
              {truncate(companyDesc, 400)}
            </div>
          )}
          <FibConfluencePanel symbol={it.symbol} />
        </div>
      )}

      {/* ⑤ Footer strip — due diligence + evidence */}
      <div
        onClick={e => e.stopPropagation()}
        style={{ borderTop: `1px solid ${WL.surface.divider}`, padding: '9px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
      >
        <span style={{ fontSize: 11, color: WL.text.secondary }}>
          <span style={ctxKey}>Due diligence </span>
          {reportEntry?.generated_at ? (
            <span style={{ color: WL.text.dim }}>
              weekly prospectus · generated {ago(reportEntry.generated_at)}
              {reportEntry.generation ? ` · gen #${reportEntry.generation}` : ''}
              {reportEntry.oversight_verdict ? ` · oversight ${reportEntry.oversight_verdict}` : ''}
            </span>
          ) : (
            <>no prospectus yet — generate the weekly report</>
          )}
        </span>
        <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} />
          {hasEvidence && <Expander open={evidenceOpen} onToggle={() => setEvidenceOpen(v => !v)} label="CIO evidence" />}
        </span>
      </div>

      {evidenceOpen && hasEvidence && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 16px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {it.synthesis_evidence?.length > 0 && (
            <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
          )}
          {action.detail && (
            <div style={{ fontSize: 11, color: WL.text.muted, lineHeight: 1.5 }}>
              <span style={ctxKey}>Advisory </span>{action.detail}
            </div>
          )}
          {adv?.note && adv.note !== action.detail && (
            <div style={{ fontSize: 11, color: WL.text.muted, lineHeight: 1.5 }}>
              <span style={ctxKey}>Setup advisory </span>{adv.note}
            </div>
          )}
        </div>
      )}

      {ensOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 16px', borderTop: `1px solid ${WL.surface.divider}` }}>
          <EnsembleValidationInline
            targetType="signal"
            targetId={it.id}
            subject={it.symbol}
            content={`${it.symbol} watchlist — ${it.latest_recommendation || it.trend || ''} · ${it.profile_sector || ''}`}
          />
        </div>
      )}
    </div>
  )
}
