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
import { LadderLine } from './primitives/cardPrimitives'
import { type RiskPct } from '../lib/watchlistProposeSizing'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import SizingTable from './SizingTable'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import type { WatchlistCardProps } from './WatchlistCard'
import { marketAwareStale, composeWhy, sameHeadline, catalystAgeDays } from '../lib/watchlistCardV4'

// Security Card v4 — institutional evaluation build (v3 untouched; Watch-hub toggle selects).
// Changes vs v3, per the 2026-07-04 operator-approved audit:
//   A  rule-of-one hero sentence (composeWhy dedupes warning/reasoning restatements)
//   B  the header Refresh disappears when the primary action IS refresh
//   C  market-aware staleness (weekend-calm; re-arms at Monday open) — marketAwareStale
//   D  catalyst age is a signal: amber past 7d and counted as a data-quality flag
//   E  top news that repeats the catalyst headline is skipped for the next distinct story
//   F  confidence renders as bar + band word; the raw decimal lives in the tooltip
//   G  links underline on hover only (.wlc4-link)
// Layout: taller two-row hero (the recommendation owns the card), then the familiar
// plan ⟷ sizing and context ⟷ intelligence rows, then the due-diligence footer.
// Color discipline unchanged: the hero is the only tinted surface; teal/amber/red = signal.

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

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1).trimEnd()}…`
}

function cleanNewsSource(raw?: string): string {
  if (!raw) return 'news'
  return String(raw)
    .replace(/^(google_news|yahoo_rss|finviz_news|hermes):\s*/i, '')
    .replace(/^hermes\s*·\s*/i, '')
    .trim() || 'news'
}

function rrColor(rr: number): string {
  return rr >= 2 ? WL.signal.teal : rr >= 1.5 ? WL.signal.amber : WL.signal.red
}

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
}

function Expander({ open, onToggle, label }: { open: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={e => { e.stopPropagation(); onToggle() }}
      style={{ fontSize: 10.5, fontWeight: 700, color: WL.text.dim, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
    >{label} {open ? '▴' : '▾'}</button>
  )
}

const moduleLabel: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase',
  color: WL.text.dim, marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
}
const ctxLine: CSSProperties = { fontSize: 11, color: WL.text.secondary, lineHeight: 1.55 }
const ctxKey: CSSProperties = { color: WL.text.dim, fontWeight: 700 }
const LLM_NAMES: Record<string, string> = { grok: 'Grok', chatgpt: 'ChatGPT', claude: 'Claude' }
const llmName = (lane?: string) => LLM_NAMES[lane || ''] || lane || 'LLM'
/** Surface the model's own stated conviction when the recommendation text carries the
 *  "CONVICTION: <level>" prefix — real stance instead of a bare lane name. */
function llmStance(e: any): string {
  const name = llmName(e?.lane)
  const m = /\bconviction:\s*([a-z-]+)/i.exec(String(e?.recommendation ?? ''))
  const lv = m ? m[1].toLowerCase() : ''
  const OK = new Set(['low','medium','high','med','medium-low','medium-high','low-medium','high-medium'])
  return OK.has(lv) ? `${name} (${lv})` : name
}

export default function WatchlistCardV4({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap, accounts, heldPositions, maxDeployPctOfCash,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
  onPropose, onAdjust, onBuildPlan, onOpenDesk,
}: WatchlistCardProps) {
  const enriched = !!it.last_enriched_at
  // (C) weekend-calm staleness — 1h clock only counts market movement.
  const stale = enriched && marketAwareStale(it.last_enriched_at)
  const needsRefresh = watchlistNeedsRefresh(it, stale)
  const street = pa?.target != null && Number(pa.target) > 0 ? Number(pa.target) : null
  const entry = it.entry_limit != null ? Number(it.entry_limit) : null
  const stop = it.entry_stop != null ? Number(it.entry_stop) : null
  const planTarget = it.entry_target != null ? Number(it.entry_target) : null
  const rr = it.entry_rr != null ? Number(it.entry_rr)
    : (entry && stop && planTarget && entry > stop && planTarget > entry ? (planTarget - entry) / (entry - stop) : null)
  const hasPlan = entry != null && stop != null
  const ladder = entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null
  const warns = entry != null || stop != null
    ? planWarnings({ entry, stop, planTarget, rr, pctCash: null, streetTarget: street, analystUpside: pa?.upside != null ? Number(pa.upside) : null })
    : []
  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''
  const action = deriveRecommendedAction({
    it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh,
  })
  const heroState = heroStateStyle(action.verdict, action.urgency)
  const focusIdx = ladderFocusIndex(ladder)
  const cioRec = it.latest_recommendation ? String(it.latest_recommendation).replace(/_/g, ' ') : null
  const cioLabel = cioRec ?? (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const cioAccent = cioRecColor(it.latest_recommendation || cioLabel)
  const confNum = it.research_confidence != null
    ? Number(it.research_confidence)
    : (it.hermes_score_components?._confidence != null ? Number(it.hermes_score_components._confidence) : null)
  const validatedVal = ago(it.entry_planned_at) || ago(it.last_validated_at) || null

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
  const isHeld = it.in_portfolio || outcome?.held
  const heldTip = outcome?.held ? `unrealized ${outcome.unrealized_pnl_pct ?? '?'}%` : 'in portfolio'

  const companyDesc = sc?.description || it.profile_description || null
  const allNews: any[] = sc?.news ?? []
  // (E) skip a top story that just repeats the catalyst headline.
  const newsPool = allNews.filter((n, i) => i > 0 || !sameHeadline(n?.title, it.catalyst_headline))
  const topNews = newsPool[0] ?? null
  const moreNews = newsPool.slice(1, 4)
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
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const analystDivergent = pa?.divergence === 'divergent'
  const secondaryActions = deriveSecondaryActions(action, hasPlan)

  // (A) one clean sentence for the hero — no restatements, and never the CIO synthesis
  // itself (that lives in CIO context below; absorbing it made the hero a paragraph and
  // duplicated the module — operator feedback 2026-07-04 evening).
  const cioSnip = it.synthesis_narrative_snip ? String(it.synthesis_narrative_snip) : ''
  const reasonForHero = reasoning && cioSnip && reasoning.trim().slice(0, 60) === cioSnip.trim().slice(0, 60)
    ? null
    : reasoning
  const whyLine = composeWhy([action.heroText, action.warning?.text, reasonForHero].map(s => s ? truncate(String(s), 110) : s))

  const planNote = (!action.warning && action.verdict !== 'FIX' && warns.length)
    ? { text: warns[0].text, color: warns[0].color }
    : null

  // (D) catalyst age joins the data-quality picture.
  const catAgeD = catalystAgeDays(it.catalyst_at)
  const catalystStale = catAgeD != null && catAgeD > 7 && !!it.catalyst_headline
  const dqFlags = [
    ...dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt, adv }),
    ...(catalystStale ? [{ label: `catalyst ${catAgeD}d old`, severity: 'amber' as const }] : []),
  ]

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

  const worstDq = dqFlags.find(f => f.severity === 'red') ?? dqFlags[0] ?? null
  const dqColor = worstDq ? (worstDq.severity === 'red' ? WL.signal.red : WL.signal.amber) : WL.signal.teal
  const dqText = worstDq
    ? `${worstDq.label}${dqFlags.length > 1 ? ` · ${dqFlags.length - 1} more issue${dqFlags.length > 2 ? 's' : ''}` : ''}`
    : `Data healthy — enriched ${ago(it.last_enriched_at) || 'recently'}`
  const dqTip = dqFlags.length
    ? dqFlags.map(f => f.label).join('\n')
    : [enrichedTooltip(it), planValidatedTooltip(it)].join('\n')

  const confBand = confNum == null ? null : confNum >= 0.7 ? 'High' : confNum >= 0.5 ? 'Moderate' : 'Low'
  const confColor = confNum == null ? WL.text.dim : confNum >= 0.7 ? WL.signal.teal : confNum >= 0.5 ? WL.signal.amber : WL.signal.red
  const cioNote = it.synthesis_narrative_snip ? truncate(String(it.synthesis_narrative_snip), 220) : null
  const cioNoteAgeH = it.synthesis_updated_at
    ? (Date.now() - new Date(it.synthesis_updated_at).getTime()) / 36e5
    : null
  const cioNoteAge = cioNoteAgeH != null && Number.isFinite(cioNoteAgeH) ? ago(it.synthesis_updated_at) : null
  const cioNoteStale = cioNoteAgeH != null && cioNoteAgeH > 24

  const canPropose = action.type === 'PROPOSE_ENTRY'
  // (B) the header refresh yields when refreshing IS the recommended action.
  const showHeaderRefresh = action.type !== 'REFRESH_DATA'

  const sinceAdded = (it.first_seen_price != null && Number(it.first_seen_price) > 0 && it.price != null)
    ? ((Number(it.price) - Number(it.first_seen_price)) / Number(it.first_seen_price)) * 100
    : null
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

  const link = (href: string, label: string) => (
    <a href={href} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="wlc4-link">{label}</a>
  )

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
      {/* ① Header — identity + price only; quiet */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, padding: '11px 18px 9px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleStar(e) }}
            title={isStarred ? 'Unstar' : 'Star'}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: 0, color: isStarred ? WL.signal.amber : WL.text.dim }}
          >{isStarred ? '★' : '☆'}</button>
          <span style={{ ...numStyle, fontWeight: 800, fontSize: 21 }}>{it.symbol}</span>
          {isHeld && (
            <span title={heldTip} style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.08em', color: WL.signal.amber, border: '1px solid rgba(245,166,35,.35)', borderRadius: 4, padding: '1px 5px', flexShrink: 0 }}>
              HELD{outcome?.held && outcome.unrealized_pnl_pct != null ? (
                <span style={{ marginLeft: 4, color: Number(outcome.unrealized_pnl_pct) >= 0 ? WL.price.up : WL.price.down }}>
                  {Number(outcome.unrealized_pnl_pct) >= 0 ? '+' : ''}{Number(outcome.unrealized_pnl_pct).toFixed(1)}%
                </span>
              ) : null}
            </span>
          )}
          <span onClick={e => e.stopPropagation()} style={{ flexShrink: 0 }}><ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={false} /></span>
          {analystDivergent && <span style={{ fontSize: 10, color: WL.signal.amber, fontWeight: 700, flexShrink: 0 }} title="CIO stance diverges from Street consensus — treat targets with care">CIO ≠ Street</span>}
          {provenanceText && (
            <span style={{ fontSize: 11, color: WL.text.dim, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={provenanceText}>{provenanceText}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ ...numStyle, fontSize: 18, fontWeight: 800 }}>{it.price != null ? money(it.price) : '—'}</div>
            {it.change_pct != null && (
              <div style={{ ...numStyle, fontSize: 11.5, fontWeight: 700, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
                {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
              </div>
            )}
          </div>
          {showHeaderRefresh && (
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
          )}
        </div>
      </div>

      {/* ② Recommendation hero — two rows, the only tinted surface, owns the card */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: heroState.bg,
          borderTop: `1px solid ${heroState.border}`,
          borderBottom: `1px solid ${heroState.border}`,
          padding: '11px 18px 10px',
          display: 'flex',
          flexDirection: 'column',
          gap: 7,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.1em', color: heroState.accent, flexShrink: 0 }}>
            {verdictWord(action.verdict)}
          </span>
          <span
            title={[whyLine, action.detail].filter(Boolean).join('\n')}
            style={{ fontSize: 13.5, fontWeight: 700, color: WL.text.primary, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}
          >
            {whyLine || action.heroText}
          </span>
          {rr != null && hasPlan && (
            <span title={rrTooltip(entry, stop, planTarget, rr)} style={{ ...numStyle, fontSize: 13, fontWeight: 800, color: rrColor(rr), flexShrink: 0 }}>
              {rr.toFixed(1)}R
            </span>
          )}
          <span style={{ display: 'inline-flex', gap: 7, flexShrink: 0, position: 'relative' }}>
            {inlineSecondary && (
              <button onClick={e => executeAction(e, inlineSecondary.type)} style={buttonStyle('neutral', true)}>{inlineSecondary.label}</button>
            )}
            {action.allowPrimary && (
              <button onClick={handlePrimary} style={buttonStyle(action.buttonVariant, true)}>{action.primaryLabel}</button>
            )}
            <button onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }} style={buttonStyle('neutral', true)} aria-label="More actions">⋯</button>
            {menuOpen && (
              <div
                style={{
                  position: 'absolute', top: '110%', right: 0, zIndex: 30, minWidth: 168,
                  background: '#0d1420', border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
                  boxShadow: '0 10px 30px rgba(0,0,0,.5)', padding: 4, display: 'flex', flexDirection: 'column',
                }}
              >
                {menuItems.map(m => (
                  <button
                    key={m.type}
                    onClick={e => executeAction(e, m.type)}
                    style={{ textAlign: 'left', fontSize: 11.5, fontWeight: 600, color: WL.text.secondary, background: 'none', border: 'none', cursor: 'pointer', padding: '7px 10px', borderRadius: 5 }}
                    onMouseEnter={e => { (e.target as HTMLElement).style.background = 'rgba(148,163,184,.08)' }}
                    onMouseLeave={e => { (e.target as HTMLElement).style.background = 'none' }}
                  >{m.label}</button>
                ))}
              </div>
            )}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 11 }}>
          <span
            title={cioViewTooltip(it)}
            style={{ fontWeight: 800, color: cioAccent, textTransform: 'capitalize', whiteSpace: 'nowrap' }}
          >CIO · {cioLabel}</span>
          {confNum != null && (
            /* (F) bar + band word — the decimal lives in the tooltip */
            <span title={`${confNum.toFixed(2)} — ${confidenceTooltip(it)}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: WL.text.secondary }}>
              <span style={{ width: 64, height: 4, borderRadius: 2, background: 'rgba(148,163,184,.18)', position: 'relative', display: 'inline-block' }}>
                <span style={{
                  position: 'absolute', top: 0, left: 0, bottom: 0, borderRadius: 2,
                  width: `${Math.round(Math.min(1, Math.max(0, confNum)) * 100)}%`,
                  background: confColor,
                }} />
              </span>
              {confBand && <b style={{ color: confColor }}>{confBand} conviction</b>}
              <span style={{ ...numStyle, color: WL.text.dim, fontSize: 10.5 }}>{confNum.toFixed(2)}</span>
            </span>
          )}
          {it.models_agree === true && <span style={{ color: WL.text.dim }}>Grok + ChatGPT agree</span>}
          {it.models_agree === false && <span style={{ color: WL.signal.amber, fontWeight: 700 }}>models split</span>}
          {validatedVal && <span style={{ color: WL.text.dim }}>validated {validatedVal}</span>}
          {it.entry_model && <span style={{ color: WL.text.dim }}>{String(it.entry_model)}</span>}
          <span title={dqTip} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: WL.text.secondary, marginLeft: 'auto' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: dqColor, flex: 'none' }} />
            {dqText}
          </span>
        </div>
      </div>

      {/* ③ Trade plan ⟷ Sizing & account risk */}
      <div className="wlc-grid" onClick={e => e.stopPropagation()} style={{ borderTop: 'none' }}>
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
              {entry != null && stop != null && <div style={{ fontSize: 9.5, color: WL.text.dim }}>{pct(entry, stop)}</div>}
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
            onSize={(accountKey, riskPct) => onPropose?.(it, { account_key: accountKey, risk_pct: riskPct as RiskPct })}
          />
        </div>
      </div>

      {ladderOpen && ladder && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 18px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 4 }}>
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

      {/* ④ Context ⟷ Intelligence */}
      <div className="wlc-grid" onClick={e => e.stopPropagation()}>
        <div className="wlc-cell">
          <div style={moduleLabel}>
            <span>CIO context</span>
            {hasEvidence && <Expander open={evidenceOpen} onToggle={() => setEvidenceOpen(v => !v)} label="Evidence" />}
          </div>
          {cioNote ? (
            <div
              title={String(it.synthesis_narrative_snip)}
              style={{
                fontSize: 11, color: WL.text.secondary, fontStyle: 'italic', lineHeight: 1.55,
                display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
              }}
            >
              {cioNoteAge && (
                <span
                  title={cioNoteStale ? 'Synthesis older than 24h — a holdings change auto-queues a refresh.' : 'When the CIO synthesis last ran.'}
                  style={{ color: cioNoteStale ? WL.signal.amber : WL.text.dim, fontWeight: 600, fontStyle: 'normal', marginRight: 5 }}
                >{cioNoteAge}{cioNoteStale ? ' ⚠' : ''} ·</span>
              )}
              {cioNote}
            </div>
          ) : (
            <div style={{ fontSize: 11, color: WL.text.dim }}>No CIO synthesis yet — refresh to queue one.</div>
          )}
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
                  {it.catalyst_url
                    ? link(it.catalyst_url, truncate(String(it.catalyst_headline), 80))
                    : truncate(String(it.catalyst_headline), 80)}
                  {it.catalyst_at && (
                    /* (D) age is a signal — amber past 7d */
                    <span
                      style={{ color: catalystStale ? WL.signal.amber : WL.text.dim, fontWeight: catalystStale ? 700 : 400 }}
                      title={catalystStale ? 'Catalyst older than 7 days — confirm it still holds before acting' : undefined}
                    > · {ago(it.catalyst_at)}{catalystStale ? ' — stale' : ''}</span>
                  )}
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
                    ? link(topNews.url, truncate(String(topNews.title), 90))
                    : truncate(String(topNews.title), 90)}
                </>
              ) : (
                <span style={{ color: WL.text.dim }}>no further indexed news</span>
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
            {companyDesc && (
              <div style={ctxLine}>
                <span style={ctxKey}>Company </span>{truncate(companyDesc, 170)}
              </div>
            )}
            {(sc?.instrument_type || llms.length > 0) && (
              <div style={{ ...ctxLine, color: WL.text.dim }}>
                {sc?.instrument_type ?? ''}
                {llms.length > 0 ? `${sc?.instrument_type ? ' · ' : ''}intel: ${llms.map((e: any) => llmStance(e)).join(' · ')}` : ''}
              </div>
            )}
          </div>
        </div>
      </div>

      {ctxOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 18px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 5 }}>
          {moreNews.map((n, i) => (
            <div key={i} style={{ ...ctxLine, overflowWrap: 'anywhere' }}>
              <span style={ctxKey}>News </span>
              <span style={{ color: WL.text.dim }}>{cleanNewsSource(n.source)}{n.at ? ` · ${ago(n.at)}` : ''} </span>
              {n.url ? link(n.url, String(n.title)) : n.title}
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

      {evidenceOpen && hasEvidence && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 18px', borderTop: `1px solid ${WL.surface.divider}`, display: 'flex', flexDirection: 'column', gap: 8 }}>
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

      {/* ⑤ Footer — due diligence reports */}
      <div
        onClick={e => e.stopPropagation()}
        style={{ borderTop: `1px solid ${WL.surface.divider}`, padding: '9px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
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
        <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} />
      </div>

      {ensOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '9px 18px', borderTop: `1px solid ${WL.surface.divider}` }}>
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
