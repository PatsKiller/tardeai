import { useRef, useState, type CSSProperties } from 'react'
import { AgeChip, LadderLine, TrustLine, VerdictBanner } from './primitives/cardPrimitives'
import BrokerIntelPanel from './BrokerIntelPanel'
import BrokerAccountPicker, { type BrokerAccount } from './BrokerAccountPicker'
import ThesisValidityBar from './ThesisValidityBar'
import PositionSizingRiskBar from './risk/PositionSizingRiskBar'
import ProposalSourceBadges from './ProposalSourceBadges'
import ProposalStrategyBadge from './ProposalStrategyBadge'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import { PROPOSAL_STATUS_LABELS, routingPathLabel, unifiedEdgeFromProposal } from '../lib/proposalLabels'
import { brokerOf, fmtMoney, pickFreshOversight, resolveLiveQuote, resolveTickerContext, tradeEconomics } from '../lib/brokerThesis'
import { collectCardBlockers, groupBlockers } from '../lib/proposalBlockers'
import { deriveProposalAction, proposalRrChip } from '../lib/proposalCardAction'
import { buttonStyle, ladderStepTooltip } from '../lib/watchlistCardAction'
import { exitLadder } from '../lib/exitLadder'
import ProposalLifecycleTimeline from './ProposalLifecycleTimeline'
import BrokerDiligenceStrip from './BrokerDiligenceStrip'
import ProposalDeskStrip from './ProposalDeskStrip'
import ProposalLaneGateStrip, { GradeSplitPills } from './ProposalLaneGateStrip'
import TechnicalAssessmentCard from './TechnicalAssessmentCard'
import { cardShell, desk, sectionLabel, statusPill } from '../lib/proposalDeskTheme'

// Legacy desk tokens — preserved detail blocks (litmus, 2FA, expired meta, evidence) still use them.
const MUTED = desk.textDim
const TEXT0 = desk.text
const TEXT1 = 'var(--text1)'
const GREEN = desk.green
const AMBER = desk.amber
const BLUE = desk.blue
const PURPLE = desk.purple
const RED = desk.red
const TEAL = '#5b9aa0'

// Security Card v3 palette (locked spec) — signal-only color, neutral info is grey.
const W = {
  text: '#ecf1f8',
  sub: '#aeb9ca',
  dim: '#66748c',
  teal: '#2dd4bf',
  amber: '#f5a623',
  red: '#ef5350',
  priceUp: '#4ade80',
  edge: '#202b3d',
} as const

const numStyle: CSSProperties = { fontFamily: desk.mono, fontVariantNumeric: 'tabular-nums' }

const moduleLabel: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase',
  color: W.dim, marginBottom: 6,
}

const subLabel: CSSProperties = {
  fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: W.dim, textTransform: 'uppercase',
}

const statusMeta = (s: any) => PROPOSAL_STATUS_LABELS[String(s || '').toUpperCase()] || null

const parseTs = (iso?: string | null): Date | null => {
  if (!iso) return null
  const s = String(iso).trim()
  const norm = s.includes('T') ? s : s.replace(' ', 'T')
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(norm) ? norm : `${norm}Z`)
  return isNaN(d.getTime()) ? null : d
}

/** Normalize a (possibly TZ-naive UTC) server timestamp for AgeChip — naive strings parsed as
 *  local time render negative ages ("-4h old") east of UTC. */
const isoTs = (iso?: string | null): string | undefined => {
  const d = parseTs(iso)
  return d ? d.toISOString() : undefined
}

const agoLabel = (iso?: string | null): string | null => {
  const d = parseTs(iso)
  if (!d) return null
  const h = (Date.now() - d.getTime()) / 36e5
  if (h < 0) return null
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`
  if (h < 48) return `${Math.round(h)}h ago`
  return `${Math.floor(h / 24)}d ago`
}

const truncate = (text: string, max: number): string => {
  const t = String(text).trim()
  return t.length <= max ? t : `${t.slice(0, max - 1).trimEnd()}…`
}

const pctFrom = (base: number | null, x: number | null): string | null => {
  if (!base || x == null || !Number.isFinite(base) || !Number.isFinite(x)) return null
  const v = ((x - base) / base) * 100
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

const rrColorOf = (rr: number): string => (rr >= 2 ? W.teal : rr >= 1.5 ? W.sub : W.amber)

const reviewVerdictColor = (v: string): string => {
  const s = String(v || '').toUpperCase()
  if (/APPROVE|GO\b|PASS|BUY/.test(s)) return W.teal
  if (/REJECT|BLOCK|AVOID|SELL|NO.?GO/.test(s)) return W.red
  if (/CAUTION|WARN|HOLD|WAIT/.test(s)) return W.amber
  return W.sub
}

type Props = {
  proposal: any
  accounts: BrokerAccount[]
  destAccount: string
  onDestAccountChange: (acct: string) => void
  fvMap: Record<string, any>
  detailLoading?: boolean
  refreshBusy?: boolean
  oversightBusy?: boolean
  cloudBusy?: boolean
  oversightMsg?: string
  routeMsg?: string
  routeIntent?: {
    intent_id: string
    symbol: string
    summary?: string
    trade?: any
    trade_packet?: any
    policy_warnings?: string[]
  }
  routeBusy?: boolean
  routeApproveTk?: string
  routeApproveCode?: string
  onRouteApproveTkChange?: (v: string) => void
  onRouteApproveCodeChange?: (v: string) => void
  onConfirmRoute?: (channel: 'web' | 'telegram') => void
  acctPreviewBusy?: boolean
  onRefresh: () => void
  /** Opens the Modify (adjust) editor. Optional `shares` pre-fills the editor with that quantity
   *  (used by the v4 card's "resize to N sh" policy hint on destination-account switch). */
  onEdit: (opts?: { shares?: number }) => void
  onManual: () => void
  onRoute: () => void
  onQueueOversight: () => void
  onRunCloudOversight: () => void
  onCloudLaneDone?: (result?: any) => void
  litmus?: any
  validateBusy?: boolean
  onValidate?: () => void
  narrow?: boolean
  selectMode?: boolean
  selected?: boolean
  onToggleSelected?: () => void
  onResizeToCap?: () => void
  onReject?: () => void
  onExpire?: () => void
  resizeBusy?: boolean
  actionBusy?: boolean
}

export default function BrokerProposalCard({
  proposal: p,
  accounts,
  destAccount: dest,
  onDestAccountChange,
  fvMap,
  detailLoading,
  refreshBusy,
  oversightBusy,
  cloudBusy,
  oversightMsg,
  routeMsg,
  routeIntent,
  routeBusy,
  routeApproveTk,
  routeApproveCode,
  onRouteApproveTkChange,
  onRouteApproveCodeChange,
  onConfirmRoute,
  acctPreviewBusy,
  onRefresh,
  onEdit,
  onManual,
  onRoute,
  onQueueOversight,
  onRunCloudOversight,
  onCloudLaneDone,
  litmus,
  validateBusy,
  onValidate,
  narrow,
  selectMode,
  selected,
  onToggleSelected,
  onResizeToCap,
  onReject,
  onExpire,
  resizeBusy,
  actionBusy,
}: Props) {
  const [showAllBlockers, setShowAllBlockers] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const gatesCellRef = useRef<HTMLDivElement>(null)
  const preview = p._preview
  const previewForDest = Boolean(preview && preview.account === dest)
  const evalData = (previewForDest ? preview?.evaluation : null) || p.evaluation
  // "Record-only" (no auto-route) is true for a Fidelity destination, OR a manual-mode proposal that
  // has NO auto-capable (Schwab) destination available. A paper proposal (account=alpaca_paper) routes
  // Path-B to Schwab, so it must NOT be mislabeled "Record proposal" just because its SOURCE account is
  // manual — when a Schwab destination exists it shows "Auto route (2FA)" (disabled if gate-blocked).
  const _autoDest = (accounts || []).some((a) => brokerOf(a.account_key) === 'Schwab')
  const _destBroker = brokerOf(dest || p.account)
  const fid = _destBroker === 'Fidelity'
    || (_destBroker !== 'Schwab' && p.execution_mode === 'manual' && !_autoDest)
  const gate = evalData?.status || p.gate_status
  const ov = pickFreshOversight(evalData?.oversight, p.oversight, p.intel?.oversight)
  const ovStatus = ov.status || (ov.violations?.length ? 'BLOCK' : ov.warnings?.length ? 'WARN' : null)
  const savedShares = Number(p.proposed_shares) || 0
  const maxSh = evalData?.max_shares ?? p.broker_sizing?.max_shares ?? p.evaluation?.max_shares
  const recSh = evalData?.recommended_shares ?? p.broker_sizing?.recommended_shares ?? p.evaluation?.recommended_shares
  const capShares = recSh != null ? Number(recSh) : (maxSh != null ? Number(maxSh) : savedShares)
  const operatorRoute = Boolean(evalData?.operator_route)
  const policyCap = evalData?.policy_max_shares ?? (operatorRoute ? evalData?.sizing?.shares : maxSh)
  const sizingViolations = evalData?.violations || p.broker_sizing?.violations || p.evaluation?.violations || []
  const oversized = Boolean(
    policyCap != null && savedShares && Number(savedShares) > Number(policyCap),
  ) && !operatorRoute
  const tradePlanBlocked = Boolean(
    evalData?.trade_plan?.status === 'BLOCK' || evalData?.trade_plan?.allowed === false,
  )
  const hardGateViolations = sizingViolations.filter(
    (v: string) => !/exceed max|exceeds cap|SIZE_TOO_SMALL|policy cap|Operator/i.test(v),
  )
  const gateBlocked = !operatorRoute && (gate === 'BLOCK' || ovStatus === 'BLOCK')
  const routeBlocked = hardGateViolations.length > 0 || savedShares < 1 || tradePlanBlocked
  // Plain-language reason the Auto-route button is disabled — shown ON the card (not just a tooltip).
  const tradePlanViolation = (
    evalData?.trade_plan?.violations?.[0]
    || p.broker_diligence?.stages?.find((s: any) => s.id === 'trade_plan')?.detail
    || null
  )
  const routeBlockReason: string | null = (!routeBlocked && !gateBlocked) ? null
    : tradePlanBlocked
      ? (tradePlanViolation
        ? String(tradePlanViolation).slice(0, 120)
        : 'No authoritative trade plan — levels need support/resistance/confluence anchor, not pure 2×risk math')
    : hardGateViolations.length ? String(hardGateViolations[0])
    : (ovStatus === 'BLOCK' || gate === 'BLOCK') ? 'Oversight / gate BLOCK — resolve reviews before auto-route'
    : savedShares < 1 ? 'No routable size on this proposal'
    : 'Auto-route blocked — resolve hard gates first'
  // Cross-surface trust context (2026-07-03): held position + earnings proximity + wide-stop
  // note — approving an add-to-position or pre-earnings entry must not look like a clean entry.
  const _heldHere = Number(p.held_shares_in_account || 0)
  const _heldTotal = Number(p.held_shares_total || 0)
  const _earnM = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(p.next_earnings_date ?? ''))
  const _earnDate = _earnM ? new Date(Number(_earnM[1]), Number(_earnM[2]) - 1, Number(_earnM[3]), 12) : null
  const _earnDays = _earnDate ? Math.round((_earnDate.getTime() - Date.now()) / 864e5) : null
  const _earnLabel = _earnDate ? _earnDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : null
  const _entryN = Number(p.proposed_entry || 0)
  const _stopN = Number(p.proposed_stop || 0)
  const _stopPct = _entryN > 0 && _stopN > 0 && _entryN > _stopN ? ((_entryN - _stopN) / _entryN) * 100 : null
  const trustBits: { text: string; amber?: boolean }[] = []
  if (_heldHere > 0) trustBits.push({ text: `holds ${Math.round(_heldHere).toLocaleString()} sh in this account — this ADDS`, amber: true })
  else if (_heldTotal > 0) trustBits.push({ text: `holds ${Math.round(_heldTotal).toLocaleString()} sh in other accounts` })
  if (_earnDays != null && _earnDays >= 0 && _earnDays <= 45) {
    trustBits.push({
      text: `earnings ${_earnLabel} (${_earnDays}d)`,
      amber: _earnDays <= 7,
    })
  }
  if (_stopPct != null && _stopPct > 7) trustBits.push({ text: `wide stop (${_stopPct.toFixed(1)}%) — consider reduced risk`, amber: true })
  if (oversized && policyCap != null) trustBits.push({ text: `oversized · policy cap ${Number(policyCap).toLocaleString()} sh`, amber: true })

  // Time until this proposal expires (how long it stays in this state).
  const _expMs = p.expires_at ? ((parseTs(p.expires_at)?.getTime() ?? new Date(p.expires_at).getTime()) - Date.now()) : null
  const _expHrs = _expMs != null && !Number.isNaN(_expMs) ? _expMs / 3_600_000 : null
  const expLabel = _expHrs == null ? null
    : _expHrs <= 0 ? 'expired'
    : _expHrs < 1 ? `${Math.round(_expHrs * 60)}m`
    : _expHrs < 48 ? `${_expHrs.toFixed(_expHrs < 10 ? 1 : 0)}h`
    : `${Math.floor(_expHrs / 24)}d ${Math.round(_expHrs % 24)}h`
  // Spec: amber inside 24h, red once expired, otherwise quiet.
  const expColor = _expHrs == null ? W.dim : _expHrs <= 0 ? W.red : _expHrs < 24 ? W.amber : W.dim
  // The gates module renders the consolidated ⛔ list. When it does, suppress the duplicate
  // ⛔/⚠ list inside BrokerIntelPanel's AI-oversight block so blockers show once.
  const cardShowsBlockers = gateBlocked || (!operatorRoute && oversized) || hardGateViolations.length > 0
  const savedEcon = tradeEconomics(savedShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
  const capEcon = oversized && capShares > 0 && capShares !== savedShares
    ? tradeEconomics(capShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
    : null
  const accountLabel = dest || p.account || 'account'
  const intel = p.intel?.ok
    ? {
        ...p.intel,
        oversight: { ...ov, status: ovStatus || ov.status, violations: ov.violations, warnings: ov.warnings },
        agent_reviews: ov.agents?.reviews || p.intel.agent_reviews || [],
      }
    : p.intel?.lazy
      ? null
      : { ok: true, oversight: ov, agent_reviews: ov.agents?.reviews || [] }
  const tickerCtx = resolveTickerContext(p, intel)
  // High-risk / meme-speculation surfacing — the operator asked for this to be BOLD at the top,
  // not buried in the AI-oversight section. Driven by the agents' own words + the risk signals.
  const _riskReviews: any[] = ov.agents?.reviews || intel?.agent_reviews || p.intel?.agent_reviews || []
  const _cat: any = (intel as any)?.catalyst || p.intel?.catalyst || {}
  const _tech: any = (intel as any)?.technicals || p.intel?.technicals || {}
  const _memeRe = /\b(meme|short[ -]?squeeze|heavily shorted|social sentiment|reddit|wsb|wallstreetbets|meme[ -]?trader|pump|frenzy|squeeze|social)\b/i
  const _reviewText = _riskReviews.map((r: any) => String(r.summary || r.reasoning || '')).join(' ')
  const _catText = `${String(_cat.headline || _cat.title || '')} ${String(_cat.summary || '')} ${String(_cat.social_summary || '')} ${String(_cat.text || (p as any).catalyst || '')}`
  // rvol/gap live in intel.technicals; also mirrored onto intel.catalyst — read both + top-level.
  const _rvol = Number(p.rvol ?? _cat.rvol ?? _tech.rvol ?? 0)
  const _gap = Number(p.gap_pct ?? _cat.gap_pct ?? _tech.gap_pct ?? 0)
  const _catUnverified = !!_cat && (_cat.verified === false || Number(_cat.confidence ?? 0) <= 0)
  const _socialFlag = _cat.social === true
  const _memeFlag = _socialFlag || _memeRe.test(_catText) || _memeRe.test(_reviewText)
  const _extremeRvol = _rvol >= 10
  const highRisk = _memeFlag || (_extremeRvol && (_catUnverified || Math.abs(_gap) >= 15))
  const _riskLine = String(
    _riskReviews.find((r: any) => /risk/i.test(String(r.agent || '')))?.summary ||
    _riskReviews.find((r: any) => _memeRe.test(String(r.summary || '')))?.summary || '',
  )
  const _riskReasons = [
    _socialFlag ? `social-momentum${_cat.social_sources ? ` (${_cat.social_sources} src)` : ''}` : (_memeFlag ? 'meme-driven' : null),
    _extremeRvol ? `RVOL ${_rvol.toFixed(0)}×` : null,
    Math.abs(_gap) >= 10 ? `gap ${_gap > 0 ? '+' : ''}${_gap.toFixed(0)}%` : null,
    _catUnverified ? 'unverified catalyst' : null,
  ].filter(Boolean).join(' · ')
  const _stances = _riskReviews
    .map((r: any) => String(r.vote || r.verdict || r.recommendation || '').toUpperCase().replace(/_/g, ' '))
    .filter(Boolean)
  const liveQ = resolveLiveQuote(p)

  // ── Decision matrix inputs ─────────────────────────────────────────────────
  const statusUp = String(p.status || '').toUpperCase()
  const expired = statusUp === 'EXPIRED' || (_expHrs != null && _expHrs <= 0)
  const brokerRejected = statusUp === 'REJECTED'
  const blockersFlat = cardShowsBlockers ? collectCardBlockers(p, evalData, ov, { operatorRoute }) : []
  // Drift of the LIVE price vs the PROPOSED entry (the matrix trigger) — computed directly so it
  // never silently reuses a stale thesis drift.
  const pDriftPct = liveQ.price != null && _entryN > 0
    ? ((liveQ.price / _entryN) - 1) * 100
    : (liveQ.driftPct != null ? Number(liveQ.driftPct) : null)
  const pendingAgents: string[] = ov.agents?.pending || []
  const reviewsPendingBits: string[] = []
  if (pendingAgents.length) reviewsPendingBits.push(`${pendingAgents.length} agent review${pendingAgents.length > 1 ? 's' : ''} pending`)
  else if (!_riskReviews.length) reviewsPendingBits.push('agent reviews missing')
  if (!_tech.technical_grade) reviewsPendingBits.push('TA grade missing')
  const rr = p.live_rr != null ? Number(p.live_rr) : (p.proposed_rr != null ? Number(p.proposed_rr) : null)

  const action = deriveProposalAction({
    expired,
    brokerRejected,
    gateBlocked: gateBlocked || routeBlocked,
    blockReason: routeBlockReason,
    blockerCount: blockersFlat.length || undefined,
    driftPct: pDriftPct,
    oversized,
    capShares: policyCap != null ? Number(policyCap) : null,
    queuedShares: savedShares || null,
    earningsDays: _earnDays,
    earningsLabel: _earnLabel,
    reviewsPendingBits,
    fid,
    approveLabel: undefined,
  })

  const scrollToGates = () => {
    setShowAllBlockers(true)
    gatesCellRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  const dismissHandler = onExpire || onReject
  const primaryHandler: (() => void) | undefined =
    action.primaryKind === 'dismiss' ? dismissHandler
      : action.primaryKind === 'view_gates' ? scrollToGates
      : action.primaryKind === 'modify' ? onEdit
      : action.primaryKind === 'approve' ? onRoute
      : undefined
  const primaryBusy =
    action.primaryKind === 'approve' ? !!routeBusy
      : action.primaryKind === 'dismiss' ? !!actionBusy
      : false
  const primaryLabel = action.primaryKind === 'approve' && routeIntent && action.verdict === 'READY'
    ? 'Re-review route'
    : action.primaryLabel

  const menuItems: { label: string; onClick: () => void }[] = []
  if (onValidate) menuItems.push({ label: validateBusy ? 'Validating…' : 'Validate (litmus)', onClick: () => { if (!validateBusy) { setEvidenceOpen(true); onValidate() } } })
  menuItems.push({ label: refreshBusy ? 'Refreshing…' : 'Refresh prices', onClick: () => { if (!refreshBusy) onRefresh() } })
  if (action.primaryKind !== 'modify') menuItems.push({ label: 'Edit / adjust', onClick: onEdit })
  if (action.primaryKind !== 'approve' && !(routeBlocked && !fid) && !expired && !brokerRejected) {
    menuItems.push({ label: fid ? 'Record proposal' : routeIntent ? 'Re-review route' : 'Auto route (2FA)', onClick: () => { if (!routeBusy) onRoute() } })
  }
  menuItems.push({ label: '✓ Executed manually', onClick: onManual })
  if (oversized && onResizeToCap) menuItems.push({ label: resizeBusy ? 'Resizing…' : `Resize to cap (${policyCap ?? '?'} sh)`, onClick: () => { if (!resizeBusy) onResizeToCap() } })
  menuItems.push({ label: oversightBusy ? 'Oversight queued…' : 'Queue local oversight', onClick: () => { if (!oversightBusy) onQueueOversight() } })
  menuItems.push({ label: cloudBusy ? 'Cloud running…' : 'Run cloud oversight', onClick: () => { if (!cloudBusy) onRunCloudOversight() } })
  if (onReject && !(action.primaryKind === 'dismiss' && dismissHandler === onReject)) {
    menuItems.push({ label: 'Reject', onClick: () => { if (!actionBusy) onReject() } })
  }
  if (onExpire && !(action.primaryKind === 'dismiss' && dismissHandler === onExpire)) {
    menuItems.push({ label: 'Expire', onClick: () => { if (!actionBusy) onExpire() } })
  }

  // ── Module data ────────────────────────────────────────────────────────────
  const entryVal = _entryN > 0 ? _entryN : null
  const stopVal = _stopN > 0 ? _stopN : null
  const targetVal = Number(p.proposed_target1) > 0 ? Number(p.proposed_target1) : null
  const ladder = exitLadder(entryVal, stopVal, targetVal, null)
  const rPerShare = entryVal != null && stopVal != null && entryVal > stopVal ? entryVal - stopVal : null

  const sizingEq = Number(evalData?.sizing?.equity ?? NaN)
  const sizingCash = Number(evalData?.sizing?.cash_available ?? NaN)
  const deployPctEq = savedEcon.investment != null && Number.isFinite(sizingEq) && sizingEq > 0
    ? (savedEcon.investment / sizingEq) * 100 : null
  const riskPctCash = savedEcon.max_risk != null && Number.isFinite(sizingCash) && sizingCash > 0
    ? (savedEcon.max_risk / sizingCash) * 100 : null

  const _why: any = (intel as any)?.why_purchase || {}
  const intelSummary = _why.headline || _why.approve_case || _why.summary || _tech.summary || tickerCtx.companyLine || null
  const analysisTs = ov.cloud_review?.ran_at || _tech.graded_at || p.refreshed_at || null
  const catTitle = p.catalyst_title || _cat.headline || _cat.title
    || (typeof p.catalyst === 'string' && p.catalyst ? p.catalyst : null) || _cat.text || null
  const catAt = p.catalyst_at || _cat.ts || null
  const newsList: any[] = (intel as any)?.news || []

  const stages: any[] = p.broker_diligence?.stages || []
  const stagesPass = stages.filter((s: any) => String(s.status || '').toUpperCase() === 'PASS').length
  const stagesBad = stages.filter((s: any) => ['BLOCK', 'FAIL'].includes(String(s.status || '').toUpperCase()))
  const gatesColor = stages.length
    ? (stagesBad.length ? W.red : stagesPass === stages.length ? W.teal : W.amber)
    : gate === 'BLOCK' ? W.red : gate === 'WARN' ? W.amber : gate === 'PASS' ? W.teal : W.dim
  const cloudConsensus = ov.cloud_review?.consensus?.verdict || null

  const proposedAgo = agoLabel(p.created_at)

  const gateRail = gateBlocked || ovStatus === 'BLOCK' ? RED : ovStatus === 'WARN' || gate === 'WARN' ? AMBER : GREEN

  const ctxHead: CSSProperties = { fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }

  return (
    <article style={{
      ...cardShell(gateBlocked),
      borderLeft: `3px solid ${gateRail}`,
    }}>
      {/* ① Header — one line: identity · state meta · live price */}
      <header style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '11px 16px 9px' }}>
        {selectMode && (
          <input
            type="checkbox"
            checked={!!selected}
            onChange={onToggleSelected}
            aria-label={`Select proposal ${p.symbol} #${p.id} for bulk actions`}
            style={{ width: 15, height: 15, cursor: 'pointer', accentColor: BLUE }}
          />
        )}
        <span style={{ ...numStyle, fontSize: 15, fontWeight: 800, color: W.text, letterSpacing: '-.02em' }}>{p.symbol}</span>
        <span style={{
          fontSize: 9.5, fontWeight: 800, letterSpacing: '.06em', color: W.sub,
          border: `1px solid ${W.edge}`, borderRadius: 4, padding: '2px 6px', whiteSpace: 'nowrap',
        }}>
          {String(p.side || 'BUY').toUpperCase()}·{String(p.order_type || 'LIMIT').toUpperCase()}
        </span>
        <ProposalStrategyBadge proposal={{ ...p, strategy_display_name: tickerCtx.strategyDisplay, strategy_description: tickerCtx.strategyPurpose }} size="sm" />
        <span style={{ fontSize: 11, color: W.dim, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`Destination account: ${accountLabel}`}>
          {String(accountLabel).replace(/_/g, ' ')}
        </span>
        {statusMeta(p.status) && (
          <span title={statusMeta(p.status)!.title} style={statusPill(statusMeta(p.status)!.color)}>
            {statusMeta(p.status)!.label}
          </span>
        )}
        {(() => {
          const tr: any = p.traded
          if (!tr?.trade_id) return null
          const open = tr.status === 'open'
          const filled = open || tr.broker_status === 'filled'
          if (!filled && tr.pnl == null) return null
          const label = open
            ? `Paper filled · #${tr.trade_id} open${tr.entry_price != null ? ` @ $${Number(tr.entry_price).toFixed(2)}` : ''}`
            : tr.pnl != null
              ? `Closed · ${Number(tr.pnl) >= 0 ? 'WIN' : 'LOSS'}`
              : `Trade #${tr.trade_id}`
          return (
            <span title="Linked paper execution for this proposal" style={statusPill(open ? GREEN : MUTED)}>
              {label}
            </span>
          )
        })()}
        {proposedAgo && <span style={{ fontSize: 10.5, color: W.dim, whiteSpace: 'nowrap' }}>Proposed {proposedAgo}</span>}
        {expLabel && (
          <span style={{ fontSize: 10.5, fontWeight: expColor === W.dim ? 600 : 700, color: expColor, whiteSpace: 'nowrap' }}
            title={p.expires_at ? `Expires ${p.expires_at}` : undefined}>
            {expLabel === 'expired' ? 'expired' : `expires ${expLabel}`}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {liveQ.price != null ? (
          <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8 }}
            title={`${liveQ.label} price${liveQ.provider ? ` · ${liveQ.provider}` : ''}`}>
            <span style={{ ...numStyle, fontSize: 16, fontWeight: 800, color: liveQ.stale ? W.dim : W.priceUp }}>
              ${liveQ.price.toFixed(2)}
            </span>
            {pDriftPct != null && (
              <span style={{ ...numStyle, fontSize: 11, fontWeight: 700, color: W.dim }}>
                {pDriftPct >= 0 ? '+' : ''}{pDriftPct.toFixed(2)}% vs entry
              </span>
            )}
            {liveQ.stale && <span style={{ fontSize: 9, fontWeight: 700, color: W.dim, textTransform: 'uppercase' }}>last</span>}
          </span>
        ) : (
          <span style={{ fontSize: 11, fontWeight: 600, color: W.dim, fontStyle: 'italic' }}>No live price</span>
        )}
      </header>

      {/* ② Status banner — the decision matrix rendered as the single tinted line */}
      <VerdictBanner
        verdict={action.bannerVerdict}
        urgency={action.urgency}
        heroText={action.heroText}
        whyLine={action.whyLine || null}
        whyTitle={[action.whyLine, routeBlockReason].filter(Boolean).join('\n') || undefined}
        chip={proposalRrChip(rr)}
        primary={primaryHandler ? {
          label: primaryBusy ? '…' : primaryLabel,
          onClick: (e) => { e.stopPropagation(); if (!primaryBusy) primaryHandler() },
          style: buttonStyle(action.buttonVariant, true),
        } : null}
        secondary={action.primaryKind === 'approve' ? {
          label: 'Modify',
          onClick: (e) => { e.stopPropagation(); onEdit() },
          style: buttonStyle('neutral', true),
        } : null}
        menuItems={menuItems.map(m => ({ label: m.label, onClick: (e) => { e.stopPropagation(); m.onClick() } }))}
        menuButtonStyle={buttonStyle('neutral', true)}
      />

      {/* High-risk / meme-speculation banner — bold, top-of-card (the agents' verdict, surfaced) */}
      {highRisk && (
        <div role="alert" style={{
          margin: '0 16px 10px', padding: '10px 12px', borderRadius: 8,
          background: 'rgba(239,68,68,.13)', border: '1px solid rgba(239,68,68,.5)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13.5, fontWeight: 900, color: RED, letterSpacing: '.3px' }}>
              ⚠ MEME / HIGH-RISK SPECULATION
            </span>
            {_riskReasons && (
              <span style={{ fontSize: 11, fontWeight: 800, color: AMBER }}>{_riskReasons}</span>
            )}
          </div>
          <div style={{ fontSize: 11.5, color: TEXT1, lineHeight: 1.5, marginTop: 5 }}>
            {_riskLine
              ? `${_riskLine.slice(0, 240)}${_riskLine.length > 240 ? '…' : ''}`
              : 'Agents flag this as a speculative, non-actionable setup — confirm the catalyst before any size.'}
          </div>
          <div style={{ fontSize: 10, color: MUTED, marginTop: 5, fontWeight: 700 }}>
            Consensus:&nbsp;
            {_stances.length ? _stances.join(' · ') : 'agents reviewing'}
            {ovStatus ? <span style={{ color: ovStatus === 'BLOCK' ? RED : AMBER }}> · oversight {ovStatus}</span> : null}
          </div>
        </div>
      )}

      {/* Expired meta — bold proposed / expired timestamps + trade result (if it became a trade). */}
      {statusUp === 'EXPIRED' && (() => {
        const fmt = (iso?: string) => {
          const d = parseTs(iso)
          return d ? d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : (iso || '—')
        }
        const tr: any = p.traded
        const traded = tr && (tr.pnl != null || tr.status === 'open' || tr.broker_status === 'filled')
        const won = traded && Number(tr.pnl) > 0
        return (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, padding: '8px 16px', borderTop: `1px solid ${W.edge}`, alignItems: 'baseline' }}>
            <span style={{ fontSize: 11, color: MUTED }}>Proposed <b style={{ fontSize: 13.5, color: TEXT0 }}>{fmt(p.created_at)}</b></span>
            <span style={{ fontSize: 11, color: MUTED }}>Expired <b style={{ fontSize: 13.5, color: AMBER }}>{fmt(p.updated_at || p.expires_at)}</b></span>
            <span style={{ fontSize: 11, color: MUTED }}>Result <b style={{ fontSize: 13.5, color: traded ? (won ? GREEN : tr.status === 'open' ? TEAL : RED) : MUTED }}>
              {traded
                ? tr.status === 'open'
                  ? `Open · trade #${tr.trade_id}${tr.entry_price != null ? ` @ $${Number(tr.entry_price).toFixed(2)}` : ''}`
                  : `${won ? 'WIN' : 'LOSS'} ${tr.pnl_pct != null ? `${Number(tr.pnl_pct) > 0 ? '+' : ''}${tr.pnl_pct}%` : ''}${tr.r_multiple != null ? ` (${tr.r_multiple}R)` : ''}`.trim()
                : 'Not traded'}
            </b></span>
            {!traded && p.would_have && (() => {
              const wh: any = p.would_have
              const c = wh.verdict === 'hit TARGET' ? GREEN : wh.verdict === 'STOPPED' ? RED : (Number(wh.move_pct) >= 0 ? TEAL : AMBER)
              return (
                <span style={{ fontSize: 11, color: MUTED }} title={`If entered at the plan: ${wh.method}`}>
                  Would‑have <b style={{ fontSize: 13.5, color: c }}>
                    {wh.verdict} {Number(wh.move_pct) >= 0 ? '+' : ''}{wh.move_pct}%
                    {wh.to_target_pct != null ? ` · ${wh.to_target_pct}% to target` : ''}
                  </b>
                </span>
              )
            })()}
          </div>
        )
      })()}

      {/* ③ Module grid row 1 — Order & Levels ⟷ Sizing & Fit */}
      <div className="wlc-grid">
        <div className="wlc-cell">
          <div style={moduleLabel}>Order &amp; Levels</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6 }}>
            <div>
              <div style={subLabel}>Limit</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: W.text }}>
                {entryVal != null ? `$${entryVal.toFixed(2)}` : '—'}
              </div>
            </div>
            <div>
              <div style={subLabel}>Stop</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: stopVal == null ? W.red : W.text }}>
                {stopVal != null ? `$${stopVal.toFixed(2)}` : '—'}
              </div>
              {entryVal != null && stopVal != null && <div style={{ fontSize: 9.5, color: W.dim }}>{pctFrom(entryVal, stopVal)}</div>}
            </div>
            <div>
              <div style={subLabel}>Target</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: W.text }}>
                {targetVal != null ? `$${targetVal.toFixed(2)}` : '—'}
              </div>
              {entryVal != null && targetVal != null && <div style={{ fontSize: 9.5, color: W.dim }}>{pctFrom(entryVal, targetVal)}</div>}
            </div>
            <div>
              <div style={subLabel}>R : R</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: rr != null ? rrColorOf(rr) : W.text }}>
                {rr != null ? rr.toFixed(1) : '—'}
                <span style={{ fontSize: 9, color: W.dim, marginLeft: 4, fontWeight: 700 }}>
                  {p.live_rr != null ? 'live' : (p.proposed_rr != null ? 'plan' : '')}
                </span>
              </div>
              {rPerShare != null && <div style={{ fontSize: 9.5, color: W.dim }}>R ${rPerShare.toFixed(2)}/sh</div>}
            </div>
          </div>
          {ladder && (
            <LadderLine steps={ladder.steps} focusIdx={ladder.steps.length > 1 ? 1 : 0} stepTooltip={ladderStepTooltip} />
          )}
          {(p.support_1 != null || p.resistance_1 != null) && (
            <div style={{ fontSize: 10, color: W.dim, marginTop: 7, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {p.support_1 != null && (
                <span>Support <b style={{ ...numStyle, color: W.sub }}>${Number(p.support_1).toFixed(2)}</b></span>
              )}
              {p.resistance_1 != null && (
                <span>Resistance <b style={{ ...numStyle, color: W.sub }}>${Number(p.resistance_1).toFixed(2)}</b></span>
              )}
              {p.levels_source && <span style={{ opacity: 0.7 }}>({p.levels_source})</span>}
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            <ThesisValidityBar tv={p.thesis_validity} refreshedAt={p.refreshed_at} quoteProvider={p.quote_provider} showSourceNote />
          </div>
          {p.refreshed_at && (
            <div style={{ fontSize: 10, color: W.dim, marginTop: 6 }}>
              Refreshed {p.refreshed_at}{p.quote_provider ? ` · ${p.quote_provider}` : ''}
            </div>
          )}
          {(p.last_curated_at || p.curation_status) && (
            <div style={{ fontSize: 10, color: W.dim, marginTop: 4 }}>
              Curated {p.last_curated_at ? String(p.last_curated_at).slice(0, 19).replace('T', ' ') : '—'}
              {p.curation_status && (
                <span style={{
                  marginLeft: 6, fontWeight: 800,
                  color: p.curation_status === 'fresh' ? GREEN : p.curation_status === 'warn' ? AMBER : RED,
                }}>· {p.curation_status}</span>
              )}
            </div>
          )}
        </div>

        <div className="wlc-cell">
          <div style={moduleLabel}>Sizing &amp; Fit</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6 }}>
            <div>
              <div style={subLabel}>Shares</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: oversized ? W.red : W.text }}>
                {savedShares.toLocaleString()}
              </div>
              {oversized && policyCap != null && <div style={{ fontSize: 9.5, color: W.red }}>cap {Number(policyCap).toLocaleString()}</div>}
            </div>
            <div>
              <div style={subLabel}>Deploy</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: W.text }}>{fmtMoney(savedEcon.investment)}</div>
              {deployPctEq != null && <div style={{ fontSize: 9.5, color: W.dim }}>{deployPctEq.toFixed(1)}% of equity</div>}
            </div>
            <div>
              <div style={subLabel}>Risk</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: W.red }}>{fmtMoney(savedEcon.max_risk)}</div>
              {riskPctCash != null && <div style={{ fontSize: 9.5, color: W.dim }}>{riskPctCash.toFixed(1)}% of cash</div>}
            </div>
            <div>
              <div style={subLabel}>Profit @ tgt</div>
              <div style={{ ...numStyle, fontSize: 15.5, fontWeight: 700, marginTop: 1, color: W.text }}>
                {savedEcon.profit_at_target != null ? `+${fmtMoney(savedEcon.profit_at_target)}` : '—'}
              </div>
            </div>
          </div>
          <TrustLine bits={trustBits} />
          {capEcon && (
            <div style={{ fontSize: 10.5, color: W.sub, marginTop: 6 }}>
              If resized to cap: <b style={numStyle}>{capEcon.shares.toLocaleString()} sh</b>
              {' · '}risk <b style={numStyle}>{fmtMoney(capEcon.max_risk)}</b>
              {' · '}profit <b style={numStyle}>+{fmtMoney(capEcon.profit_at_target)}</b>
            </div>
          )}
          {oversized && onResizeToCap && (
            <button onClick={onResizeToCap} disabled={resizeBusy}
              style={{ marginTop: 8, fontSize: 10, fontWeight: 800, padding: '5px 12px', borderRadius: 6, cursor: resizeBusy ? 'not-allowed' : 'pointer',
                border: `1px solid ${W.amber}`, background: 'transparent', color: W.amber }}>
              {resizeBusy ? '…' : `Resize to policy cap (${policyCap ?? '?'} sh)`}
            </button>
          )}
          {!operatorRoute && (
            <div style={{ marginTop: 8 }}>
              <PositionSizingRiskBar
                queuedShares={savedShares}
                capShares={capShares}
                accountLabel={accountLabel}
              />
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            <BrokerAccountPicker
              accounts={accounts}
              value={dest}
              onChange={onDestAccountChange}
              disabled={acctPreviewBusy}
              compact
            />
          </div>
          {(detailLoading || acctPreviewBusy) && (
            <div style={{ fontSize: 10.5, color: W.dim, fontStyle: 'italic', marginTop: 4 }}>Updating sizing &amp; gates…</div>
          )}
          <div style={{ fontSize: 10, color: W.dim, marginTop: 6 }}>
            {p.account && p.account !== dest ? `Routed ${p.account} · ` : ''}
            {evalData?.policy_max_shares != null ? `policy ref ${Number(evalData.policy_max_shares).toLocaleString()} sh · ` : ''}
            <b>Auto route (2FA)</b> opens review — edit shares/prices/risk before requesting approval.
          </div>
          {!!(evalData?.warnings || []).length && operatorRoute && (
            <div style={{ marginTop: 6, fontSize: 10.5, color: W.amber }}>
              {(evalData.warnings || []).map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}
        </div>
      </div>

      {/* ④ Module grid row 2 — Intelligence ⟷ Gates & Reviews */}
      <div className="wlc-grid">
        <div className="wlc-cell">
          <div style={moduleLabel}>Intelligence</div>
          {intelSummary ? (
            <div style={{ fontSize: 11, color: W.sub, lineHeight: 1.5 }}>
              {truncate(String(intelSummary), 220)}
              {analysisTs && <AgeChip ts={isoTs(String(analysisTs))} prefix=" · analysis" warnAfterHours={24} style={{ fontSize: 10, color: W.dim }} />}
            </div>
          ) : detailLoading ? (
            <div style={{ fontSize: 10.5, color: W.dim, fontStyle: 'italic' }}>Loading decision context…</div>
          ) : (
            <div style={{ fontSize: 10.5, color: W.dim, fontStyle: 'italic' }}>No analysis summary — run Enrich on this proposal</div>
          )}
          {p.cio_view && (
            <div style={{ fontSize: 10.5, color: W.sub, marginTop: 5 }}>
              <span style={{ color: W.dim, fontWeight: 700 }}>CIO view </span>{String(p.cio_view).replace(/_/g, ' ')}
            </div>
          )}
          {_earnLabel && _earnDays != null && _earnDays >= 0 && (
            <div style={{ fontSize: 10.5, marginTop: 5, color: _earnDays <= 7 ? W.amber : W.sub, fontWeight: _earnDays <= 7 ? 700 : 400 }}>
              <span style={{ color: W.dim, fontWeight: 700 }}>Earnings </span>{_earnLabel} ({_earnDays}d)
            </div>
          )}
          {catTitle && (
            <div style={{ fontSize: 10.5, color: W.sub, marginTop: 5, lineHeight: 1.45 }}>
              <span style={{ color: W.dim, fontWeight: 700 }}>Catalyst </span>
              {truncate(String(catTitle), 150)}
              {_catUnverified && <span style={{ color: W.amber, fontWeight: 700 }}> · unverified</span>}
              {catAt && <AgeChip ts={isoTs(String(catAt))} prefix=" ·" warnAfterHours={7 * 24} style={{ fontSize: 10, color: W.dim }} />}
            </div>
          )}
          {newsList.slice(0, 2).map((n: any, i: number) => (
            <div key={i} style={{ fontSize: 10.5, color: W.sub, marginTop: 5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={n.title}>
              <span style={{ color: W.dim, fontWeight: 700 }}>News </span>
              <span style={{ color: W.dim }}>{n.source} · </span>{n.title}
              {n.at && <span style={{ color: W.dim, fontSize: 9 }}> · {String(n.at).slice(0, 10)}</span>}
            </div>
          ))}
          {tickerCtx.companyLine && intelSummary !== tickerCtx.companyLine && (
            <div style={{ fontSize: 10.5, color: W.sub, marginTop: 5, lineHeight: 1.45 }}>
              <span style={{ color: W.dim, fontWeight: 700 }}>Company </span>
              {truncate(String(tickerCtx.companyLine), 160)}
            </div>
          )}
          {(tickerCtx.sector || tickerCtx.industry) && (
            <div style={{ fontSize: 10, color: W.dim, marginTop: 6 }}>
              {[tickerCtx.sector, tickerCtx.industry, tickerCtx.instrumentType].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>

        <div className="wlc-cell" ref={gatesCellRef}>
          <div style={moduleLabel}>Gates &amp; Reviews</div>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: gatesColor }}>
            {stages.length
              ? `${stagesPass}/${stages.length} gates green`
              : gate ? `Gate ${gate}` : 'Gates not evaluated'}
            {ovStatus && (
              <span style={{ marginLeft: 8, color: ovStatus === 'BLOCK' ? W.red : ovStatus === 'WARN' ? W.amber : W.teal }}>
                oversight {ovStatus}
              </span>
            )}
          </div>
          {stagesBad.length > 0 && (
            <div style={{ fontSize: 10.5, color: W.red, marginTop: 3 }}>
              {stagesBad.map((s: any) => s.label || s.id).filter(Boolean).join(' · ')}
            </div>
          )}
          {cardShowsBlockers && (() => {
            const groups = groupBlockers(blockersFlat)
            const flat = groups.flatMap(g => g.items)
            const LIMIT = 4
            const truncated = !showAllBlockers && flat.length > LIMIT
            const visible = truncated ? flat.slice(0, LIMIT) : flat
            return (
              <div style={{ marginTop: 6, padding: '7px 9px', fontSize: 10, color: W.red, background: 'rgba(239,83,80,.07)', borderRadius: 7, border: '1px solid rgba(239,83,80,.22)' }}>
                {groups.map(g => (
                  <div key={g.category} style={{ marginBottom: 5 }}>
                    <div style={{ fontSize: 9, fontWeight: 800, color: W.dim, textTransform: 'uppercase', marginBottom: 2 }}>{g.label}</div>
                    {(showAllBlockers ? g.items : g.items.filter(it => visible.includes(it))).map((v, i) => (
                      <div key={`${g.category}-${i}`}>⛔ {v}</div>
                    ))}
                  </div>
                ))}
                {flat.length > LIMIT && (
                  <button
                    onClick={() => setShowAllBlockers(s => !s)}
                    aria-expanded={showAllBlockers}
                    aria-label={truncated ? `Show all ${flat.length} blockers` : 'Show fewer blockers'}
                    style={{ marginTop: 3, fontSize: 10.5, fontWeight: 700, padding: '2px 7px', borderRadius: 5, border: '1px solid rgba(239,83,80,.35)', background: 'transparent', color: W.red, cursor: 'pointer' }}
                  >
                    {truncated ? `+${flat.length - LIMIT} more` : 'Show fewer'}
                  </button>
                )}
              </div>
            )
          })()}
          {routeBlockReason && !fid && !cardShowsBlockers && (
            <div style={{ fontSize: 10.5, color: W.red, marginTop: 5, lineHeight: 1.4 }}>
              <b>Auto-route blocked:</b> {routeBlockReason}
              {expLabel && expLabel !== 'expired' && <span style={{ color: W.dim, fontWeight: 500 }}> · stays until expiry in {expLabel}</span>}
            </div>
          )}
          {(ov.cloud_review?.status || cloudConsensus) && (
            <div style={{ fontSize: 10.5, color: W.sub, marginTop: 6 }}>
              <span style={{ color: W.dim, fontWeight: 700 }}>Cloud </span>
              {cloudConsensus ? String(cloudConsensus).replace(/_/g, ' ') : String(ov.cloud_review?.status)}
              {ov.cloud_review?.ran_at && <AgeChip ts={isoTs(String(ov.cloud_review.ran_at))} prefix=" ·" warnAfterHours={24} style={{ fontSize: 10, color: W.dim }} />}
            </div>
          )}
          {_riskReviews.slice(0, 4).map((r: any, i: number) => (
            <div key={i} style={{ fontSize: 10.5, marginTop: 4, color: W.sub, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
              title={r.summary || r.reasoning || undefined}>
              <span style={{ color: W.dim, fontWeight: 700 }}>{r.agent || 'agent'} </span>
              {r.pending
                ? <span style={{ color: W.amber, fontWeight: 700 }}>pending</span>
                : <span style={{ color: reviewVerdictColor(String(r.verdict || r.vote || '')), fontWeight: 700 }}>{String(r.verdict || r.vote || '—').replace(/_/g, ' ')}</span>}
              {r.summary && !r.pending && <span style={{ color: W.dim }}> · {truncate(String(r.summary), 80)}</span>}
            </div>
          ))}
          {pendingAgents.length > 0 && !_riskReviews.length && (
            <div style={{ fontSize: 10.5, color: W.amber, marginTop: 4 }}>{pendingAgents.join(', ')} pending</div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            {_tech.technical_grade ? (
              <span style={{ fontSize: 10.5, color: W.sub }}>
                <span style={{ color: W.dim, fontWeight: 700 }}>TA </span>
                <b>{_tech.technical_grade}</b>
                {_tech.technical_score != null ? ` (${_tech.technical_score})` : ''}
                {_tech.graded_at && <AgeChip ts={isoTs(String(_tech.graded_at))} prefix=" ·" warnAfterHours={48} style={{ fontSize: 10, color: W.dim }} />}
              </span>
            ) : (
              <span style={{ fontSize: 10.5, color: W.amber }}>TA grade missing</span>
            )}
            <GradeSplitPills gradeSplit={p.grade_split} size="sm" />
          </div>
          {oversightMsg && (
            <div style={{ fontSize: 10.5, marginTop: 6, color: oversightMsg.startsWith('✅') ? W.teal : W.amber }}>{oversightMsg}</div>
          )}
        </div>
      </div>

      {/* Litmus verdict — surfaced full-width when the operator has run Validate */}
      {litmus?.facts?.length > 0 && (() => {
        const v = String(litmus.verdict || '—').toUpperCase()
        const vc = v === 'GO' ? GREEN : v === 'CAUTION' ? AMBER : RED
        const blockers: string[] = litmus.blockers || []
        return (
          <div style={{
            margin: '10px 16px', padding: '10px 12px', borderRadius: 10, fontSize: 11.5, lineHeight: 1.45,
            background: `${vc}0d`, border: `1px solid ${vc}44`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{
                fontSize: 13, fontWeight: 900, padding: '3px 10px', borderRadius: 6,
                background: `${vc}22`, color: vc, border: `1.5px solid ${vc}`, letterSpacing: '.4px',
              }}>LITMUS {v}</span>
              {litmus.trade_still_good != null && (
                <span style={{
                  fontSize: 9.5, fontWeight: 800, padding: '2px 8px', borderRadius: 5,
                  background: litmus.trade_still_good ? 'rgba(34,197,94,.12)' : 'rgba(239,68,68,.12)',
                  color: litmus.trade_still_good ? GREEN : RED,
                }}>
                  {litmus.trade_still_good ? 'trade still good' : 'not route-ready'}
                </span>
              )}
              {litmus.validated_at && (
                <span style={{ fontSize: 9, color: MUTED, fontWeight: 600 }}>{litmus.validated_at}</span>
              )}
            </div>
            {blockers.length > 0 && (
              <div style={{ marginBottom: 8, padding: '6px 8px', borderRadius: 6, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.2)' }}>
                {blockers.map((b: string, i: number) => (
                  <div key={i} style={{ fontSize: 10.5, color: RED, fontWeight: 700 }}>⛔ {b}</div>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {litmus.facts.map((f: string, i: number) => (
                <div key={i} style={{ color: TEXT1, fontSize: 11, display: 'flex', gap: 6 }}>
                  <span style={{ color: vc, flexShrink: 0 }}>·</span>
                  <span>{f}</span>
                </div>
              ))}
            </div>
            {litmus.cloud_conflict && (
              <div style={{ color: AMBER, marginTop: 8, fontWeight: 700, fontSize: 10.5 }}>
                ☁ Cloud lane split — re-run cloud review after Validate so models see live price
              </div>
            )}
          </div>
        )
      })()}

      {/* Route review / 2FA confirm — full-width, only during an active route intent */}
      {(routeMsg || (routeIntent && onConfirmRoute)) && (
        <div style={{ padding: '4px 16px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {routeMsg && (
            <span style={{ fontSize: 10, color: routeMsg.startsWith('✅') || routeMsg.startsWith('📝') ? GREEN : routeMsg.startsWith('🔒') || routeMsg.startsWith('🔐') ? PURPLE : AMBER }}>
              {routeMsg}
            </span>
          )}
          {routeIntent && onConfirmRoute && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 10px', borderRadius: 8, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.22)' }}>
              {(() => {
                const t = routeIntent.trade_packet || routeIntent.trade || {}
                if (!t.shares && !routeIntent.summary) return null
                return (
                  <div style={{ fontSize: 10, color: TEXT0, lineHeight: 1.45 }}>
                    <div style={{ fontWeight: 800, color: PURPLE, marginBottom: 4 }}>Approve this trade</div>
                    <div style={{ fontFamily: 'monospace' }}>
                      BUY {t.shares ?? '—'} {routeIntent.symbol} LIMIT ${Number(t.entry || 0).toFixed(2)}
                      {' · '}STOP ${Number(t.stop || 0).toFixed(2)}
                      {t.target ? ` · TGT $${Number(t.target).toFixed(2)}` : ''}
                    </div>
                    <div style={{ fontSize: 11, color: MUTED, marginTop: 4 }}>
                      risk {fmtMoney(t.dollar_risk)} · invest {fmtMoney(t.dollar_size)}
                      {t.risk_reward ? ` · R:R ${t.risk_reward}:1` : ''}
                    </div>
                    {routeIntent.summary && (
                      <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>{routeIntent.summary}</div>
                    )}
                    {(routeIntent.policy_warnings || []).map((w, i) => (
                      <div key={i} style={{ fontSize: 11, color: AMBER, marginTop: 2 }}>⚠ {w}</div>
                    ))}
                  </div>
                )
              })()}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>2FA confirm:</span>
                <input
                  value={routeApproveTk || ''}
                  onChange={e => onRouteApproveTkChange?.(e.target.value)}
                  placeholder={`ticker ${routeIntent.symbol}`}
                  aria-label={`Web 2FA confirmation — type ticker ${routeIntent.symbol}`}
                  style={{ fontSize: 10, padding: '4px 7px', borderRadius: 5, border: '1px solid rgba(148,163,184,.35)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: 72 }}
                />
                <button
                  onClick={() => onConfirmRoute('web')}
                  disabled={routeBusy || (routeApproveTk || '').trim().toUpperCase() !== routeIntent.symbol}
                  aria-label="Confirm route via web 2FA"
                  style={{ fontSize: 11, fontWeight: 800, padding: '4px 8px', borderRadius: 5, cursor: routeBusy ? 'not-allowed' : 'pointer', border: `1px solid ${GREEN}`, background: 'rgba(34,197,94,.12)', color: GREEN }}
                >Web ✓</button>
                <input
                  value={routeApproveCode || ''}
                  onChange={e => onRouteApproveCodeChange?.(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="6-digit"
                  aria-label="Telegram 2FA confirmation — 6-digit code"
                  style={{ fontSize: 10, padding: '4px 7px', borderRadius: 5, border: '1px solid rgba(148,163,184,.35)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: 64 }}
                />
                <button
                  onClick={() => onConfirmRoute('telegram')}
                  disabled={routeBusy || (routeApproveCode || '').length !== 6}
                  aria-label="Confirm route via Telegram 2FA code"
                  style={{ fontSize: 11, fontWeight: 800, padding: '4px 8px', borderRadius: 5, cursor: routeBusy ? 'not-allowed' : 'pointer', border: `1px solid ${BLUE}`, background: 'rgba(96,165,250,.12)', color: BLUE }}
                >Code ✓</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ⑤ Evidence — the full diligence/intel detail blocks, collapsed behind the footer toggle */}
      {evidenceOpen && (
        <div style={{ borderTop: `1px solid ${W.edge}`, padding: '10px 16px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Plan context chips — at-a-glance answers: source · edge · strategy · hold · catalyst · R:R · backtest · journal */}
          {(() => {
            const cat: any = (intel as any)?.catalyst || p.intel?.catalyst || {}
            const cconf = cat.confidence != null ? (Number(cat.confidence) <= 1 ? Number(cat.confidence) * 100 : Number(cat.confidence)) : null
            const catOk = !!cat.verified && (cconf == null || cconf >= 30)
            const tf = p.strategy_timeframe ? String(p.strategy_timeframe).replace(/_/g, ' ') : null
            const planRR = p.proposed_rr != null ? p.proposed_rr : null
            const liveRR = p.live_rr != null ? p.live_rr : null
            // Source: automated (auto-generated) vs watchlist-originated. Account-agnostic.
            const isWatchlist = Boolean(p.also_on_watchlist || p.watchlist_sleeve || /watch/i.test(String(p.discovery_source || p.proposal_origin || p.origin || '')))
            // Journals to where it ROUTES: the selected/destination broker account. A paper proposal
            // (account=alpaca_paper) journals to its Path-B routing destination — the Schwab (then Fidelity)
            // account it would route to — not its paper source. Only a genuinely ATM-auto trade stays Alpaca.
            const _routeAcct = (accounts || []).find((a) => brokerOf(a.account_key) === 'Schwab')
              || (accounts || []).find((a) => brokerOf(a.account_key) === 'Fidelity')
            const _selAcct = String(dest || p.target_account || '').trim()
            const _isPaperSel = !_selAcct || /alpaca/i.test(_selAcct)
            const journalAcct = (_isPaperSel && _routeAcct)
              ? (_routeAcct.display_name || _routeAcct.account_key)
              : (_selAcct || String(p.account || '').trim())
            const journalLabel = !journalAcct ? '—'
              : /alpaca/i.test(journalAcct) ? 'Simulation'
              : journalAcct.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
            const chip = (label: string, value: any, accent?: string) => (
              <span style={{
                display: 'inline-flex', gap: 6, alignItems: 'baseline', padding: '4px 10px', borderRadius: desk.radius,
                background: desk.bgInset, border: `1px solid ${desk.borderSubtle}`,
              }}>
                <span style={{ ...sectionLabel, marginBottom: 0, fontSize: 9 }}>{label}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: accent || desk.text, fontFamily: desk.mono }}>{value}</span>
              </span>
            )
            const chips = [
              chip('Source', isWatchlist ? 'Watchlist' : 'Automated'),
              (() => {
                const edge = unifiedEdgeFromProposal(p)
                return edge == null ? null : chip('Edge', edge.toFixed(1))
              })(),
              chip('Strategy', tickerCtx.strategyDisplay || p.strategy_id || '—'),
              tf ? chip('Hold', tf) : null,
              chip('Catalyst', catOk ? 'verified' : `unverified${cconf != null ? ` ${Math.round(cconf)}%` : ''}`, catOk ? desk.text : AMBER),
              (planRR != null || liveRR != null) ? chip('R:R', `${planRR ?? '—'} plan${liveRR != null ? ` → ${liveRR} live` : ''}`) : null,
              (() => {
                const bt: any = p.backtest
                if (!bt) return chip('Backtest', 'not run', MUTED)
                const parts = [bt.quality || '—']
                if (bt.samples != null) parts.push(`${bt.samples} samples`)
                if (bt.avg_r != null) parts.push(`${bt.avg_r}R`)
                if (bt.win_rate != null) parts.push(`${Math.round(Number(bt.win_rate) * 100)}% win`)
                return chip('Backtest', parts.join(' · '))
              })(),
              chip('Journals', journalLabel),
              expLabel ? chip('Expires', expLabel === 'expired' ? 'expired' : `in ${expLabel}`, expLabel === 'expired' ? RED : desk.text) : null,
              p.live_submit_path ? chip('Route', routingPathLabel(p.live_submit_path)) : null,
            ].filter(Boolean)
            return (
              <div>
                <div style={{ ...sectionLabel }}>Plan context</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{chips}</div>
              </div>
            )
          })()}

          <ProposalLaneGateStrip routingLane={p.routing_lane} laneGates={p.lane_gates} />

          <ProposalDeskStrip
            gate={gate}
            oversight={ovStatus}
            techGrade={_tech.technical_grade}
            techScore={_tech.technical_score}
            techGradedAt={_tech.graded_at}
            techVerdict={_tech.verdict}
            techAction={_tech.action}
            routeBlocked={routeBlocked || gateBlocked}
            routeBlockReason={routeBlockReason}
          />

          {p.broker_diligence && <BrokerDiligenceStrip summary={p.broker_diligence} compact />}

          {(detailLoading || _tech.summary || _tech.narrative || _tech.technical_grade || _tech.action) && (
            <TechnicalAssessmentCard tech={_tech} compact={narrow} gradeInStrip />
          )}

          {/* Entry helper — moving averages (SMA20/50/200), RSI, RVOL, ATR%, VWAP + plain-English hint.
              Surfaces price-vs-MA structure to time the entry — esp. on watchlist/income proposals that
              carry no momentum-scanner technicals. */}
          {(() => {
            const mc: any = p.ma_context
            if (!mc || (!mc.mas?.length && mc.rsi == null)) return null
            const stat = (label: string, value: any, color: string) => (
              <span style={{ display: 'inline-flex', gap: 4, alignItems: 'baseline' }}>
                <span style={{ fontSize: 9.5, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.3px' }}>{label}</span>
                <span style={{ fontSize: 12, fontWeight: 800, color, fontFamily: 'ui-monospace, monospace' }}>{value}</span>
              </span>
            )
            const rsiC = mc.rsi == null ? MUTED : mc.rsi >= 70 ? RED : mc.rsi <= 30 ? GREEN : TEXT1
            return (
              <div style={{ padding: '8px 10px', borderRadius: 8, border: `1px solid ${desk.borderSubtle}`, background: desk.bgInset, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 14px' }}>
                <span style={{ fontSize: 9.5, fontWeight: 900, color: MUTED, textTransform: 'uppercase', letterSpacing: '.4px' }}>Entry helper</span>
                {(mc.mas || []).map((m: any) => (
                  <span key={m.label} style={{ display: 'inline-flex', gap: 4, alignItems: 'baseline' }}
                    title={`Price is ${Math.abs(m.pct_above)}% ${m.above ? 'above' : 'below'} ${m.label} (${m.price != null ? '$' + m.price : 'n/a'})`}>
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: MUTED }}>{m.label}</span>
                    <span style={{ fontSize: 12, fontWeight: 800, color: m.above ? GREEN : RED, fontFamily: 'ui-monospace, monospace' }}>
                      {m.above ? '↑' : '↓'}{m.price != null ? `$${m.price}` : `${m.pct_above}%`}
                    </span>
                  </span>
                ))}
                {mc.rsi != null && stat('RSI', mc.rsi, rsiC)}
                {mc.rvol != null && stat('RVOL', `${mc.rvol}×`, mc.rvol >= 2 ? AMBER : TEXT1)}
                {mc.atr_pct != null && stat('ATR', `${mc.atr_pct}%`, TEXT1)}
                {mc.vwap != null && (
                  <span style={{ display: 'inline-flex', gap: 4, alignItems: 'baseline' }}
                    title={`Price is ${Math.abs(Number(mc.vwap_dist_pct ?? 0))}% ${mc.above_vwap ? 'above' : 'below'} session VWAP`}>
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.3px' }}>VWAP</span>
                    <span style={{ fontSize: 12, fontWeight: 800, color: mc.above_vwap ? GREEN : RED, fontFamily: 'ui-monospace, monospace' }}>
                      {mc.above_vwap ? '↑' : '↓'}${mc.vwap}
                    </span>
                  </span>
                )}
                {mc.entry_hint && (
                  <span style={{ flexBasis: '100%', fontSize: 10.5, color: MUTED, fontStyle: 'italic', marginTop: 1 }}>↳ {mc.entry_hint}</span>
                )}
              </div>
            )
          })()}

          {/* Ticker context — strategy, exit plan, sector, company one-liner */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px 20px',
            fontSize: 11,
          }}>
            <div>
              <div style={ctxHead}>Strategy</div>
              <div style={{ fontSize: 12, fontWeight: 800, color: TEXT0 }}>{tickerCtx.strategyDisplay}</div>
              {tickerCtx.resolvedStrategyId && (
                <div style={{ fontSize: 10, color: MUTED, marginTop: 2, fontFamily: 'monospace' }}>
                  id {tickerCtx.resolvedStrategyId}
                  {tickerCtx.watchlistSleeve ? ` · sleeve ${tickerCtx.watchlistSleeve}` : ''}
                </div>
              )}
              {tickerCtx.strategyPurpose && (
                <div style={{ fontSize: 10.5, color: TEXT1, marginTop: 3, lineHeight: 1.4 }}>{tickerCtx.strategyPurpose}</div>
              )}
              {tickerCtx.strategyMisaligned && (
                <div style={{ fontSize: 10, color: AMBER, marginTop: 4, fontWeight: 700 }}>
                  Sleeve label ≠ executable strategy — exits use resolved YAML policy
                </div>
              )}
            </div>
            <div>
              <div style={ctxHead}>Exit plan</div>
              {tickerCtx.exitSummary ? (
                <div style={{ fontSize: 11, color: TEXT1, lineHeight: 1.45 }}>{tickerCtx.exitSummary}</div>
              ) : intel?.exit_plan?.summary ? (
                <div style={{ fontSize: 11, color: TEXT1, lineHeight: 1.45 }}>{intel.exit_plan.summary}</div>
              ) : (
                <div style={{ fontSize: 10.5, color: RED, fontWeight: 700 }}>Generic 5% stop / 2R — refresh watchlist bridge</div>
              )}
              {(tickerCtx.exitRationale?.stop_method || intel?.exit_plan?.rationale?.stop_method) && (
                <div style={{ fontSize: 10, color: MUTED, marginTop: 3, fontFamily: 'monospace' }}>
                  stop {String(tickerCtx.exitRationale?.stop_method || intel?.exit_plan?.rationale?.stop_method)}
                  {' · '}target {String(tickerCtx.exitRationale?.target_method || intel?.exit_plan?.rationale?.target_method)}
                </div>
              )}
            </div>
            <div>
              <div style={ctxHead}>Sector</div>
              {(tickerCtx.sector || tickerCtx.industry) ? (
                <div style={{ fontSize: 12, fontWeight: 700, color: TEXT0 }}>
                  {[tickerCtx.sector, tickerCtx.industry].filter(Boolean).join(' · ')}
                </div>
              ) : (/^(the fund|the index|under normal|u\.?s\.?|specifically|the trust)/i.test(String(tickerCtx.companyLine || '')) || /etf|fund/i.test(String(tickerCtx.instrumentType || ''))) ? (
                // Funds/ETFs have no single GICS sector — labeling it "missing" (red) is a false alarm.
                <div style={{ fontSize: 12, fontWeight: 700, color: TEAL }}>ETF / Fund <span style={{ fontSize: 10, fontWeight: 600, color: MUTED }}>· no single sector</span></div>
              ) : (
                <div style={{ fontSize: 12, fontWeight: 700, color: RED }}>Sector missing</div>
              )}
              {tickerCtx.instrumentType && (
                <div style={{ fontSize: 10, color: MUTED, marginTop: 3 }}>{tickerCtx.instrumentType}</div>
              )}
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={ctxHead}>Company</div>
              {tickerCtx.companyLine ? (
                <div style={{ fontSize: 11, color: TEXT1, lineHeight: 1.45 }}>{tickerCtx.companyLine}</div>
              ) : detailLoading ? (
                <div style={{ fontSize: 10.5, color: MUTED, fontStyle: 'italic' }}>Loading company profile…</div>
              ) : (
                <div style={{ fontSize: 10.5, color: MUTED, fontStyle: 'italic' }}>No company profile — run Enrich on this proposal</div>
              )}
            </div>
          </div>

          <EnsembleValidationInline
            targetType="proposal"
            targetId={p.id}
            subject={p.symbol}
            content={`${p.symbol} ${p.strategy_id || ''} entry ${p.proposed_entry} stop ${p.proposed_stop}`}
            compact
          />

          <ProposalLifecycleTimeline proposalId={p.id} />

          {detailLoading && !intel && (
            <div style={{ fontSize: 10, color: MUTED, fontStyle: 'italic' }}>Loading decision context…</div>
          )}
          <BrokerIntelPanel
            intel={intel || { ok: true, oversight: ov, agent_reviews: ov.agents?.reviews || [] }}
            compact
            proposalId={p.id}
            onCloudLaneDone={onCloudLaneDone ?? onRefresh}
            onQueueOversight={onQueueOversight}
            onRunCloudOversight={onRunCloudOversight}
            oversightBusy={oversightBusy}
            cloudBusy={cloudBusy}
            suppressViolationList={cardShowsBlockers}
            suppressStrategyPurpose
            suppressCompanyPurpose={!!tickerCtx.companyLine}
            sourceKind={String(p.discovery_source || p.origin || '')}
          />
        </div>
      )}

      {/* ⑥ Footer strip — provenance + evidence toggle */}
      <footer style={{
        borderTop: `1px solid ${W.edge}`, padding: '8px 16px', fontSize: 10.5, color: W.dim,
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <span style={numStyle}>#{p.id}</span>
        <ProposalSourceBadges proposal={p} size="sm" showRoutingLane />
        <span>route · {routingPathLabel(p.live_submit_path || p.routing_path)}</span>
        {(() => {
          const traceId = p.discovery_trace_id || p.correlation_id || p.last_correlation_id
          return traceId ? (
            <span style={numStyle} title={String(traceId)}>trace {String(traceId).slice(0, 20)}</span>
          ) : null
        })()}
        <span style={{ flex: 1 }} />
        <button
          onClick={() => setEvidenceOpen(v => !v)}
          aria-expanded={evidenceOpen}
          style={{ fontSize: 10.5, fontWeight: 700, color: W.dim, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >evidence {evidenceOpen ? '▴' : '▾'}</button>
      </footer>
    </article>
  )
}
