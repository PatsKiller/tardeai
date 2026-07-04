import { useState } from 'react'
import BrokerIntelPanel from './BrokerIntelPanel'
import BrokerAccountPicker, { type BrokerAccount } from './BrokerAccountPicker'
import ThesisValidityBar from './ThesisValidityBar'
import PositionSizingRiskBar from './risk/PositionSizingRiskBar'
import ActionButton from './ActionButton'
import ProposalSourceBadges from './ProposalSourceBadges'
import ProposalStrategyBadge from './ProposalStrategyBadge'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import { PROPOSAL_STATUS_LABELS, routingPathLabel, unifiedEdgeFromProposal } from '../lib/proposalLabels'
import { brokerOf, fmtMoney, pickFreshOversight, resolveLiveQuote, resolveTickerContext, tradeEconomics } from '../lib/brokerThesis'
import { collectCardBlockers, groupBlockers } from '../lib/proposalBlockers'
import ProposalLifecycleTimeline from './ProposalLifecycleTimeline'
import BrokerDiligenceStrip from './BrokerDiligenceStrip'
import ProposalDeskStrip from './ProposalDeskStrip'
import ProposalLaneGateStrip, { GradeSplitPills } from './ProposalLaneGateStrip'
import TechnicalAssessmentCard from './TechnicalAssessmentCard'
import { cardShell, desk, sectionLabel, statusPill } from '../lib/proposalDeskTheme'

const MUTED = desk.textDim
const TEXT0 = desk.text
const TEXT1 = 'var(--text1)'
const GREEN = desk.green
const AMBER = desk.amber
const BLUE = desk.blue
const PURPLE = desk.purple
const RED = desk.red
const TEAL = '#5b9aa0'

const gateColor = (s: string) => s === 'PASS' ? GREEN : s === 'WARN' ? AMBER : s === 'BLOCK' ? RED : MUTED

const statusMeta = (s: any) => PROPOSAL_STATUS_LABELS[String(s || '').toUpperCase()] || null

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
  onEdit: () => void
  onManual: () => void
  onRoute: () => void
  onQueueOversight: () => void
  onRunCloudOversight: () => void
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
  const _entryN = Number(p.proposed_entry || 0)
  const _stopN = Number(p.proposed_stop || 0)
  const _stopPct = _entryN > 0 && _stopN > 0 && _entryN > _stopN ? ((_entryN - _stopN) / _entryN) * 100 : null
  const trustBits: { text: string; amber?: boolean }[] = []
  if (_heldHere > 0) trustBits.push({ text: `holds ${Math.round(_heldHere).toLocaleString()} sh in this account — this ADDS`, amber: true })
  else if (_heldTotal > 0) trustBits.push({ text: `holds ${Math.round(_heldTotal).toLocaleString()} sh in other accounts` })
  if (_earnDays != null && _earnDays >= 0 && _earnDays <= 45) {
    trustBits.push({
      text: `earnings ${_earnDate!.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} (${_earnDays}d)`,
      amber: _earnDays <= 7,
    })
  }
  if (_stopPct != null && _stopPct > 7) trustBits.push({ text: `wide stop (${_stopPct.toFixed(1)}%) — consider reduced risk`, amber: true })

  // Time until this proposal expires (how long it stays in this state).
  const _expMs = p.expires_at ? (new Date(p.expires_at).getTime() - Date.now()) : null
  const _expHrs = _expMs != null && !Number.isNaN(_expMs) ? _expMs / 3_600_000 : null
  const expLabel = _expHrs == null ? null
    : _expHrs <= 0 ? 'expired'
    : _expHrs < 1 ? `${Math.round(_expHrs * 60)}m`
    : _expHrs < 48 ? `${_expHrs.toFixed(_expHrs < 10 ? 1 : 0)}h`
    : `${Math.floor(_expHrs / 24)}d ${Math.round(_expHrs % 24)}h`
  const expColor = _expHrs == null ? MUTED : _expHrs <= 0 ? RED : _expHrs < 24 ? RED : _expHrs < 48 ? AMBER : TEAL
  // The card's left-section blocker box renders the consolidated ⛔ list. When it does, suppress
  // the duplicate ⛔/⚠ list inside BrokerIntelPanel's AI-oversight block so blockers show once.
  const cardShowsBlockers = gateBlocked || (!operatorRoute && oversized) || hardGateViolations.length > 0
  const savedEcon = tradeEconomics(savedShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
  const capEcon = oversized && capShares > 0 && capShares !== savedShares
    ? tradeEconomics(capShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
    : null
  const accountLabel = dest || p.account || 'account'
  const previewNote = previewForDest && dest !== (p.account || '') ? ' (preview)' : ''
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
  const driftColor = liveQ.driftPct == null ? MUTED
    : Math.abs(liveQ.driftPct) > 3 ? AMBER
    : liveQ.driftPct >= 0 ? GREEN : RED

  const metricBox = {
    background: 'rgba(2,6,23,.35)',
    border: '1px solid rgba(148,163,184,.15)',
    borderRadius: 8,
    padding: '8px 10px',
  } as const

  const gateRail = gateBlocked || ovStatus === 'BLOCK' ? RED : ovStatus === 'WARN' || gate === 'WARN' ? AMBER : GREEN

  return (
    <article style={{
      ...cardShell(gateBlocked),
      borderLeft: `3px solid ${gateRail}`,
    }}>
      {/* Header — institutional 2-row: identity + price, then status meta */}
      <header style={{
        padding: '12px 14px 10px',
        borderBottom: `1px solid ${desk.borderSubtle}`,
        background: desk.bgElevated,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          {selectMode && (
            <input
              type="checkbox"
              checked={!!selected}
              onChange={onToggleSelected}
              aria-label={`Select proposal ${p.symbol} #${p.id} for bulk actions`}
              style={{ width: 16, height: 16, cursor: 'pointer', accentColor: BLUE, marginTop: 4 }}
            />
          )}
          <div style={{ flex: '1 1 200px', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
              <span style={{
                fontSize: 17, fontWeight: 800, color: TEXT0, fontFamily: desk.mono, letterSpacing: '-.02em',
              }}>{p.symbol}</span>
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
            </div>
            <div style={{ fontSize: 9, color: MUTED, marginTop: 3, fontFamily: desk.mono }}>
              #{p.id}
              {p.strategy_id ? ` · ${p.strategy_id}` : ''}
            </div>
          </div>
          {liveQ.price != null ? (
            <div style={{ textAlign: 'right' }} title={`${liveQ.label} price${liveQ.provider ? ` · ${liveQ.provider}` : ''}`}>
              <div style={{
                fontSize: 22, fontWeight: 800, color: liveQ.stale ? MUTED : TEXT0,
                fontFamily: desk.mono, letterSpacing: '-.03em', lineHeight: 1,
              }}>
                ${liveQ.price.toFixed(2)}
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center', marginTop: 2 }}>
                {liveQ.driftPct != null && (
                  <span style={{ fontSize: 12, fontWeight: 700, fontFamily: desk.mono, color: driftColor }}>
                    {liveQ.driftPct >= 0 ? '+' : ''}{liveQ.driftPct.toFixed(2)}%
                  </span>
                )}
                <span style={{ fontSize: 9, fontWeight: 600, color: MUTED, textTransform: 'uppercase' }}>{liveQ.label}</span>
              </div>
            </div>
          ) : (
            <span style={{ fontSize: 11, fontWeight: 600, color: MUTED, fontStyle: 'italic' }}>No live price</span>
          )}
        </div>

        {trustBits.length > 0 && (
          <div style={{ fontSize: 11, color: MUTED, marginTop: 8, lineHeight: 1.5 }}>
            {trustBits.map((b, i) => (
              <span key={i} style={b.amber ? { color: AMBER, fontWeight: 700 } : undefined}>
                {i > 0 ? ' · ' : ''}{b.text}
              </span>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          <ProposalStrategyBadge proposal={{ ...p, strategy_display_name: tickerCtx.strategyDisplay, strategy_description: tickerCtx.strategyPurpose }} size="md" />
          <GradeSplitPills gradeSplit={p.grade_split} size="md" />
          <ProposalSourceBadges proposal={p} size="sm" showRoutingLane />
          {oversized && policyCap != null && (
            <span style={statusPill(RED)}>Oversized · cap {Number(policyCap).toLocaleString()}</span>
          )}
          <span style={{ flex: 1 }} />
          {onValidate && (
            <ActionButton variant="secondary" size="sm" loading={validateBusy} onClick={onValidate}
              title="Litmus: live quote, thesis band, R:R, gates"
              style={{ border: `1px solid ${desk.border}`, color: desk.green, fontWeight: 700 }}>
              {validateBusy ? 'Validating…' : 'Validate'}
            </ActionButton>
          )}
          <ActionButton variant="secondary" size="sm" loading={refreshBusy} onClick={onRefresh}
            style={{ border: `1px solid ${desk.border}`, color: desk.blue, fontWeight: 700 }}>
            {refreshBusy ? 'Refreshing…' : 'Refresh'}
          </ActionButton>
          <ActionButton variant="secondary" size="sm" onClick={onEdit}
            style={{ border: `1px solid ${desk.border}`, color: desk.textMuted, fontWeight: 700 }}>
            Edit
          </ActionButton>
        </div>
      </header>

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

      {(detailLoading || _tech.summary || _tech.narrative || _tech.technical_grade || _tech.action) && (
        <div style={{ padding: '0 0 4px' }}>
          <TechnicalAssessmentCard tech={_tech} compact={narrow} gradeInStrip />
        </div>
      )}

      {/* Expired meta — bold proposed / expired timestamps + trade result (if it became a trade). */}
      {String(p.status || '').toUpperCase() === 'EXPIRED' && (() => {
        const fmt = (iso?: string) => {
          if (!iso) return '—'
          const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z')
          return isNaN(d.getTime()) ? iso : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        }
        const tr: any = p.traded
        const traded = tr && (tr.pnl != null || tr.status === 'open' || tr.broker_status === 'filled')
        const won = traded && Number(tr.pnl) > 0
        return (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, padding: '8px 14px', borderBottom: '1px solid rgba(148,163,184,.14)', background: 'rgba(15,23,42,.65)', alignItems: 'baseline' }}>
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

      {/* Decision Summary — at-a-glance answers: strategy · hold · catalyst · R:R · backtest · journal */}
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
        const summaryLine = [
          isWatchlist ? 'Watchlist' : 'Auto',
          tickerCtx.strategyDisplay || p.strategy_id,
          catOk ? 'catalyst ✓' : 'catalyst ?',
          liveRR != null ? `R:R ${liveRR}` : (planRR != null ? `R:R ${planRR}` : null),
          expLabel ? (expLabel === 'expired' ? 'expired' : `exp ${expLabel}`) : null,
        ].filter(Boolean).join(' · ')
        return (
          <details style={{ borderBottom: `1px solid ${desk.borderSubtle}`, background: desk.bg }}>
            <summary style={{
              padding: '8px 14px', fontSize: 10, fontWeight: 700, color: desk.textMuted, cursor: 'pointer',
              listStyle: 'none', display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span style={{ ...sectionLabel, marginBottom: 0 }}>Plan context</span>
              <span style={{ fontSize: 10.5, fontWeight: 600, color: desk.text, fontFamily: desk.mono }}>{summaryLine}</span>
            </summary>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '0 14px 10px' }}>
              {chips}
            </div>
          </details>
        )
      })()}

      {p.broker_diligence && (
        <div style={{ padding: '8px 14px', borderBottom: `1px solid ${desk.borderSubtle}`, background: desk.bg }}>
          <BrokerDiligenceStrip summary={p.broker_diligence} compact />
        </div>
      )}

      <div style={{ padding: '6px 14px', borderBottom: '1px solid rgba(148,163,184,.1)', background: 'rgba(15,23,42,.35)' }}>
        <EnsembleValidationInline
          targetType="proposal"
          targetId={p.id}
          subject={p.symbol}
          content={`${p.symbol} ${p.strategy_id || ''} entry ${p.proposed_entry} stop ${p.proposed_stop}`}
          compact
        />
      </div>

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
          <div style={{ padding: '8px 14px', borderBottom: `1px solid ${desk.borderSubtle}`, background: desk.bgInset, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 14px' }}>
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

      {/* Ticker context — strategy, sector, company one-liner */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid rgba(148,163,184,.1)',
        background: 'rgba(15,23,42,.45)',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '12px 20px',
        fontSize: 11,
      }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>Strategy</div>
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
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>Exit plan</div>
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
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>Sector</div>
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
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>Company</div>
          {tickerCtx.companyLine ? (
            <div style={{ fontSize: 11, color: TEXT1, lineHeight: 1.45 }}>{tickerCtx.companyLine}</div>
          ) : detailLoading ? (
            <div style={{ fontSize: 10.5, color: MUTED, fontStyle: 'italic' }}>Loading company profile…</div>
          ) : (
            <div style={{ fontSize: 10.5, color: MUTED, fontStyle: 'italic' }}>No company profile — run Enrich on this proposal</div>
          )}
        </div>
      </div>

      {/* High-risk / meme-speculation banner — bold, top-of-card (the agents' verdict, surfaced) */}
      {highRisk && (
        <div role="alert" style={{
          margin: '10px 14px 2px', padding: '10px 12px', borderRadius: 8,
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

      {/* Body grid */}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? '1fr' : 'minmax(0,1.2fr) minmax(0,1fr)', gap: 0 }}>
        <section style={{ padding: '12px 14px', borderRight: narrow ? 'none' : '1px solid rgba(148,163,184,.1)', borderBottom: narrow ? '1px solid rgba(148,163,184,.1)' : 'none' }}>
          {litmus?.facts?.length > 0 && (() => {
            const v = String(litmus.verdict || '—').toUpperCase()
            const vc = v === 'GO' ? GREEN : v === 'CAUTION' ? AMBER : RED
            const blockers: string[] = litmus.blockers || []
            return (
              <div style={{
                marginBottom: 10, padding: '10px 12px', borderRadius: 10, fontSize: 11.5, lineHeight: 1.45,
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
                    ☁ Cloud lane split — re-run Grok+ChatGPT after Validate so models see live price
                  </div>
                )}
              </div>
            )
          })()}
          <ThesisValidityBar tv={p.thesis_validity} refreshedAt={p.refreshed_at} quoteProvider={p.quote_provider} showSourceNote />
          {!operatorRoute && (
            <PositionSizingRiskBar
              queuedShares={savedShares}
              capShares={capShares}
              accountLabel={accountLabel}
            />
          )}
          {p.refreshed_at && (
            <div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>
              Refreshed {p.refreshed_at}{p.quote_provider ? ` · ${p.quote_provider}` : ''}
            </div>
          )}
          {(p.support_1 != null || p.resistance_1 != null) && (
            <div style={{ fontSize: 10, color: MUTED, marginTop: 6, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {p.support_1 != null && (
                <span>Support <b style={{ color: GREEN, fontFamily: 'monospace' }}>${Number(p.support_1).toFixed(2)}</b></span>
              )}
              {p.resistance_1 != null && (
                <span>Resistance <b style={{ color: RED, fontFamily: 'monospace' }}>${Number(p.resistance_1).toFixed(2)}</b></span>
              )}
              {p.levels_source && <span style={{ opacity: 0.7 }}>({p.levels_source})</span>}
            </div>
          )}
          {(p.last_curated_at || p.curation_status) && (
            <div style={{ fontSize: 10, color: MUTED, marginTop: 4 }}>
              Curated {p.last_curated_at ? String(p.last_curated_at).slice(0, 19).replace('T', ' ') : '—'}
              {p.curation_status && (
                <span style={{
                  marginLeft: 6, fontWeight: 800,
                  color: p.curation_status === 'fresh' ? GREEN : p.curation_status === 'warn' ? AMBER : RED,
                }}>· {p.curation_status}</span>
              )}
            </div>
          )}

          <div style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 8,
            background: oversized ? 'rgba(239,68,68,.06)' : 'rgba(15,23,42,.4)',
            border: `1px solid ${oversized ? 'rgba(239,68,68,.25)' : 'rgba(148,163,184,.15)'}`,
            fontSize: 11,
          }}>
            <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 6 }}>Route size</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', alignItems: 'baseline' }}>
              <span style={{ color: TEXT0 }}>
                <b style={{ fontFamily: 'monospace' }}>Route:</b> {savedShares.toLocaleString()} sh
                {p.account && p.account !== dest ? ` · routed ${p.account}` : ''}
              </span>
              {evalData?.policy_max_shares != null && (
                <span style={{ color: MUTED, fontSize: 10 }}>
                  policy ref {Number(evalData.policy_max_shares).toLocaleString()} sh
                </span>
              )}
            </div>
            <div style={{ marginTop: 6, color: MUTED, fontSize: 10 }}>
              <b>Auto route (2FA)</b> opens review — edit shares/prices/risk before requesting approval.
            </div>
          </div>

          {!!(evalData?.warnings || []).length && operatorRoute && (
            <div style={{ marginTop: 8, padding: '8px 10px', fontSize: 11.5, color: AMBER, background: 'rgba(245,158,11,.08)', borderRadius: 8, border: '1px solid rgba(245,158,11,.2)' }}>
              {(evalData.warnings || []).map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}
          {cardShowsBlockers && (() => {
            const blockers = collectCardBlockers(p, evalData, ov, { operatorRoute })
            const groups = groupBlockers(blockers)
            const flat = groups.flatMap(g => g.items)
            const LIMIT = 4
            const truncated = !showAllBlockers && flat.length > LIMIT
            const visible = truncated ? flat.slice(0, LIMIT) : flat
            return (
              <div style={{ marginTop: 8, padding: '8px 10px', fontSize: 10, color: RED, background: 'rgba(239,68,68,.08)', borderRadius: 8, border: '1px solid rgba(239,68,68,.2)' }}>
                {groups.map(g => (
                  <div key={g.category} style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 2 }}>{g.label}</div>
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
                    style={{ marginTop: 4, fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 5, border: '1px solid rgba(239,68,68,.35)', background: 'transparent', color: RED, cursor: 'pointer' }}
                  >
                    {truncated ? `+${flat.length - LIMIT} more` : 'Show fewer'}
                  </button>
                )}
              </div>
            )
          })()}
          {oversized && onResizeToCap && (
            <button onClick={onResizeToCap} disabled={resizeBusy}
              style={{ marginTop: 8, fontSize: 10, fontWeight: 800, padding: '6px 12px', borderRadius: 7, cursor: resizeBusy ? 'not-allowed' : 'pointer',
                border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>
              {resizeBusy ? '…' : `Resize to policy cap (${policyCap ?? '?' } sh)`}
            </button>
          )}
          <ProposalLifecycleTimeline proposalId={p.id} />

          <div style={{ display: 'grid', gridTemplateColumns: narrow ? '1fr' : 'repeat(3, 1fr)', gap: 8, marginTop: 12 }}>
            <div style={metricBox}>
              <div style={{ fontSize: 11, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>At queued size</div>
              <div style={{ fontSize: 15, fontWeight: 800, fontFamily: 'monospace', color: oversized ? RED : TEXT0 }}>
                {savedEcon.shares.toLocaleString()} sh @ ${Number(p.proposed_entry).toFixed(2)}
              </div>
              <div style={{ fontSize: 11, color: MUTED }}>stop ${Number(p.proposed_stop).toFixed(2)} · tgt ${Number(p.proposed_target1).toFixed(2)}</div>
            </div>
            <div style={metricBox}>
              <div style={{ fontSize: 11, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>Risk @ queued</div>
              <div style={{ fontSize: 15, fontWeight: 800, fontFamily: 'monospace', color: RED }}>{fmtMoney(savedEcon.max_risk)}</div>
              <div style={{ fontSize: 11, color: MUTED }}>invest {fmtMoney(savedEcon.investment)}</div>
            </div>
            <div style={metricBox}>
              <div style={{ fontSize: 11, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>Profit @ tgt</div>
              <div style={{ fontSize: 15, fontWeight: 800, fontFamily: 'monospace', color: GREEN }}>+{fmtMoney(savedEcon.profit_at_target)}</div>
              {/* R:R: live (from fresh thesis) when available, else the plan R:R — never a stale live value. */}
              <div style={{ fontSize: 11, color: MUTED }}>
                R:R <b style={{ color: TEXT0 }}>{p.live_rr ?? p.proposed_rr ?? '—'}</b>
                <span style={{ color: p.live_rr != null ? GREEN : MUTED, marginLeft: 4, fontWeight: 700 }}>
                  {p.live_rr != null ? 'live' : (p.proposed_rr != null ? 'plan' : '')}
                </span>
              </div>
            </div>
          </div>
          {capEcon && (
            <div style={{ display: 'grid', gridTemplateColumns: narrow ? '1fr' : 'repeat(3, 1fr)', gap: 8, marginTop: 8, opacity: 0.92 }}>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 10, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>If resized to cap</div>
                <div style={{ fontSize: 13, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>
                  {capEcon.shares.toLocaleString()} sh @ ${Number(p.proposed_entry).toFixed(2)}
                </div>
              </div>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 10, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>Risk @ cap</div>
                <div style={{ fontSize: 13, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>{fmtMoney(capEcon.max_risk)}</div>
              </div>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 10, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>Profit @ cap</div>
                <div style={{ fontSize: 13, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>+{fmtMoney(capEcon.profit_at_target)}</div>
              </div>
            </div>
          )}
        </section>

        <section style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <BrokerAccountPicker
            accounts={accounts}
            value={dest}
            onChange={onDestAccountChange}
            disabled={acctPreviewBusy}
            compact
          />
          {(detailLoading || acctPreviewBusy) && (
            <div style={{ fontSize: 11, color: MUTED, fontStyle: 'italic' }}>Updating sizing & gates…</div>
          )}
        </section>
      </div>

      {/* Intel + oversight — always show oversight controls */}
      <section style={{ padding: '10px 14px', borderTop: '1px solid rgba(148,163,184,.12)', background: 'rgba(15,23,42,.35)' }}>
        {detailLoading && !intel && (
          <div style={{ fontSize: 10, color: MUTED, fontStyle: 'italic', marginBottom: 8 }}>Loading decision context…</div>
        )}
        <BrokerIntelPanel
          intel={intel || { ok: true, oversight: ov, agent_reviews: ov.agents?.reviews || [] }}
          compact
          onQueueOversight={onQueueOversight}
          onRunCloudOversight={onRunCloudOversight}
          oversightBusy={oversightBusy}
          cloudBusy={cloudBusy}
          suppressViolationList={cardShowsBlockers}
          suppressStrategyPurpose
          suppressCompanyPurpose={!!tickerCtx.companyLine}
          sourceKind={String(p.discovery_source || p.origin || '')}
        />
        {oversightMsg && (
          <div style={{ fontSize: 11.5, marginTop: 6, color: oversightMsg.startsWith('✅') ? GREEN : AMBER }}>{oversightMsg}</div>
        )}
      </section>

      {/* Actions */}
      <footer style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        padding: '10px 14px', background: 'rgba(0,0,0,.25)', borderTop: '1px solid rgba(148,163,184,.1)',
      }}>
        {routeMsg && (
          <span style={{ fontSize: 10, color: routeMsg.startsWith('✅') || routeMsg.startsWith('📝') ? GREEN : routeMsg.startsWith('🔒') || routeMsg.startsWith('🔐') ? PURPLE : AMBER, flex: '1 1 100%' }}>
            {routeMsg}
          </span>
        )}
        {routeIntent && onConfirmRoute && (
          <div style={{ flex: '1 1 100%', display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 10px', borderRadius: 8, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.22)' }}>
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
        {routeBlockReason && !fid && (
          <div style={{ flex: '1 1 100%', display: 'flex', alignItems: 'flex-start', gap: 6, padding: '7px 10px', borderRadius: 7, background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.3)' }}>
            <span style={{ fontSize: 12, lineHeight: 1.2 }}>⛔</span>
            <span style={{ fontSize: 11, color: '#fca5a5', fontWeight: 600, lineHeight: 1.4 }}>
              <b style={{ color: RED }}>Auto-route blocked:</b> {routeBlockReason}
              {expLabel && expLabel !== 'expired' && <span style={{ color: MUTED, fontWeight: 500 }}> · stays in this state until it expires in {expLabel}</span>}
            </span>
          </div>
        )}
        <ActionButton variant="secondary" size="md" onClick={onManual}
          style={{ border: `1px solid ${BLUE}`, color: BLUE, fontWeight: 800 }}
          title="Log fill after executing in FA or Schwab">
          ✓ Executed manually
        </ActionButton>
        {onReject && (
          <ActionButton variant="secondary" size="md" disabled={actionBusy} onClick={onReject}
            style={{ border: `1px solid ${RED}`, color: RED, fontWeight: 700 }}
            title="Reject — removes from active queue">
            Reject
          </ActionButton>
        )}
        {onExpire && (
          <ActionButton variant="secondary" size="md" disabled={actionBusy} onClick={onExpire}
            style={{ border: `1px solid ${MUTED}`, color: MUTED, fontWeight: 700 }}
            title="Expire — archive invalid thesis">
            Expire
          </ActionButton>
        )}
        <span style={{ flex: 1 }} />
        <ActionButton
          variant={routeBlocked && !fid ? 'disabled' : 'primary'}
          size="md"
          disabled={(routeBlocked && !fid) || routeBusy}
          onClick={onRoute}
          title={routeBlocked
            ? (tradePlanBlocked
              ? 'No authoritative trade plan — run cards/bridge before live route'
              : 'Resolve hard blocks (cash, market, trade plan) first')
            : (fid ? 'Record-only at Fidelity' : 'Review trade → request Schwab 2FA')}
          style={fid ? { background: `${PURPLE}33`, color: PURPLE, border: `1px solid ${PURPLE}` } : { background: `${AMBER}22`, color: AMBER, border: `1px solid ${AMBER}` }}
        >
          {routeBusy ? '…' : fid ? 'Record proposal' : routeIntent ? 'Re-review route' : 'Auto route (2FA)'}
        </ActionButton>
      </footer>
    </article>
  )
}

