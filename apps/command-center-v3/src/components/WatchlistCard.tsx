import { useState, type CSSProperties, type ReactNode } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  actionProminence,
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
  riskSizingHint,
  rrTooltip,
  type CardActionType,
} from '../lib/watchlistCardAction'
import { WL, heroStateStyle, sectionLabel, verdictWord, numStyle } from '../lib/watchlistCardTokens'
import {
  resolveSizingBase,
  resolveEquity,
  computeRiskSizedShares,
  acctLabel,
  type ProposalAccount,
} from '../lib/watchlistProposeSizing'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import { EnsembleValidationInline } from './EnsembleValidationCard'

// Security Card v2 — one elevated surface, hairline-divided rows, the status banner is the only
// tinted element and the primary button the only solid one. Color = signal, never decoration.

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

/** Full-bleed section row — divider-top, quiet label, optional right slot. */
function Row({ label, right, children, style }: { label?: string; right?: ReactNode; children: ReactNode; style?: CSSProperties }) {
  return (
    <div onClick={e => e.stopPropagation()} style={{ padding: `${WL.row.padY}px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}`, ...style }}>
      {(label || right) && (
        <div style={{ ...sectionLabel, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
          <span>{label}</span>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

/** Quiet inline expander toggle. */
function Expander({ open, onToggle, label }: { open: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={e => { e.stopPropagation(); onToggle() }}
      style={{ fontSize: 11, fontWeight: 700, color: WL.text.dim, background: 'none', border: 'none', cursor: 'pointer', padding: 0, letterSpacing: 'normal', textTransform: 'none' }}
    >{label} {open ? '▴' : '▾'}</button>
  )
}

const LLM_NAMES: Record<string, string> = { grok: 'Grok', chatgpt: 'ChatGPT', claude: 'Claude' }
const llmName = (lane?: string) => LLM_NAMES[lane || ''] || lane || 'LLM'

const linkStyle: CSSProperties = {
  color: WL.text.secondary,
  textDecoration: 'underline',
  textDecorationColor: 'rgba(148,163,184,.35)',
  textUnderlineOffset: 2,
}

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
  /** Proposal accounts for per-account 1%-risk share sizing (from /api/v2/proposal-accounts). */
  accounts?: ProposalAccount[]
  /** Current per-account positions in this symbol (from /api/v2/portfolio/holdings). */
  heldPositions?: { account: string; shares: number; market_value: number }[]
  ensOpen: boolean
  refreshState?: string
  onDrill: (ctx: DrillContext) => void
  onToggleStar: (e: React.MouseEvent) => void
  onRefresh: (e: React.MouseEvent) => void
  onToggleEns: () => void
  isStarred: boolean
  onPropose?: (it: any) => void
  onAdjust?: (it: any) => void
  onBuildPlan?: (symbol: string) => void
  onOpenDesk?: (symbol: string) => void
}

export default function WatchlistCard({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap, accounts, heldPositions,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
  onPropose, onAdjust, onBuildPlan, onOpenDesk,
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
  const ladder = entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null
  const warns = entry != null || stop != null
    ? planWarnings({ entry, stop, planTarget, rr, pctCash: null, streetTarget: street, analystUpside: pa?.upside != null ? Number(pa.upside) : null })
    : []
  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''
  const action = deriveRecommendedAction({
    it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh,
  })
  const prominence = actionProminence(action, hasPlan)
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
  const validatedVal = ago(it.entry_planned_at) || ago(it.last_validated_at) || null

  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [ladderOpen, setLadderOpen] = useState(prominence.ladderDefaultOpen)
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
  const provenanceText = [
    companyName,
    it.hermes_rank != null ? `Hermes #${it.hermes_rank}` : null,
    originLabel,
    sectorLine,
  ].filter(Boolean).join(' · ')
  const isHeld = it.in_portfolio || outcome?.held
  const heldTip = outcome?.held ? `unrealized ${outcome.unrealized_pnl_pct ?? '?'}%` : 'in portfolio'

  const companyDesc = sc?.description || it.profile_description || null
  const allNews: any[] = sc?.news ?? []
  const topNews = allNews[0] ?? null
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

  // Entry thesis line — strategy · setup · urgency · plan-quality tag · ideal entry.
  const entryLine = [
    strategyLabel,
    setupLabel && setupLabel !== strategyLabel ? `${setupLabel} setup` : null,
    urgencyLabel,
    idealEntry != null ? `ideal ${money(idealEntry)}` : null,
    entryConf != null ? `plan conf ${entryConf.toFixed(2)}` : null,
    entryTag && !['ok', 'ready'].includes(entryTag) ? entryTag : null,
  ].filter(Boolean).join(' · ')

  // Per-account 1%-risk sizing — same math as the Propose modal (risk budget ÷ stop distance,
  // cash-capped) — with held-position awareness: an existing position in the account renders as
  // "holds N sh · add ~M sh" so new risk reads as incremental, not fresh.
  const heldFor = (key: string) => (heldPositions ?? []).find(h => h.account === key) ?? null
  const accountSizing = (hasPlan && entry != null && stop != null && entry > stop)
    ? (accounts ?? [])
        .map(a => ({ a, base: resolveSizingBase(a) }))
        .filter(x => x.base >= 1000)
        .map(x => ({
          key: x.a.account_key,
          name: x.a.display_name || acctLabel(x.a.account_key),
          held: heldFor(x.a.account_key),
          pos: computeRiskSizedShares({
            sizingBase: x.base, equity: resolveEquity(x.a), entry, stop,
            target: planTarget ?? entry, riskPct: 1,
          }),
        }))
        .filter(x => x.pos.shares > 0 || x.held)
        .sort((l, r) => r.pos.sizingBase - l.pos.sizingBase)
        .slice(0, 3)
    : []
  // Positions in accounts the sizing line doesn't cover (e.g. below cash floor or unsized).
  const heldElsewhere = (heldPositions ?? []).filter(h => !accountSizing.some(x => x.key === h.account))

  const reasoning = actionReasoning({ it, pa, adv, action, hasPlan, rr, stale, enriched })
  const dqFlags = dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt, adv })
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const analystDivergent = pa?.divergence === 'divergent'
  const secondaryActions = deriveSecondaryActions(action, hasPlan)
  const sizingHint = riskSizingHint(action, hasPlan, rr)

  // Rule of one — the banner why-line owns the blocking reason; nothing repeats it below.
  const whyParts: string[] = []
  if (action.warning?.text) whyParts.push(action.warning.text)
  if (reasoning && reasoning !== action.warning?.text) whyParts.push(reasoning)
  const whyLine = whyParts.join(' · ')

  // Supplemental plan note — only warnings the banner does not already carry.
  const planNote = (!action.warning && action.verdict !== 'FIX' && warns.length)
    ? { text: warns[0].text, color: warns[0].color }
    : null

  // Narrative snip renders as the CIO note in Conviction — the expander keeps only evidence + advisory.
  const hasEvidence = !!(it.synthesis_evidence?.length || action.detail || adv?.note)

  const executeAction = (e: React.MouseEvent, type: CardActionType) => {
    e.stopPropagation()
    setMenuOpen(false)
    switch (type) {
      case 'REFRESH_DATA':
        onRefresh(e)
        break
      case 'VIEW_INTEL':
      case 'REVIEW_SETUP':
        onDrill(drillCtx)
        break
      case 'PROPOSE_ENTRY':
        onPropose?.(it)
        break
      case 'ADJUST_PLAN':
      case 'REVIEW_EXIT':
        onAdjust?.(it)
        break
      case 'BUILD_PLAN':
        onBuildPlan?.(it.symbol)
        break
      case 'WATCH_ON_DESK':
      case 'QUEUE_PROPOSAL':
        onOpenDesk?.(it.symbol)
        break
      case 'REC_INTEL':
        window.location.href = `/v3/rec-intel?symbol=${encodeURIComponent(it.symbol)}`
        break
      case 'ENSEMBLE':
        onToggleEns()
        break
      default:
        break
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    if (!action.allowPrimary) return
    executeAction(e, action.type)
  }

  // Quiet secondary next to primary; everything else lives in the ••• menu — the old footer row is gone.
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

  // Data health — one dot, one line; full flag list in the tooltip.
  const worstDq = dqFlags.find(f => f.severity === 'red') ?? dqFlags[0] ?? null
  const dqColor = worstDq ? (worstDq.severity === 'red' ? WL.signal.red : WL.signal.amber) : WL.signal.teal
  const dqText = worstDq
    ? `${worstDq.label}${dqFlags.length > 1 ? ` · ${dqFlags.length - 1} more issue${dqFlags.length > 2 ? 's' : ''}` : ''}`
    : `Data healthy — enriched ${ago(it.last_enriched_at) || 'recently'} · CIO synthesis complete`
  const dqTip = dqFlags.length
    ? dqFlags.map(f => f.label).join('\n')
    : [enrichedTooltip(it), planValidatedTooltip(it)].join('\n')

  const convictionMeta = [
    confNum != null ? null : 'confidence pending',
    it.models_agree === true ? 'Grok + ChatGPT agree' : it.models_agree === false ? 'models split' : null,
    validatedVal ? `plan validated ${validatedVal}` : null,
    it.entry_model ? `model ${it.entry_model}` : null,
  ].filter(Boolean).join(' · ')
  const confBand = confNum == null ? null : confNum >= 0.7 ? 'High' : confNum >= 0.5 ? 'Moderate' : 'Low'
  const confColor = confNum == null ? WL.text.dim : confNum >= 0.7 ? WL.signal.teal : confNum >= 0.5 ? WL.signal.amber : WL.signal.red
  const cioNote = it.synthesis_narrative_snip ? truncate(String(it.synthesis_narrative_snip), 220) : null

  const monitorRuleShort = MONITOR_RULES.split('·')[0].trim()

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
      {/* ① Header — identity + price */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, padding: `15px ${WL.row.padX}px 13px` }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 9, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={e => { e.stopPropagation(); onToggleStar(e) }}
              title={isStarred ? 'Unstar' : 'Star'}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, padding: 0, color: isStarred ? WL.signal.amber : WL.text.dim }}
            >{isStarred ? '★' : '☆'}</button>
            <span style={{ ...numStyle, fontWeight: 800, fontSize: 23, letterSpacing: '.01em' }}>{it.symbol}</span>
            {isHeld && (
              <span title={heldTip} style={{ fontSize: 9.5, fontWeight: 800, letterSpacing: '.08em', color: WL.signal.amber, border: '1px solid rgba(245,166,35,.35)', borderRadius: 4, padding: '1px 6px' }}>HELD</span>
            )}
          </div>
          {provenanceText && (
            <div style={{ marginTop: 4, fontSize: 11.5, color: WL.text.dim, lineHeight: 1.4 }}>{provenanceText}</div>
          )}
          <div style={{ marginTop: 5, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }} onClick={e => e.stopPropagation()}>
            <ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={false} />
            {analystDivergent && <span style={{ fontSize: 10.5, color: WL.signal.red, fontWeight: 700 }}>CIO ≠ Street</span>}
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }} onClick={e => e.stopPropagation()}>
          <div style={{ ...numStyle, fontSize: 20, fontWeight: 800 }}>{it.price != null ? money(it.price) : '—'}</div>
          {it.change_pct != null && (
            <div style={{ ...numStyle, fontSize: 12, fontWeight: 700, color: Number(it.change_pct) >= 0 ? WL.price.up : WL.price.down }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); onRefresh(e) }}
            disabled={!!refreshState}
            title="Refresh Finviz + re-queue synthesis"
            style={{
              marginTop: 6, fontSize: 10.5, fontWeight: 600, padding: '3px 9px', borderRadius: 5,
              cursor: refreshState ? 'wait' : 'pointer', border: '1px solid rgba(148,163,184,.25)',
              background: 'transparent', color: needsRefresh ? WL.signal.amber : WL.text.dim,
            }}
          >{refreshState ? `Refresh ${refreshState}` : 'Refresh'}</button>
        </div>
      </div>

      {/* ② Status banner — the decision. Only tinted surface; capped at verdict + headline + why. */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          margin: `0 ${WL.row.padX}px`,
          borderRadius: 8,
          padding: '13px 16px',
          background: heroState.bg,
          border: `1px solid ${heroState.border}`,
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) auto',
          gap: 14,
          alignItems: 'center',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: WL.hero.labelSize, fontWeight: 800, letterSpacing: '.12em', color: heroState.accent, marginBottom: 4 }}>
            {verdictWord(action.verdict)}{action.allowPrimary ? ` · ${action.primaryLabel.toUpperCase()}` : ''}
          </div>
          <div style={{ fontSize: prominence.heroScale === 'large' ? WL.hero.textLarge : WL.hero.textMedium, fontWeight: 800, lineHeight: 1.25 }}>
            {action.heroText}
          </div>
          {whyLine && (
            <div style={{ fontSize: WL.hero.subtextSize, color: WL.text.secondary, marginTop: 5, lineHeight: 1.45 }} title={action.detail || whyLine}>
              {whyLine}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7, alignItems: 'stretch', minWidth: 148 }}>
          {action.allowPrimary && (
            <button onClick={handlePrimary} style={buttonStyle(action.buttonVariant, false, true)}>{action.primaryLabel}</button>
          )}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
            {inlineSecondary && (
              <button onClick={e => executeAction(e, inlineSecondary.type)} style={buttonStyle('neutral', true)}>
                {inlineSecondary.label}
              </button>
            )}
            <div style={{ position: 'relative' }}>
              <button
                onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }}
                title="More actions"
                style={{ ...buttonStyle('neutral', true), minWidth: 0, fontWeight: 800 }}
              >•••</button>
              {menuOpen && (
                <div style={{
                  position: 'absolute', right: 0, top: 'calc(100% + 4px)', zIndex: 30,
                  background: '#16202f', border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
                  boxShadow: '0 10px 28px rgba(0,0,0,.4)', minWidth: 160, padding: 4,
                  display: 'flex', flexDirection: 'column',
                }}>
                  {menuItems.map(m => (
                    <button
                      key={m.label}
                      onClick={e => executeAction(e, m.type)}
                      style={{
                        fontSize: 11.5, fontWeight: 600, color: WL.text.secondary, textAlign: 'left',
                        background: 'transparent', border: 'none', cursor: 'pointer',
                        padding: '7px 10px', borderRadius: 5, whiteSpace: 'nowrap',
                      }}
                    >{m.label}</button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ③ Trade plan — the numbers */}
      <Row label="Trade plan" style={{ borderTop: 'none', paddingTop: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em', color: WL.text.dim, textTransform: 'uppercase' }}>Limit</div>
            <div style={{ ...numStyle, fontSize: 17, fontWeight: 700, marginTop: 3 }}>{money(it.entry_limit)}</div>
            {hasZone && <div style={{ fontSize: 10.5, color: WL.text.dim, marginTop: 2 }}>zone {money(zoneLo)}–{money(zoneHi)}</div>}
          </div>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em', color: WL.text.dim, textTransform: 'uppercase' }}>Stop</div>
            <div style={{ ...numStyle, fontSize: 17, fontWeight: 700, marginTop: 3, color: hasPlan && stop == null ? WL.signal.red : WL.text.primary }}>{money(it.entry_stop)}</div>
            {entry != null && stop != null && <div style={{ fontSize: 10.5, color: WL.text.dim, marginTop: 2 }}>{pct(entry, stop)}</div>}
          </div>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em', color: WL.text.dim, textTransform: 'uppercase' }}>Target</div>
            <div style={{ ...numStyle, fontSize: 17, fontWeight: 700, marginTop: 3 }}>{money(it.entry_target)}</div>
            {entry != null && planTarget != null && <div style={{ fontSize: 10.5, color: WL.text.dim, marginTop: 2 }}>{pct(entry, planTarget)}</div>}
          </div>
          <div title={rrTooltip(entry, stop, planTarget, rr)}>
            <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em', color: WL.text.dim, textTransform: 'uppercase' }}>R : R</div>
            <div style={{ ...numStyle, fontSize: 17, fontWeight: 700, marginTop: 3, color: rr != null ? rrColor(rr) : WL.text.primary }}>
              {rr != null ? rr.toFixed(1) : '—'}
            </div>
            {ladder && <div style={{ fontSize: 10.5, color: WL.text.dim, marginTop: 2 }}>R = ${ladder.R.toFixed(2)} / sh</div>}
          </div>
        </div>
        {entryLine && (
          <div style={{ marginTop: 9, fontSize: 11.5, color: WL.text.secondary, lineHeight: 1.5 }}>
            <span style={{ color: WL.text.dim, fontWeight: 700 }}>Entry </span>
            <span style={{ textTransform: 'capitalize' }}>{entryLine}</span>
          </div>
        )}
        {accountSizing.length > 0 ? (
          <div
            title={'1% of each account\'s sizing base (cash / buying power, never equity) ÷ stop distance, capped by available cash — same math as the Propose modal. "holds" = current position in that account; the add is incremental new risk on top of it.'}
            style={{ marginTop: 6, fontSize: 11.5, color: WL.text.secondary, lineHeight: 1.5 }}
          >
            <span style={{ color: WL.text.dim, fontWeight: 700 }}>Sizing @1% risk </span>
            {accountSizing.map((x, i) => (
              <span key={x.key}>
                {i > 0 && ' · '}
                {x.name}{' '}
                {x.held && (
                  <span style={{ color: WL.signal.amber, fontWeight: 700 }}>
                    holds {Math.round(x.held.shares).toLocaleString()} sh (${(x.held.market_value / 1000).toFixed(1)}k)
                  </span>
                )}
                {x.held && x.pos.shares > 0 && ' · add '}
                {x.pos.shares > 0 && `~${x.pos.shares.toLocaleString()} sh ($${(x.pos.investment / 1000).toFixed(1)}k)`}
              </span>
            ))}
            {heldElsewhere.length > 0 && (
              <span style={{ color: WL.text.dim }}>
                {' · also held: '}
                {heldElsewhere.map(h => `${acctLabel(h.account)} ${Math.round(h.shares).toLocaleString()} sh`).join(', ')}
              </span>
            )}
          </div>
        ) : sizingHint ? (
          <div style={{ marginTop: 6, fontSize: 11, color: WL.text.dim, lineHeight: 1.45 }}>{sizingHint}</div>
        ) : null}
        {exitVsStreet && (
          <div style={{ marginTop: 6, fontSize: 11, color: WL.text.dim, lineHeight: 1.45 }}>{exitVsStreet}</div>
        )}
        {planNote && (
          <div style={{ marginTop: 6, fontSize: 11, color: planNote.color === '#ef5350' ? WL.signal.red : WL.signal.amber, lineHeight: 1.45 }}>
            {planNote.text}
          </div>
        )}
      </Row>

      {/* ④ Conviction + data health */}
      <Row label="Conviction">
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <span
            title={cioViewTooltip(it)}
            style={{
              fontSize: 12, fontWeight: 800, color: cioAccent, textTransform: 'capitalize',
              border: `1px solid ${cioAccent}4d`, borderRadius: 6, padding: '4px 10px', whiteSpace: 'nowrap',
            }}
          >CIO · {cioLabel}</span>
          {confNum != null && (
            <span title={confidenceTooltip(it)} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: WL.text.secondary }}>
              Confidence {confNum.toFixed(2)}
              <span style={{ width: 74, height: 4, borderRadius: 2, background: 'rgba(148,163,184,.18)', position: 'relative', display: 'inline-block' }}>
                <span style={{
                  position: 'absolute', top: 0, left: 0, bottom: 0, borderRadius: 2,
                  width: `${Math.round(Math.min(1, Math.max(0, confNum)) * 100)}%`,
                  background: confColor,
                }} />
              </span>
              {confBand && <span style={{ fontWeight: 700, color: confColor }}>{confBand}</span>}
            </span>
          )}
          <span style={{ fontSize: 11.5, color: WL.text.dim }}>
            {convictionMeta}
          </span>
        </div>
        {cioNote && (
          <div style={{ marginTop: 8, fontSize: 11.5, color: WL.text.secondary, fontStyle: 'italic', lineHeight: 1.5 }} title={String(it.synthesis_narrative_snip)}>
            <span style={{ color: WL.text.dim, fontWeight: 700, fontStyle: 'normal' }}>CIO note </span>{cioNote}
          </div>
        )}
        <div title={dqTip} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: WL.text.secondary, marginTop: 9 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: dqColor, flex: 'none' }} />
          {dqText}
        </div>
      </Row>

      {/* ⑤ Exit ladder — one line; actions behind "Plan detail". Always shown when a ladder exists. */}
      {ladder && (
        <Row
          label="Exit ladder"
          right={<Expander open={ladderOpen} onToggle={() => setLadderOpen(v => !v)} label="Plan detail" />}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px 14px', flexWrap: 'wrap' }}>
            {ladder.steps.map((s, i) => {
              const short = s.label.split(' ')[0]
              const active = i === focusIdx
              return (
                <span key={i} title={ladderStepTooltip(s.label, s.px, s.action)} style={{ ...numStyle, fontSize: 12.5, color: active ? WL.text.primary : WL.text.secondary }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: active ? WL.signal.amber : WL.text.dim, marginRight: 5 }}>{short}</span>
                  {s.px.toFixed(2)}
                </span>
              )
            })}
            <span style={{ fontSize: 10.5, color: WL.text.dim }}>scale ⅓ / ⅓ / runner · {monitorRuleShort}</span>
          </div>
          {ladderOpen && (
            <div style={{ marginTop: 9, display: 'flex', flexDirection: 'column', gap: 5 }}>
              {ladder.steps.map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11.5, color: WL.text.secondary, lineHeight: 1.5 }}>
                  <b style={{ ...numStyle, color: WL.text.dim, flex: 'none', width: 110, fontWeight: 700 }}>{s.label}</b>
                  <span>{s.px.toFixed(2)} — {s.action}</span>
                </div>
              ))}
              <div style={{ display: 'flex', gap: 10, fontSize: 11.5, color: WL.text.secondary, lineHeight: 1.5 }}>
                <b style={{ ...numStyle, color: WL.text.dim, flex: 'none', width: 110, fontWeight: 700 }}>Rules</b>
                <span>{MONITOR_RULES}</span>
              </div>
            </div>
          )}
        </Row>
      )}

      {/* ⑥ Context — two lines by default; company / news / fib / LLM lanes behind "More" */}
      <Row
        label="Context"
        right={<Expander open={ctxOpen} onToggle={() => setCtxOpen(v => !v)} label="More" />}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: WL.text.secondary, lineHeight: 1.55 }}>
          {fv && (
            <div title="Finviz daily metrics">
              <span style={{ color: WL.text.dim, fontWeight: 700 }}>Technicals </span>
              RSI {fv.rsi == null ? '—' : Math.round(Number(fv.rsi))}
              {' · '}1W {fv.perf_week == null ? '—' : `${Number(fv.perf_week) > 0 ? '+' : ''}${Number(fv.perf_week).toFixed(1)}%`}
              {' · '}1M {fv.perf_month == null ? '—' : `${Number(fv.perf_month) > 0 ? '+' : ''}${Number(fv.perf_month).toFixed(1)}%`}
              {' · '}YTD {fv.perf_ytd == null ? '—' : `${Number(fv.perf_ytd) > 0 ? '+' : ''}${Number(fv.perf_ytd).toFixed(1)}%`}
              {' · '}vs 50d {fv.sma50 == null ? '—' : `${Number(fv.sma50) > 0 ? '+' : ''}${Number(fv.sma50).toFixed(1)}%`}
              {sc?.vs_sector_week != null && (
                <span style={{ color: sc.vs_sector_week >= 0 ? WL.signal.teal : WL.signal.red }}>
                  {' · '}{sc.vs_sector_week >= 0 ? '+' : ''}{sc.vs_sector_week}% vs sector (1w)
                </span>
              )}
            </div>
          )}
          {it.catalyst_headline && (
            <div>
              <span style={{ color: WL.text.dim, fontWeight: 700 }}>Catalyst </span>
              {it.catalyst_url ? (
                <a href={it.catalyst_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={linkStyle}>{it.catalyst_headline}</a>
              ) : it.catalyst_headline}
              {it.catalyst_at && <span style={{ color: WL.text.dim, marginLeft: 6 }}>{ago(it.catalyst_at)}</span>}
            </div>
          )}
          {topNews && (
            <div style={{ overflowWrap: 'anywhere' }}>
              <span style={{ color: WL.text.dim, fontWeight: 700 }}>News </span>
              <span style={{ color: WL.text.dim }}>{cleanNewsSource(topNews.source)}{topNews.at ? ` · ${ago(topNews.at)}` : ''} </span>
              {topNews.url ? (
                <a href={topNews.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={linkStyle}>{topNews.title}</a>
              ) : topNews.title}
            </div>
          )}
          {companyDesc && (
            <div style={{ color: WL.text.muted }}>{truncate(companyDesc, 140)}</div>
          )}
          {llms.length > 0 && (
            <div style={{ fontSize: 11, color: WL.text.dim }}>
              External intel current: {llms.map((e: any) => llmName(e.lane)).join(' · ')}
            </div>
          )}
        </div>
        {ctxOpen && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5, fontSize: 12, color: WL.text.secondary, lineHeight: 1.55 }}>
            {companyDesc && companyDesc.trim().length > 140 && (
              <div>
                <span style={{ color: WL.text.dim, fontWeight: 700 }}>Company </span>
                {truncate(companyDesc, 400)}
              </div>
            )}
            <FibConfluencePanel symbol={it.symbol} />
          </div>
        )}
      </Row>

      {/* ⑦ Due diligence reports — always present */}
      <Row label="Due diligence">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 12, color: WL.text.secondary, lineHeight: 1.45 }}>
            {reportEntry?.generated_at ? (
              <>Weekly analyst prospectus · <span style={{ color: WL.text.dim }}>
                generated {ago(reportEntry.generated_at)}
                {reportEntry.generation ? ` · gen #${reportEntry.generation}` : ''}
                {reportEntry.oversight_verdict ? ` · oversight ${reportEntry.oversight_verdict}` : ''}
              </span></>
            ) : (
              <>No prospectus yet for <b>{it.symbol}</b> — generate the weekly report</>
            )}
          </div>
          <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} />
        </div>
      </Row>

      {/* ⑧ CIO evidence & narrative — collapsed long-form */}
      {hasEvidence && (
        <Row style={{ paddingTop: 11, paddingBottom: 12 }}>
          <Expander open={evidenceOpen} onToggle={() => setEvidenceOpen(v => !v)} label="CIO evidence & narrative" />
          {evidenceOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {it.synthesis_evidence?.length > 0 && (
                <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
              )}
              {action.detail && (
                <div style={{ fontSize: 11.5, color: WL.text.muted, lineHeight: 1.5 }}>
                  <span style={{ color: WL.text.dim, fontWeight: 700 }}>Advisory </span>{action.detail}
                </div>
              )}
              {adv?.note && adv.note !== action.detail && (
                <div style={{ fontSize: 11.5, color: WL.text.muted, lineHeight: 1.5 }}>
                  <span style={{ color: WL.text.dim, fontWeight: 700 }}>Setup advisory </span>{adv.note}
                </div>
              )}
            </div>
          )}
        </Row>
      )}

      {ensOpen && (
        <Row>
          <EnsembleValidationInline
            targetType="signal"
            targetId={it.id}
            subject={it.symbol}
            content={`${it.symbol} watchlist — ${it.latest_recommendation || it.trend || ''} · ${it.profile_sector || ''}`}
          />
        </Row>
      )}
    </div>
  )
}
