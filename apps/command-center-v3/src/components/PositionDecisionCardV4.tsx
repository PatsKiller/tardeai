import { useState, useEffect, type CSSProperties } from 'react'
import { fmt$ } from '../lib/format'
import ProAnalystPill from './ProAnalystPill'
import PreflightChangedPanel from './PreflightChangedPanel'
import { resolvedTrailPct } from '../lib/protectionTrail'
import { runProtectiveStopPreflight, unwrapApi, type PreflightDiff } from '../lib/protectiveStopPreflight'
import { buildStopLogic, type StopOrderKind } from '../lib/stopManagement'
import { formatReviewStamp, stopReviewTooltip } from '../lib/stopReviewTooltip'
import { WL, heroStateStyle, numStyle } from '../lib/watchlistCardTokens'
import { composeWhy } from '../lib/watchlistCardV4'
import { buttonStyle, type ActionUrgency, type CardVerdict } from '../lib/watchlistCardAction'
import { useTerminalUi } from '../lib/terminalUi'
import { cardShell, modRow, modLabel, ctxLine, ctxKey, statusStrip } from '../lib/terminalCardTheme'
import { BB, terminalRail, terminalVerdictColor, terminalVerdictBg, terminalButton } from '../lib/watchlistTerminalTokens'
import CloudLlmRunButtons from './CloudLlmRunButtons'

// Position Decision Card v4 — open-trades surface joins the v4 card family (2026-07-04).
// Same props + behavior as PositionDecisionCard (v3 untouched; global cc.cards.v4 toggle
// selects). One tinted two-row hero owns the card; everything below is calm module rhythm.
// The protective-stop machinery (Stage 2c 2FA flow, preflight, synthetic/fractional,
// scale control) is carried over from v3 VERBATIM — presentation only changed.
//
// ─── FIELD PARITY CHECKLIST — every field v3 PositionDecisionCard renders → v4 home ───
// [PASS] symbol ................................ header identity
// [PASS] ProAnalystPill (paMap) ................ header identity
// [PASS] shares · hold_duration ................ header identity
// [PASS] symCard.description ................... Context module "Company" line (full text in tooltip)
// [PASS] symCard.vs_sector_week ................ Context module "Company" line (signed, colored)
// [PASS] watchlist_state (directive/watchlist) . header right tag
// [PASS] PAPER/REAL · account (broker/env tip) . header right tag
// [PASS] operator_priority ..................... header right tag + drives hero tint
// [PASS] protection_state ...................... hero row 2 protection status dot
// [PASS] operator_decision ..................... hero row 1 state word + sentence
// [PASS] decision_reason ....................... hero row 1 sentence (composeWhy dedupe; full in tooltip)
// [PASS] primary_next_review ................... hero row 2 "next: …"
// [PASS] ScaleControl (scale in/out flow) ...... Scale module (identical preview→confirm flow)
// [PASS] live broker stop line (qty/type/px/status/#id/read-at + review tooltip) … Protection module
// [PASS] Modify / Cancel-stop buttons + cancelMsg … Protection module
// [PASS] coverage oversized / partial warnings . Protection module
// [PASS] protection advisory (family, stop/ref level, trail $ + %, distance %) … Protection module
// [PASS] fund-holding (mf) no-exchange-stop notice … Protection module
// [PASS] queue stop / stop-limit / trailing (ADVISED/OPTIONAL head, ★ rec) … Protection module
// [PASS] Ignore-1-week snooze + snoozeMsg ...... Protection module
// [PASS] fractional block (sell-all @ MKT, arm synthetic) + synthMsg + DAY-TIF note … Protection module
// [PASS] protectionRec.rationale ............... Protection module
// [PASS] reviewed-by LLM lanes (llmCov) ........ Protection module footer
// [PASS] 2FA stop modal (order label/qty/type/TIF, account/route, token-health re-auth banner,
//        ToS ticket mode, either-channel approve, preflight-changed panel, request buttons,
//        stopMsg/stopDone states) .............. modal — v3 logic verbatim
// [PASS] P&L $ (market_value fallback) ......... hero row 1 figure + metrics grid
// [PASS] P&L % ................................. metrics grid (+ hero row 1)
// [PASS] Today move ............................ metrics grid
// [PASS] Market value .......................... metrics grid
// [PASS] Basis (+ basis_quality color) ......... metrics grid
// [PASS] Now (current_price) ................... metrics grid
// [PASS] Stop (placed / advised* + tooltip) .... metrics grid
// [PASS] R multiple (tracked / ~advisory + tooltip) … metrics grid
// [PASS] % from stop (cushion + tooltip) ....... metrics grid
// [PASS] strategy .............................. hero row 2
// [PASS] RSI + rsi_bucket ...................... Context "Technicals" line
// [PASS] trend_label ........................... Context "Technicals" line
// [PASS] sector (+ETF, vs_sector_5d signal color) … Context "Technicals" line
// [PASS] data_freshness ........................ hero row 2 freshness dot
// [PASS] news_freshness + latest_news_age_hours … hero row 2 freshness dot
// [PASS] risk_flags ............................ Context — tamed into ONE red line
// [PASS] opportunity_flags ..................... Context — tamed into ONE teal line
// [PASS] analyst (rating, rating_mean, opinions, target_mean, target_upside_pct) … Context "Analysts" line
// [PASS] earnings_date (amber ≤7d) ............. Context "Earnings" line
// [PASS] strategy_rationale ("Why …") .......... Context "Why" line
// [PASS] recommended_manual_actions (≤4) ....... hero row 1 buttons (first inline, rest in ⋯ menu)
// [PASS] more/less (expanded/onToggle) ......... News & catalysts module expander control
// [PASS] drill (onDrill) ....................... hero row 1 Drill button + whole-card click
// [PASS] news items (source, age_hours + stale, title/url link, why_it_matters) … News expander
// [PASS] SMA50 · SMA200 · RVOL · sector label · last_hermes_review_at … News expander footer line
// ────────────────────────────────────────────────────────────────────────────────────

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const TEAL = WL.signal.teal

const chip = (bg: string, fg: string, strong = false) => ({ fontSize: strong ? 10 : 9, fontWeight: strong ? 850 : 750, padding: strong ? '3px 8px' : '2px 7px', borderRadius: 5, background: bg, color: fg, whiteSpace: 'nowrap' as const, display: 'inline-block', border: `1px solid ${fg}44` })
const num = (v: any, d = 2) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d))
const pct = (v: any) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`)
const BASIS_C: Record<string, string> = { broker: TEAL, tax_grade: TEAL, verified: TEXT2, entry: TEXT2, owner_provided: AMBER, unknown: RED }
const FRESH_C: Record<string, string> = { fresh: TEAL, aging: WL.signal.amber, stale: WL.signal.red, none: WL.text.dim }
const LANE_META: Record<string, { label: string; c: string }> = { local: { label: 'GEMMA', c: '#2dd4bf' }, grok: { label: 'GROK', c: AMBER }, chatgpt: { label: 'GPT', c: '#a3e635' }, claude: { label: 'CLAUDE', c: '#d97757' } }
const SCHWAB_SELL_ALL_MAX_SHARES = 40

// The REAL failure reason is often nested in result.error (e.g. a Schwab transport error like an expired
// refresh token) — dig there first so the operator sees the actual cause, not a generic "failed".
const apiReason = (j: any) => j?.result?.error ?? j?.error ?? j?.reason ?? j?.message ?? j?.hint ?? 'request failed'
const internalBlockMessage = (r: any) => {
  const reason = r?.reason || apiReason(r)
  if (r?.broker_submitted === false && (r?.stage === 'evidence_revalidation' || String(reason).includes('no_evidence_bound_approval'))) {
    return 'Trade AI blocked submit before Schwab: missing evidence-bound approval. No broker order was sent.'
  }
  if (r?.broker_submitted === false) {
    return `Trade AI blocked submit before Schwab: ${reason}. No broker order was sent.`
  }
  return null
}

/** Position state word — derived from the existing operator_decision / recommended actions.
 *  PROTECT = protection gap needs an order · ACT = trim/exit/sell decision · REVIEW = operator
 *  review asked · MONITOR = no action needed. Mapped onto the shared hero tint scale. */
function deriveState(p: any): { word: string; verdict: CardVerdict; urgency: ActionUrgency } {
  const d = String(p.operator_decision ?? '').toLowerCase()
  const critical = String(p.operator_priority ?? '') === 'critical'
  if (d.includes('protect')) return { word: 'PROTECT', verdict: 'FIX', urgency: critical ? 'red' : 'amber' }
  if (/(trim|exit|sell|reduce|close)/.test(d)) return { word: 'ACT', verdict: 'FIX', urgency: critical ? 'red' : 'amber' }
  if (d.includes('review')) return { word: 'REVIEW', verdict: 'WAIT', urgency: 'amber' }
  if (!d || d.includes('no action') || d.includes('monitor')) {
    if ((p.recommended_manual_actions ?? []).length && p.protection_state !== 'protected' && ['critical', 'high'].includes(p.operator_priority)) {
      return { word: 'REVIEW', verdict: 'WAIT', urgency: 'amber' }
    }
    return { word: 'MONITOR', verdict: 'WATCH', urgency: 'none' }
  }
  return { word: 'REVIEW', verdict: 'WAIT', urgency: ['critical', 'high'].includes(p.operator_priority) ? 'amber' : 'none' }
}

function Expander({ open, onToggle, label }: { open: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={e => { e.stopPropagation(); onToggle() }}
      style={{ fontSize: 10.5, fontWeight: 700, color: WL.text.dim, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
    >{label} {open ? '▴' : '▾'}</button>
  )
}

const tag: CSSProperties = { fontSize: 9, fontWeight: 800, letterSpacing: '.06em', borderRadius: 4, padding: '1px 6px', whiteSpace: 'nowrap', flexShrink: 0 }

function M({ label, value, color = WL.text.primary, title }: any) {
  return <div title={title} style={{ minWidth: 0 }}>
    <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: WL.text.dim }}>{label}</div>
    <div style={{ ...numStyle, fontSize: 14.5, fontWeight: 700, color, marginTop: 2, cursor: title ? 'help' : undefined }}>{value}</div>
  </div>
}

export default function PositionDecisionCardV4({ p, paMap, expanded, onToggle, onDrill, onAction, llmCov, protectionRec, symCard }: any) {
  const [terminalUi] = useTerminalUi()
  const t = p.technical || {}, sr = p.sector_relative || {}
  const news: any[] = p.news ?? []
  const lanes: Record<string, any> = {}
  for (const c of (llmCov ?? [])) { const k = LANE_META[c.lane] ? c.lane : 'local'; if (!lanes[k] || c.last_at > lanes[k].last_at) lanes[k] = c }
  const paper = p.environment === 'paper' || String(p.account ?? '').toLowerCase().includes('paper')
  const pnlColor = (p.unrealized_pnl ?? 0) >= 0 ? WL.price.up : WL.price.down
  const basis = p.basis_reliable ? num(p.entry_price) : 'n/a'
  // R-multiple fallback: imported holdings have no tracked R (no strategy entry+stop). When the stored
  // r_multiple is null but we have a reliable basis (entry), a current price, and an advised stop BELOW
  // entry (real downside risk), express current P&L in R units against that advised stop. Marked "~"
  // (advisory). The "Stop" field falls back to the advised stop (marked "*"). Funds (no basis/price) stay '—'.
  const _advStop = protectionRec ? (Number(protectionRec.stop_price) || null) : null
  const _entry = p.basis_reliable ? (Number(p.entry_price) || null) : null
  const _now = Number(p.current_price) || null
  const _rTracked = p.r_multiple != null
  const _rAdvisory = (!_rTracked && _entry && _now && _advStop && (_entry - _advStop) > 0)
    ? (_now - _entry) / (_entry - _advStop) : null
  const _rShow = _rTracked ? Number(p.r_multiple) : _rAdvisory

  // ── Protective-stop order machinery — carried over from v3 verbatim (Stage 2c) ──
  const _acct = String(p.account ?? '')
  const _sym = String(p.symbol ?? '').toUpperCase()
  const _isSchwab = _acct.startsWith('schwab')
  const _isFidelity = _acct.startsWith('fidelity') && _acct !== 'fidelity_401k'
  const [stopOrder, setStopOrder] = useState<any>(null)   // {kind, qty, stop, trailPct, label}
  const [stopTk, setStopTk] = useState('')                // type-the-ticker (web 2FA channel)
  const [stopCode, setStopCode] = useState('')            // telegram/email one-time code (other channel)
  const [stopBusy, setStopBusy] = useState(false)
  const [stopMsg, setStopMsg] = useState('')
  const [stopIntent, setStopIntent] = useState<string>('')   // intent_id once 2FA requested (approve phase)
  const [stopTicket, setStopTicket] = useState<string>('')   // ticket string when account has no API
  const [stopDone, setStopDone] = useState(false)
  const [validating, setValidating] = useState(false)
  const [preflightDiff, setPreflightDiff] = useState<PreflightDiff | null>(null)
  const [pendingAction, setPendingAction] = useState<{ kind: 'request' } | { kind: 'confirm'; channel: 'web' | 'telegram' } | null>(null)
  const [advisoryOverride, setAdvisoryOverride] = useState<any>(null)
  const [liveStopOverride, setLiveStopOverride] = useState<any>(null)
  const effectiveProtectionRec = advisoryOverride ? { ...protectionRec, ...advisoryOverride } : protectionRec
  const _bstop = (p as any).broker_stop as any
  const effectiveBrokerStop = liveStopOverride ?? _bstop
  const _trailRes = resolvedTrailPct(effectiveProtectionRec)
  const _trailPct = _trailRes?.pct ?? null
  const _priceTs = p.price_updated_at ?? effectiveProtectionRec?.source_timestamp ?? effectiveProtectionRec?.at ?? null
  const _effectivePrice = Number(effectiveProtectionRec?.price) || Number(p.current_price) || null
  const computeLogic = (orderKind: StopOrderKind, overrides?: {
    quotePrice?: number | null; quoteTs?: string | null; liveStop?: any; advisorySnap?: any
  }) => {
    const px = overrides?.quotePrice ?? _effectivePrice
    const ts = overrides?.quoteTs ?? _priceTs
    const conf = overrides?.liveStop ?? effectiveBrokerStop
    const snap = overrides?.advisorySnap
    const pr = snap ? { ...effectiveProtectionRec, ...snap, price: px } : { ...effectiveProtectionRec, price: px }
    return buildStopLogic({
      h: { ...p, symbol: _sym, account: _acct, current_price: px, price: px, source_timestamp: ts },
      pr,
      monitored: null,
      confirmedStop: conf,
      trailPct: _trailPct,
      orderKind,
      wholeShareConfirmed: false,
      sourceTimestamp: ts,
    })
  }
  const runClickPreflight = async (orderKind: StopOrderKind) => {
    setValidating(true)
    setPreflightDiff(null)
    setPendingAction(null)
    setStopMsg('⏳ Validating quote + advisory + stop logic…')
    const pf = await runProtectiveStopPreflight({
      sym: _sym, acct: _acct, orderKind, trailPct: _trailPct, isSchwab: _isSchwab, isFidelity: _isFidelity,
      priceTimestamp: _priceTs, effectivePrice: _effectivePrice, effectiveConfirmed: effectiveBrokerStop,
      computeLogic,
    })
    if (pf.advisorySnap) {
      setAdvisoryOverride({ ...pf.advisorySnap, price: pf.quoteSnap?.quote_price ?? pf.advisorySnap.price })
    }
    if (pf.liveSnap && pf.liveSnap !== effectiveBrokerStop) setLiveStopOverride(pf.liveSnap)
    setValidating(false)
    return pf
  }
  // Schwab OAuth token health — surfaced UP FRONT so a dead/expired refresh token shows "re-auth needed"
  // BEFORE an order attempt (the freshness timestamp alone can read healthy while Schwab has revoked it).
  const [tokenHealth, setTokenHealth] = useState<any>(null)
  const _needsReauth = _isSchwab && tokenHealth?.needs_reauth === true
  useEffect(() => {
    if (!_isSchwab || !stopOrder || tokenHealth) return
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth(unwrapApi(j))).catch(() => {})
  }, [_isSchwab, stopOrder, tokenHealth])
  const _resetStop = () => {
    setStopOrder(null); setStopTk(''); setStopCode(''); setStopMsg(''); setStopIntent(''); setStopTicket(''); setStopDone(false)
    setValidating(false); setPreflightDiff(null); setPendingAction(null); setAdvisoryOverride(null); setLiveStopOverride(null)
  }
  // "Ignore stop for a week" — operator acknowledgement granting a 7-day grace period. Suppresses the stop
  // ALERT (stop_snooze table); advisory only — does NOT change or cancel the protective stop at the broker.
  const [snoozeBusy, setSnoozeBusy] = useState(false)
  const [snoozeMsg, setSnoozeMsg] = useState('')
  const _snoozeStop = async () => {
    setSnoozeBusy(true); setSnoozeMsg('')
    try {
      const r = await fetch('/api/v2/holdings/stop-snooze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: p.symbol, days: 7 }) }).then(x => x.json())
      setSnoozeMsg(r?.ok ? `✓ Acknowledged — ${p.symbol} stop alert snoozed 1 week (until ${String(r.snoozed_until).slice(0, 10)}); protective stop unchanged` : `failed: ${r?.error ?? '—'}`)
    } catch { setSnoozeMsg('snooze failed — retry') } finally { setSnoozeBusy(false) }
  }
  // Fractional Schwab positions can't hold a resting broker STOP (Schwab rejects fractional stops) — arm a
  // SYNTHETIC stop instead: a monitored level that, on breach, requests a Market-Day sell-all 2FA.
  const _shares = Number(p.shares) || 0
  const _isFractional = _isSchwab && _shares > 0 && Math.abs(_shares - Math.round(_shares)) > 1e-9
  const _needsSellAll = _isSchwab && _shares > 0 && _shares < SCHWAB_SELL_ALL_MAX_SHARES
  const _sellAllTif = _isFractional ? 'DAY' : 'GTC'
  const [synthBusy, setSynthBusy] = useState(false)
  const [synthMsg, setSynthMsg] = useState('')
  const _openSellAll = () => {
    if (!window.confirm(`Sell ALL ${_shares} ${p.symbol} @ MARKET (${_sellAllTif}) on ${_acct}? Requires 2FA before submit.`)) return
    _resetStop()
    setStopOrder({
      kind: 'MARKET', qty: _shares, stop: null, trailPct: null,
      label: `SELL ALL ${_shares} ${p.symbol} @ MARKET ${_sellAllTif}`,
      advised: _advStop, cur: Number(p.current_price) || null,
    })
  }
  const _armSynthetic = async (level: number) => {
    setSynthBusy(true); setSynthMsg('')
    try {
      const r = unwrapApi(await fetch('/api/v2/holdings/synthetic-stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: p.symbol, account: p.account, stop_price: level, qty: _shares, note: 'fractional — arm from card' }) }).then(x => x.json()))
      setSynthMsg(r?.ok ? `✓ Synthetic stop armed @ $${Number(level).toFixed(2)} on full ${_shares} sh — on breach you'll get a Market-Day sell-all 2FA (nothing placed at the broker)` : `⛔ ${apiReason(r)}`)
    } catch (e: any) { setSynthMsg('⛔ ' + e.message) } finally { setSynthBusy(false) }
  }
  const preflightAndRequest = async () => {
    if (!stopOrder) return
    const kind = stopOrder.kind as StopOrderKind
    if (kind === 'MARKET') { _requestStop(); return }
    const pf = await runClickPreflight(kind)
    if (!pf.ok) {
      setStopMsg(`⛔ Validation failed — ${pf.blockers?.join(' · ') || pf.error || 'resolve blockers above'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'request' })
      setStopMsg('⚠️ Logic changed since page load — review below, then confirm to proceed.')
      return
    }
    setStopMsg('✓ Validated — proceeding…')
    await _requestStop(true)
  }
  const preflightAndConfirm = async (channel: 'web' | 'telegram') => {
    if (!stopOrder) return
    const kind = stopOrder.kind as StopOrderKind
    const pf = await runClickPreflight(kind)
    if (!pf.ok) {
      setStopMsg(`⛔ Cannot submit — ${pf.blockers?.join(' · ') || 'validation failed'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'confirm', channel })
      setStopMsg('⚠️ Logic changed — confirm again to submit to Schwab.')
      return
    }
    await _confirmStop(channel, true)
  }
  // STEP 1 — request: builds the order + (Schwab/armed) requests per-order 2FA, or returns a ToS ticket.
  const _requestStop = async (skipPreflight = false) => {
    if (!skipPreflight) { await preflightAndRequest(); return }
    setStopBusy(true); setStopMsg('requesting…')
    try {
      const body = { symbol: p.symbol, account: p.account, qty: stopOrder.qty, order_kind: stopOrder.kind,
                     stop_price: stopOrder.kind === 'MARKET' ? null : stopOrder.stop,
                     trail_pct: stopOrder.trailPct ?? null,
                     advised_stop: stopOrder.advised ?? null, current_price: stopOrder.cur ?? null,
                     replace_order_id: stopOrder.replace_order_id ?? null }
      const raw = await fetch('/api/v2/holdings/protective-stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
      const r = unwrapApi(raw)
      if (r?.mode === 'awaiting_approval') {
        if (!r.intent_id) { setStopMsg('⛔ Approval request returned no intent_id — cannot confirm. Check backend protective-stop endpoint.'); return }
        setStopIntent(r.intent_id)
        const short = String(r.intent_id).slice(0, 8)
        const ttl = r.ttl_min ? ` · expires ${r.ttl_min}min` : ''
        setStopMsg(`Intent ${short}${ttl} · approve by ticker or 6-digit code · one channel is enough`)
      }
      else if (r?.mode === 'ticket') { setStopTicket(r.ticket); setStopMsg('✅ ToS ticket ready — place it exactly in thinkorswim (no trading API on this account).') }
      else if (r?.mode === 'monitored_armed') {
        const tk = r?.result?.ticket || r?.order?.ticket || ''
        if (tk) setStopTicket(tk)
        setStopDone(true)
        setStopMsg(`✅ Monitored stop armed — tracking ${p.symbol}. On breach: alert + Fidelity Active Trader ticket.`)
      }
      else setStopMsg(`⛔ ${apiReason(r)}`)
    } catch (e: any) { setStopMsg('⛔ ' + e.message) } finally { setStopBusy(false) }
  }
  // STEP 2 — confirm the per-order 2FA (EITHER channel) and submit LIVE.
  const _confirmStop = async (channel: 'web' | 'telegram', skipPreflight = false) => {
    if (!stopIntent) { setStopMsg('⛔ no active stop intent — click REQUEST LIVE STOP first'); return }
    if (!skipPreflight) { await preflightAndConfirm(channel); return }
    setStopBusy(true); setStopMsg(channel === 'web' ? 'confirming by ticker…' : 'confirming by code…')
    try {
      const code = channel === 'web' ? stopTk.trim().toUpperCase() : stopCode.trim()
      const raw = await fetch('/api/v2/holdings/protective-stop/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent_id: stopIntent, channel, code }) }).then(x => x.json())
      const r = unwrapApi(raw)
      const oid = r?.broker_order_id ?? r?.order_id ?? r?.result?.broker_order_id
      const ostatus = r?.status ?? r?.order_status ?? r?.result?.status
      const submitted = ostatus === 'submitted' || ostatus === 'filled' || r?.submitted === true
      // TRUE submit success — a broker order id / submitted|filled status, and ok not explicitly false.
      if ((r?.stage === 'submit' || submitted || oid) && submitted && r?.ok !== false) {
        setStopDone(true)
        setStopMsg(stopOrder?.kind === 'MARKET'
          ? `✅ LIVE sell placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`
          : `✅ LIVE stop placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`)
      }
      // 2FA accepted, still waiting on the other channel
      else if (r?.stage === 'confirm' && r?.ok && r?.fully_approved === false) {
        setStopMsg('channel confirmed — waiting on the other factor')
      }
      // approval accepted but the broker submit did NOT confirm (e.g. Schwab token expired) — DO NOT claim
      // success; show the real cause (result.error) so the operator knows exactly what to fix.
      else if (r?.mode === 'blocked' || r?.broker_submitted === false) {
        setStopMsg(`⛔ ${internalBlockMessage(r) ?? apiReason(r)}`)
      }
      else if (r?.stage === 'submit' && (ostatus === 'error' || r?.ok === false)) {
        setStopMsg(`⛔ Schwab rejected the submitted order: ${apiReason(r)}`)
      }
      else if (r?.ok && r?.fully_approved === true && !oid && !submitted) {
        setStopMsg('✅ approval accepted, but submit result was not returned — refresh broker orders / stop monitor to verify before retrying')
      }
      else setStopMsg(`⛔ ${apiReason(r)}`)
    } catch (e: any) { setStopMsg('⛔ ' + e.message) } finally { setStopBusy(false) }
  }
  // FULL STOP MONITORING — the live broker stop now showing on this card, + cancel ("remove") control.
  const _stopReviewTip = stopReviewTooltip({
    advisoryAt: protectionRec?.at, advisoryModel: protectionRec?.model,
    priceAt: p.price_updated_at,
    brokerFetchedAt: effectiveBrokerStop?.fetched_at,
    brokerOrderId: effectiveBrokerStop?.order_id,
  })
  const [cancelBusy, setCancelBusy] = useState(false)
  const [cancelMsg, setCancelMsg] = useState('')
  const _cancelStop = async () => {
    if (!effectiveBrokerStop?.order_id) return
    if (!window.confirm(`Cancel the live ${effectiveBrokerStop.order_type} on ${p.symbol} (#${effectiveBrokerStop.order_id}) at the broker?`)) return
    setCancelBusy(true); setCancelMsg('cancelling…')
    try {
      const r = await fetch('/api/v2/holdings/protective-stop/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account: p.account, broker_order_id: effectiveBrokerStop.order_id, symbol: p.symbol }) }).then(x => x.json())
      if (r?.ok) setCancelMsg(`✅ cancel sent (${r.status}) — refreshing…`)
      else setCancelMsg(`⛔ ${r?.error ?? r?.hint ?? 'cancel failed'}`)
    } catch (e: any) { setCancelMsg('⛔ ' + e.message) } finally { setCancelBusy(false) }
  }
  // MODIFY = cancel the existing stop + place a new one at the current advised level, in one 2FA step.
  const _openModify = () => {
    if (!effectiveBrokerStop) return
    const rec: any = effectiveProtectionRec || {}
    const advStop = Number(rec.stop_price) || (Number(effectiveBrokerStop.stop_price) || null)
    const recPrice = Number(rec.price) || (Number(p.current_price) || null)
    const off = rec.trail_recommended ? Number(rec.trail_offset) : null
    const isTrail = !!rec.trail_recommended || String(effectiveBrokerStop.order_type || '').includes('TRAILING')
    const trailPct = off == null ? null : rec.trail_type === 'PERCENT' ? off : (recPrice ? off / recPrice * 100 : null)
    const kind = isTrail && trailPct != null ? 'TRAILING' : 'STOP'
    const label = kind === 'TRAILING'
      ? `MODIFY → SELL ${p.shares} ${p.symbol} TRAILING STOP ${trailPct?.toFixed(0)}% GTC`
      : `MODIFY → SELL ${p.shares} ${p.symbol} STOP $${(advStop ?? 0).toFixed(2)} GTC`
    _resetStop()
    setStopOrder({
      kind, qty: p.shares, stop: advStop, trailPct: kind === 'TRAILING' ? trailPct : null, label,
      advised: advStop, cur: recPrice,
      // Any live Schwab stop (pilot or manual ToS) — transport cancel-then-places after 2FA.
      replace_order_id: effectiveBrokerStop.order_id || null,
    })
  }
  // ── end carried-over machinery ──

  // ── v4 presentation derivations ──
  const state = deriveState(p)
  const heroState = heroStateStyle(state.verdict, state.urgency)
  const rail = terminalUi ? terminalRail(state.verdict, state.urgency) : heroState.rail
  const heroBg = terminalUi ? terminalVerdictBg(state.verdict, state.urgency) : heroState.bg
  const heroAccent = terminalUi ? terminalVerdictColor(state.verdict, state.urgency) : heroState.accent
  const heroBorder = terminalUi ? BB.border : heroState.border
  // Rule-of-one hero sentence — operator decision + reason, restatements deduped.
  const whyLine = composeWhy([p.operator_decision ?? 'No action — monitored', p.decision_reason])
  const heroTip = [p.operator_decision, p.decision_reason, p.primary_next_review ? `Next: ${p.primary_next_review}` : null].filter(Boolean).join('\n')

  const drillCtx = {
    title: `${p.symbol} — ${p.account}`,
    subtitle: `${p.strategy ?? ''} · ${p.broker}/${p.environment}`,
    endpoint: '/api/v2/open-trades/intelligence',
    rows: [p], subjectType: 'position', subjectKey: p.symbol,
  }
  const recs: string[] = (p.recommended_manual_actions ?? []).slice(0, 4)
  const inlineRec = recs[0] ?? null
  const menuRecs = recs.slice(1)
  const [menuOpen, setMenuOpen] = useState(false)

  // Protection status for hero row 2 — one dot, one phrase; detail lives in the Protection module.
  const protColor = p.protection_state === 'protected' ? TEAL : p.protection_state === 'partial' ? WL.signal.amber : WL.signal.red
  const protText = effectiveBrokerStop
    ? `protected — stop ${effectiveBrokerStop.stop_price != null ? `$${Number(effectiveBrokerStop.stop_price).toFixed(2)}` : String(effectiveBrokerStop.order_type || 'working').replace('_', ' ').toLowerCase()} at broker`
    : p.protection_state === 'protected' ? 'protected'
    : _advStop != null ? `${p.protection_state ?? 'unprotected'} — advised stop $${_advStop.toFixed(2)} not placed`
    : (p.protection_state ?? 'unprotected')
  const dataFresh = String(p.data_freshness ?? 'none')
  const newsFresh = String(p.news_freshness ?? 'none')
  const newsAge = p.latest_news_age_hours != null ? ` ${Math.round(p.latest_news_age_hours)}h` : ''

  const riskFlags: string[] = p.risk_flags ?? []
  const oppFlags: string[] = p.opportunity_flags ?? []
  const earnDays = p.earnings_date ? Math.ceil((new Date(String(p.earnings_date)).getTime() - Date.now()) / 86400000) : null
  const earnSoon = earnDays != null && earnDays >= 0 && earnDays <= 7
  const vs5 = sr.vs_sector_5d
  const vs5Color = vs5 == null ? WL.text.secondary : vs5 > 1 ? TEAL : vs5 < -1 ? WL.signal.red : WL.text.secondary

  const priTag = String(p.operator_priority || 'low')
  const priColor = priTag === 'critical' ? WL.signal.red : priTag === 'high' ? WL.signal.amber : WL.text.dim

  return <div
    onClick={() => onDrill(drillCtx)}
    style={cardShell(rail, terminalUi)}
  >
    {/* ── Protective-stop confirmation modal — v3 flow verbatim: EXACT proposed order + per-order 2FA
        (type ticker OR one-time code — either channel). Schwab submits via API; Fidelity = ToS ticket. ── */}
    {stopOrder && (() => {
      const tkOk = stopTk.trim().toUpperCase() === String(p.symbol).toUpperCase()
      const codeOk = /^\d{6}$/.test(stopCode.trim())
      const acctLbl = String(p.account ?? '').replace(/_/g, ' ').toUpperCase()
      const route = _isSchwab ? 'Submits LIVE to Schwab via API (per-order 2FA)' : 'No API on this account → builds a thinkorswim ticket to place manually'
      const inApprove = !!stopIntent && !stopDone
      const isMarketSell = stopOrder.kind === 'MARKET'
      const orderTif = isMarketSell ? _sellAllTif : 'GTC'
      return <div onClick={e => { e.stopPropagation(); if (!stopBusy) _resetStop() }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }}>
        <div onClick={e => e.stopPropagation()} style={{ background: '#0f172a', border: `1px solid ${isMarketSell ? RED : AMBER}`, borderRadius: 12, padding: 18, width: 'min(440px,94vw)', cursor: 'default' }}>
          <div style={{ fontSize: 13, fontWeight: 900, color: isMarketSell ? RED : AMBER }}>{inApprove ? '🔐 Approve to place LIVE' : isMarketSell ? '⚠ Confirm market sell-all' : '⚠ Confirm protective stop'}</div>
          <div style={{ marginTop: 10, padding: 11, background: isMarketSell ? 'rgba(239,68,68,.10)' : 'rgba(245,158,11,.10)', border: `1px solid ${isMarketSell ? 'rgba(239,68,68,.3)' : 'rgba(245,158,11,.3)'}`, borderRadius: 8 }}>
            <div style={{ fontSize: 15, fontWeight: 950, color: TEXT0, ...({ fontFamily: 'monospace' } as any) }}>{stopOrder.label}</div>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 7, fontSize: 11 }}>
              <span style={{ color: MUTED }}>Qty <b style={{ color: TEXT0 }}>{stopOrder.qty}</b></span>
              <span style={{ color: MUTED }}>Type <b style={{ color: TEXT0 }}>{isMarketSell ? 'MARKET' : stopOrder.kind === 'TRAILING' ? `TRAILING ${stopOrder.trailPct?.toFixed(0)}%` : stopOrder.kind}</b></span>
              {!isMarketSell && stopOrder.stop != null && <span style={{ color: MUTED }}>{stopOrder.kind === 'TRAILING' ? 'Start' : 'Stop'} <b style={{ color: TEXT0 }}>${Number(stopOrder.stop).toFixed(2)}</b></span>}
              <span style={{ color: MUTED }}>TIF <b style={{ color: TEXT0 }}>{orderTif}</b></span>
            </div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>Account <b style={{ color: TEXT1 }}>{acctLbl}</b> · {route}</div>
          </div>

          {/* SCHWAB TOKEN HEALTH — re-auth needed banner (shown UP FRONT, before any order attempt) */}
          {_needsReauth && !stopDone && <div style={{ marginTop: 10, padding: 11, background: 'rgba(239,68,68,.12)', border: `1px solid ${RED}`, borderRadius: 8 }}>
            <div style={{ fontSize: 11.5, fontWeight: 900, color: RED }}>⚠ Schwab re-auth needed — orders will be rejected</div>
            <div style={{ fontSize: 10, color: TEXT2, marginTop: 5, lineHeight: 1.45 }}>{tokenHealth?.message || 'Schwab login expired/revoked.'} The refresh token must be renewed by a manual browser login before any live order can submit. Run:</div>
            <div style={{ marginTop: 6, padding: '6px 8px', borderRadius: 6, background: '#1e293b', color: TEXT0, fontSize: 11, ...({ fontFamily: 'monospace' } as any) }}>{tokenHealth?.reauth_command || 'python3 scripts/schwab_token_manager.py reauth-url schwab_taxable'}</div>
          </div>}

          {/* DONE */}
          {stopDone && <div style={{ fontSize: 12, color: '#22c55e', marginTop: 12, fontWeight: 700 }}>{stopMsg}</div>}

          {/* TICKET MODE (no API on this account) */}
          {!stopDone && stopTicket && <div style={{ marginTop: 11 }}>
            <div style={{ fontSize: 10.5, color: TEXT2 }}>Place this exact order in thinkorswim → Monitor → working orders:</div>
            <div style={{ marginTop: 6, padding: '8px 10px', borderRadius: 6, background: '#1e293b', color: TEXT0, fontSize: 13, ...({ fontFamily: 'monospace' } as any) }}>{stopTicket}</div>
          </div>}

          {/* APPROVE PHASE (Schwab live) — EITHER channel: type ticker OR enter code from Telegram/email */}
          {!stopDone && inApprove && <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 10.5, color: TEXT2 }}>A one-time code was sent to <b style={{ color: TEXT1 }}>Telegram + email</b>. Approve by <b style={{ color: TEXT0 }}>either</b>:</div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 9 }}>① type the ticker <b style={{ color: TEXT0 }}>{p.symbol}</b></div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <input autoFocus value={stopTk} onChange={e => setStopTk(e.target.value.toUpperCase())} placeholder={`type ${p.symbol}`}
                style={{ flex: 1, fontSize: 14, padding: '8px 10px', borderRadius: 6, border: `1px solid ${tkOk ? '#22c55e' : 'rgba(148,163,184,.3)'}`, background: '#1e293b', color: TEXT0 }} />
              <button onClick={() => _confirmStop('web')} disabled={stopBusy || !tkOk} style={{ fontSize: 11, fontWeight: 800, padding: '7px 12px', borderRadius: 6, border: 'none', cursor: (stopBusy || !tkOk) ? 'not-allowed' : 'pointer', background: tkOk ? '#b45309' : '#334155', color: tkOk ? '#fff' : '#64748b', whiteSpace: 'nowrap' }}>approve + submit</button>
            </div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 10 }}>② or enter the 6-digit code (Telegram / email)</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <input value={stopCode} onChange={e => setStopCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code" inputMode="numeric"
                style={{ flex: 1, fontSize: 14, padding: '8px 10px', borderRadius: 6, border: `1px solid ${codeOk ? '#22c55e' : 'rgba(148,163,184,.3)'}`, background: '#1e293b', color: TEXT0, letterSpacing: 3, ...({ fontFamily: 'monospace' } as any) }} />
              <button onClick={() => _confirmStop('telegram')} disabled={stopBusy || !codeOk} style={{ fontSize: 11, fontWeight: 800, padding: '7px 12px', borderRadius: 6, border: 'none', cursor: (stopBusy || !codeOk) ? 'not-allowed' : 'pointer', background: codeOk ? '#b45309' : '#334155', color: codeOk ? '#fff' : '#64748b', whiteSpace: 'nowrap' }}>approve + submit</button>
            </div>
            <div style={{ fontSize: 9.5, color: DIM, marginTop: 8, fontStyle: 'italic' }}>This still requires this typed ticker or 6-digit code. No agent bypass.</div>
            <div style={{ fontSize: 9.5, color: MUTED, marginTop: 4 }}>You can also tap ✅ Approve in the Telegram message. Any one is enough.</div>
          </div>}

          {/* REVIEW PHASE — request the order (Schwab requests 2FA; no-API accounts return a ticket) */}
          {!stopDone && !inApprove && !stopTicket && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 11 }}>
            {_isSchwab
              ? (isMarketSell
                ? `Market sell-all of the full ${_shares} sh (fractional OK). Approval goes to Telegram + email; order submits only after you confirm.`
                : 'Requesting will send a one-time approval to Telegram + email; the order is placed only after you confirm (next step).')
              : 'This account has no trading API — you’ll get the exact ToS ticket to place manually.'}
          </div>}

          {pendingAction && preflightDiff && (
            <PreflightChangedPanel
              diff={preflightDiff}
              busy={stopBusy}
              validating={validating}
              onProceed={() => {
                const pa = pendingAction
                setPendingAction(null); setPreflightDiff(null)
                if (pa?.kind === 'request') _requestStop(true)
                else if (pa?.kind === 'confirm') _confirmStop(pa.channel, true)
              }}
              onCancel={() => { setPendingAction(null); setPreflightDiff(null); setStopMsg('') }}
            />
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 13, justifyContent: 'flex-end', alignItems: 'center' }}>
            {stopMsg && !stopDone && <span style={{ fontSize: 10, flex: 1, color: stopMsg.startsWith('✅') ? '#22c55e' : stopMsg.startsWith('⛔') ? '#ef4444' : MUTED }}>{stopMsg}</span>}
            <button onClick={_resetStop} disabled={stopBusy || validating} style={{ fontSize: 11, padding: '7px 12px', borderRadius: 6, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>{stopDone ? 'close' : 'cancel'}</button>
            {!stopDone && !inApprove && !stopTicket && <button onClick={preflightAndRequest} disabled={stopBusy || validating || _needsReauth} title={_needsReauth ? 'Schwab re-auth required before placing a live order' : undefined} style={{ fontSize: 12, fontWeight: 800, padding: '7px 18px', borderRadius: 6, border: 'none', cursor: (stopBusy || validating || _needsReauth) ? 'not-allowed' : 'pointer', background: _needsReauth ? '#334155' : isMarketSell ? RED : '#b45309', color: _needsReauth ? '#64748b' : '#fff' }}>{validating ? 'Validating…' : stopBusy ? '…' : _needsReauth ? 'RE-AUTH NEEDED' : _isSchwab ? (isMarketSell ? 'Request Schwab sell via 2FA' : 'Request Schwab stop via 2FA') : 'Create Fidelity manual ticket'}</button>}
          </div>
        </div>
      </div>
    })()}

    {/* ① Header — identity only; quiet */}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, padding: '11px 18px 9px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
        <span style={{ ...numStyle, fontWeight: 800, fontSize: 21 }}>{p.symbol}</span>
        <span onClick={e => e.stopPropagation()} style={{ flexShrink: 0 }}><ProAnalystPill symbol={p.symbol} map={paMap} compact neutral={false} /></span>
        <span style={{ fontSize: 11, color: WL.text.dim, whiteSpace: 'nowrap' }}>{p.shares} sh · {p.hold_duration ?? '—'}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {p.watchlist_state === 'directive' && <span style={{ ...tag, color: WL.signal.amber, border: '1px solid rgba(245,166,35,.35)' }}>★ DIRECTIVE</span>}
        {p.watchlist_state === 'watchlist' && <span style={{ ...tag, color: WL.text.dim, border: `1px solid ${WL.surface.edge}` }}>WATCHLIST</span>}
        <span title={`${p.broker}/${p.environment}`} style={{ ...tag, color: paper ? WL.text.dim : WL.signal.amber, border: `1px solid ${paper ? WL.surface.edge : 'rgba(245,166,35,.35)'}` }}>{paper ? 'PAPER' : 'REAL'} · {String(p.account ?? '?').replace(/_/g, ' ').toUpperCase()}</span>
        <span style={{ ...tag, color: priColor, border: `1px solid ${priTag === 'critical' || priTag === 'high' ? `${priColor}55` : WL.surface.edge}` }}>{priTag.toUpperCase()}</span>
      </div>
    </div>

    {/* ② Decision hero — terminal: single horizontal strip; legacy: two-row tinted block */}
    <div
      onClick={e => e.stopPropagation()}
      style={terminalUi
        ? { ...statusStrip(heroBg, true), cursor: 'default' }
        : {
            background: heroBg,
            borderTop: `1px solid ${heroBorder}`,
            borderBottom: `1px solid ${heroBorder}`,
            padding: '11px 18px 10px',
            display: 'flex', flexDirection: 'column', gap: 7, cursor: 'default',
          }}
    >
      {terminalUi ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', width: '100%' }}>
          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.1em', color: heroAccent, flexShrink: 0 }}>{state.word}</span>
          <span title={heroTip} style={{ fontSize: 11, fontWeight: 700, color: WL.text.primary, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {whyLine}
          </span>
          {p.unrealized_pnl != null && (
            <span style={{ ...numStyle, fontSize: 11, fontWeight: 800, color: pnlColor, flexShrink: 0 }} title={`Unrealized P&L (${pct(p.unrealized_pnl_pct)})`}>
              {fmt$(p.unrealized_pnl)}{p.unrealized_pnl_pct != null ? ` · ${pct(p.unrealized_pnl_pct)}` : ''}
            </span>
          )}
          <span title={_stopReviewTip || undefined} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: WL.text.secondary, fontWeight: 700, fontSize: 10 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: protColor, flex: 'none' }} />
            {protText}
          </span>
          <span title={`Position data freshness: ${dataFresh}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: WL.text.dim, fontSize: 10 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: FRESH_C[dataFresh] ?? WL.text.dim, flex: 'none' }} />
            data {dataFresh}
          </span>
          <span title={`News freshness: ${newsFresh}${newsAge ? ` · latest ${newsAge.trim()} old` : ''}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: WL.text.dim, fontSize: 10 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: FRESH_C[newsFresh] ?? WL.text.dim, flex: 'none' }} />
            news {newsFresh}{newsAge}
          </span>
          <span style={{ color: WL.text.secondary, fontWeight: 700, textTransform: 'capitalize', fontSize: 10 }}>{String(p.strategy ?? 'unclassified').replace(/_/g, ' ')}</span>
          {p.primary_next_review && <span style={{ color: WL.text.dim, fontSize: 10 }}>next: {p.primary_next_review}</span>}
          <span style={{ display: 'inline-flex', gap: 5, flexShrink: 0, position: 'relative', marginLeft: 'auto' }}>
            {inlineRec && (
              <button onClick={e => { e.stopPropagation(); onAction?.(inlineRec, p) }} title="Operator review action only" style={terminalButton('primary')}>{inlineRec}</button>
            )}
            <button onClick={e => { e.stopPropagation(); onDrill(drillCtx) }} style={terminalButton('secondary')}>Drill</button>
            {menuRecs.length > 0 && (
              <button onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }} style={terminalButton('ghost')} aria-label="More actions">⋯</button>
            )}
            {menuOpen && menuRecs.length > 0 && (
              <div style={{
                position: 'absolute', top: '110%', right: 0, zIndex: 30, minWidth: 168,
                background: '#0d1420', border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
                boxShadow: '0 10px 30px rgba(0,0,0,.5)', padding: 4, display: 'flex', flexDirection: 'column',
              }}>
                {menuRecs.map(a => (
                  <button
                    key={a}
                    onClick={e => { e.stopPropagation(); setMenuOpen(false); onAction?.(a, p) }}
                    style={{ textAlign: 'left', fontSize: 11.5, fontWeight: 600, color: WL.text.secondary, background: 'none', border: 'none', cursor: 'pointer', padding: '7px 10px', borderRadius: 5 }}
                    onMouseEnter={e => { (e.target as HTMLElement).style.background = 'rgba(148,163,184,.08)' }}
                    onMouseLeave={e => { (e.target as HTMLElement).style.background = 'none' }}
                  >{a}</button>
                ))}
              </div>
            )}
          </span>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.1em', color: heroAccent, flexShrink: 0 }}>{state.word}</span>
            <span title={heroTip} style={{ fontSize: 13.5, fontWeight: 700, color: WL.text.primary, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              {whyLine}
            </span>
            {p.unrealized_pnl != null && (
              <span style={{ ...numStyle, fontSize: 13.5, fontWeight: 800, color: pnlColor, flexShrink: 0 }} title={`Unrealized P&L (${pct(p.unrealized_pnl_pct)})`}>
                {fmt$(p.unrealized_pnl)}{p.unrealized_pnl_pct != null ? ` · ${pct(p.unrealized_pnl_pct)}` : ''}
              </span>
            )}
            <span style={{ display: 'inline-flex', gap: 7, flexShrink: 0, position: 'relative' }}>
              {inlineRec && (
                <button onClick={e => { e.stopPropagation(); onAction?.(inlineRec, p) }} title="Operator review action only" style={buttonStyle('neutral', true)}>{inlineRec}</button>
              )}
              <button onClick={e => { e.stopPropagation(); onDrill(drillCtx) }} style={buttonStyle('neutral', true)}>Drill</button>
              {menuRecs.length > 0 && (
                <button onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }} style={buttonStyle('neutral', true)} aria-label="More actions">⋯</button>
              )}
              {menuOpen && menuRecs.length > 0 && (
                <div style={{
                  position: 'absolute', top: '110%', right: 0, zIndex: 30, minWidth: 168,
                  background: '#0d1420', border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
                  boxShadow: '0 10px 30px rgba(0,0,0,.5)', padding: 4, display: 'flex', flexDirection: 'column',
                }}>
                  {menuRecs.map(a => (
                    <button
                      key={a}
                      onClick={e => { e.stopPropagation(); setMenuOpen(false); onAction?.(a, p) }}
                      style={{ textAlign: 'left', fontSize: 11.5, fontWeight: 600, color: WL.text.secondary, background: 'none', border: 'none', cursor: 'pointer', padding: '7px 10px', borderRadius: 5 }}
                      onMouseEnter={e => { (e.target as HTMLElement).style.background = 'rgba(148,163,184,.08)' }}
                      onMouseLeave={e => { (e.target as HTMLElement).style.background = 'none' }}
                    >{a}</button>
                  ))}
                </div>
              )}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 11 }}>
            <span title={_stopReviewTip || undefined} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: WL.text.secondary, fontWeight: 700 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: protColor, flex: 'none' }} />
              {protText}
            </span>
            <span title={`Position data freshness: ${dataFresh}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: WL.text.dim }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: FRESH_C[dataFresh] ?? WL.text.dim, flex: 'none' }} />
              data {dataFresh}
            </span>
            <span title={`News freshness: ${newsFresh}${newsAge ? ` · latest ${newsAge.trim()} old` : ''}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: WL.text.dim }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: FRESH_C[newsFresh] ?? WL.text.dim, flex: 'none' }} />
              news {newsFresh}{newsAge}
            </span>
            <span style={{ color: WL.text.secondary, fontWeight: 700, textTransform: 'capitalize' }}>{String(p.strategy ?? 'unclassified').replace(/_/g, ' ')}</span>
            {p.primary_next_review && <span style={{ color: WL.text.dim, marginLeft: 'auto' }}>next: {p.primary_next_review}</span>}
          </div>
        </>
      )}
    </div>

    {/* ③ Position metrics */}
    <div onClick={e => e.stopPropagation()} style={{ ...modRow(terminalUi), borderTop: 'none', cursor: 'default' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))', gap: 10 }}>
        <M label="P&L" value={p.unrealized_pnl != null ? fmt$(p.unrealized_pnl) : fmt$(p.market_value ?? 0)} color={p.unrealized_pnl != null ? pnlColor : WL.text.primary} />
        <M label="P&L %" value={pct(p.unrealized_pnl_pct)} color={(p.unrealized_pnl_pct ?? 0) >= 0 ? WL.price.up : WL.price.down} />
        <M label="Today" value={pct(p.today_move_pct)} color={(p.today_move_pct ?? 0) >= 0 ? WL.price.up : WL.price.down} />
        <M label="Mkt value" value={fmt$(p.market_value ?? 0, 0)} />
        <M label="Basis" value={basis} color={BASIS_C[p.basis_quality] || WL.text.secondary} title={p.basis_quality ? `basis quality: ${p.basis_quality}` : undefined} />
        <M label="Now" value={num(p.current_price)} />
        <M label="Stop" title={_stopReviewTip || (p.stop_price == null && _advStop != null ? 'Advised stop (no protective stop placed at the broker yet)' : undefined)}
          value={p.stop_price != null ? num(p.stop_price) : _advStop != null ? `${num(_advStop)}*` : '—'}
          color={p.stop_price != null ? WL.signal.red : _advStop != null ? WL.signal.amber : WL.text.dim} />
        <M label="R multiple"
          title={_rAdvisory != null ? 'Advisory R: current P&L ÷ risk to the ADVISED stop (this holding has no strategy-tracked entry/stop, so R is computed against the Hermes advised stop)' : _rShow == null ? 'No R — needs a basis (entry) and an advised stop below entry; funds/unverified-basis positions stay blank' : undefined}
          value={_rShow != null ? `${_rAdvisory != null ? '~' : ''}${num(_rShow, 1)}R` : '—'}
          color={_rShow == null ? WL.text.dim : _rShow >= 1 ? TEAL : _rShow >= 0 ? WL.signal.amber : WL.signal.red} />
        {(() => {
          // % from stop — live cushion above the placed (or advised) stop. The monitor field: as it
          // shrinks toward 0% the stop is about to trigger. Uses the placed stop if present, else advised.
          const _s = p.stop_price != null ? Number(p.stop_price) : _advStop
          const _n = Number(p.current_price) || null
          const _d = (_s && _n) ? ((_n - _s) / _n) * 100 : null
          return <M label="% from stop"
            title={_d == null ? 'No stop reference yet (no placed/advised stop, or no price)' : `Current price is ${_d.toFixed(1)}% above the ${p.stop_price != null ? 'placed' : 'advised'} stop ($${Number(_s).toFixed(2)}) — your downside cushion. Watch this: <3% means the stop is close to triggering.`}
            value={_d == null ? '—' : `${_d >= 0 ? '+' : ''}${_d.toFixed(1)}%`}
            color={_d == null ? WL.text.dim : _d < 3 ? WL.signal.red : _d < 8 ? WL.signal.amber : TEAL} />
        })()}
      </div>
    </div>

    {/* ④ Protection & stops — full Stage 2c surface (v3 content, calm container) */}
    {(effectiveBrokerStop || effectiveProtectionRec || Object.keys(lanes).length > 0) && <div onClick={e => e.stopPropagation()} style={{ ...modRow(terminalUi), cursor: 'default' }}>
      <div style={modLabel(terminalUi)}><span>Protection & stops</span></div>
      {/* FULL STOP MONITORING — a LIVE protective stop is working at the broker (source of truth). */}
      {effectiveBrokerStop && <div title={_stopReviewTip} style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '8px 10px', borderRadius: 8, background: 'rgba(45,212,191,.07)', border: '1px solid rgba(45,212,191,.30)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', cursor: 'help' }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: TEAL }}>✓ PROTECTED — {effectiveBrokerStop.source === 'fidelity_manual' ? 'operator-recorded manual stop (Fidelity — not API-verified)' : 'live stop at broker'}{effectiveBrokerStop.fetched_at ? ` · read ${formatReviewStamp(effectiveBrokerStop.fetched_at)}` : ''}</span>
        <span style={{ ...numStyle, fontSize: 10.5, color: WL.text.secondary }}>SELL {effectiveBrokerStop.qty ?? p.shares} {p.symbol} {String(effectiveBrokerStop.order_type || '').replace('_', ' ')} {effectiveBrokerStop.stop_price != null ? `$${Number(effectiveBrokerStop.stop_price).toFixed(2)}` : effectiveBrokerStop.trail_offset != null ? (effectiveBrokerStop.trail_link === 'PERCENT' ? `${effectiveBrokerStop.trail_offset}%` : `$${effectiveBrokerStop.trail_offset}`) : ''} GTC</span>
        <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: 'rgba(45,212,191,.14)', color: TEAL }}>{String(effectiveBrokerStop.status || 'working')}</span>
        <span style={{ fontSize: 9, color: WL.text.dim }}>#{effectiveBrokerStop.order_id}</span>
        <span style={{ flex: 1 }} />
        {cancelMsg && <span style={{ fontSize: 9.5, color: cancelMsg.startsWith('✅') ? TEAL : cancelMsg.startsWith('⛔') ? WL.signal.red : WL.text.dim }}>{cancelMsg}</span>}
        <button onClick={_openModify} disabled={cancelBusy} title="Cancel this stop + place a new one at the current advised level — one 2FA. Use after the price moves up." style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${WL.signal.amber}`, background: 'transparent', color: WL.signal.amber, cursor: cancelBusy ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>Modify</button>
        <button onClick={_cancelStop} disabled={cancelBusy} title="Cancel this live protective stop at the broker (safe direction; no 2FA)" style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${WL.signal.red}`, background: 'transparent', color: WL.signal.red, cursor: cancelBusy ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{cancelBusy ? '…' : 'Cancel stop'}</button>
      </div>}
      {/* COVERAGE MISMATCH — a standalone GTC stop does NOT auto-resize when you trim/add. Warn so the
          operator cancels + re-places sized to the shares held now. */}
      {effectiveBrokerStop && effectiveBrokerStop.coverage === 'oversized' && <div style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '6px 9px', borderRadius: 7, background: 'rgba(239,83,80,.08)', border: '1px solid rgba(239,83,80,.35)', fontSize: 10, fontWeight: 800, color: WL.signal.red }}>
        ⚠ OVERSIZED — stop covers {effectiveBrokerStop.qty} sh but you hold {effectiveBrokerStop.held_qty}. On trigger it may short the extra {Number(effectiveBrokerStop.qty) - Number(effectiveBrokerStop.held_qty)} (margin) or reject (cash). Cancel & re-place at {effectiveBrokerStop.held_qty} sh.
      </div>}
      {effectiveBrokerStop && effectiveBrokerStop.coverage === 'partial' && <div style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '6px 9px', borderRadius: 7, background: 'rgba(245,166,35,.08)', border: '1px solid rgba(245,166,35,.35)', fontSize: 10, fontWeight: 800, color: WL.signal.amber }}>
        ⚠ PARTIAL — stop covers only {effectiveBrokerStop.qty} of {effectiveBrokerStop.held_qty} sh held. {Number(effectiveBrokerStop.held_qty) - Number(effectiveBrokerStop.qty)} sh are unprotected. Re-place at {effectiveBrokerStop.held_qty} sh for full cover.
      </div>}
      {effectiveProtectionRec && (() => {
        const price = Number(effectiveProtectionRec.price) || null, stop = Number(effectiveProtectionRec.stop_price) || null, dist = effectiveProtectionRec.stop_distance_pct
        const off = effectiveProtectionRec.trail_recommended ? Number(effectiveProtectionRec.trail_offset) : null, isPct = effectiveProtectionRec.trail_type === 'PERCENT'
        const trailDollar = off == null ? null : isPct ? (price ? price * off / 100 : null) : off
        const trailPct = off == null ? null : isPct ? off : (price ? off / price * 100 : null)
        const distColor = dist == null ? WL.text.dim : dist < 0 ? WL.signal.red : dist < 2 ? WL.signal.red : dist < 5 ? WL.signal.amber : TEAL
        const unprotected = p.protection_state !== 'protected'
        const mf = (p as any).is_unstoppable_fund ?? (p as any).is_mutual_fund   // fund (mutual/401k): no exchange stop possible
        const income = (p as any).holding_family === 'income'  // held for yield — protective stop optional
        const lockBtn = { fontSize: 9.5, fontWeight: 800, padding: '4px 9px', borderRadius: 6, border: '1px dashed #64748b', background: 'rgba(100,116,139,.12)', color: MUTED, cursor: 'not-allowed', whiteSpace: 'nowrap' as const }
        const STAGE2C_TIP = 'Protective stops on real holdings (Stage 2c). Schwab taxable submits LIVE via API after per-order 2FA (type the ticker OR a code sent to Telegram + email — either confirms); the pilot must be ARMED. Accounts with no API (IRAs / Fidelity-401k) return an exact thinkorswim ticket to place manually. POC envelope is committed (DRS, taxable, sub-$1k) until the proof passes.'
        return <>
          <div title={`${_stopReviewTip}\n\n${effectiveProtectionRec.rationale ?? ''} · confidence ${effectiveProtectionRec.confidence ?? '—'}`} style={{ display: 'flex', gap: 9, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <span style={{ fontSize: 11.5, fontWeight: 800, color: WL.text.primary }}>Protection advisory</span>
            <CloudLlmRunButtons
              processId="holding_protection_advisor"
              symbol={_sym}
              lanePolicy="grok_only"
              compact
              onDone={(r) => { if (r?.protection) setAdvisoryOverride(r.protection) }}
            />
            {effectiveProtectionRec.family && <span style={{ fontSize: 9.5, fontWeight: 700, color: WL.text.dim, border: `1px solid ${WL.surface.edge}`, borderRadius: 4, padding: '1px 6px' }}>{effectiveProtectionRec.family}</span>}
            {stop != null && <span style={{ fontSize: 11, fontWeight: 700, color: WL.text.secondary }}>{mf ? 'ref level' : 'stop'} <b style={{ ...numStyle, color: WL.text.primary }}>${stop.toFixed(2)}</b></span>}
            {off != null ? <span style={{ fontSize: 11, fontWeight: 700, color: WL.text.secondary }}>trail <b style={{ ...numStyle, color: WL.text.primary }}>{trailDollar != null ? `$${trailDollar.toFixed(2)}` : '—'}</b>{trailPct != null && <span style={{ color: WL.text.dim, fontWeight: 500 }}> ({trailPct.toFixed(1)}%)</span>}</span> : <span style={{ fontSize: 10, color: WL.text.dim }}>no trail yet</span>}
            {dist != null && <span style={{ fontSize: 10, fontWeight: 800, color: distColor }}>{dist < 0 ? 'price BELOW stop' : `price ${dist.toFixed(1)}% above stop`}</span>}
          </div>
          {stop != null && unprotected && mf && (
            // Fund holding (mutual fund or 401k/proxy code): an exchange stop order cannot be placed
            // (transacts at NAV / inside the plan). Show the level as REFERENCE only — no order buttons.
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: 'rgba(148,163,184,.06)', border: '1px solid rgba(148,163,184,.18)' }}>
              <span style={{ fontSize: 10.5, fontWeight: 800, color: WL.text.muted }}>▸ Fund holding — no exchange stop can be placed (trades at NAV / inside the plan). Protect via tax-aware <b style={{ color: WL.text.secondary }}>trim / rebalance</b>; ${stop.toFixed(2)} is a reference level only.</span>
            </div>
          )}
          {stop != null && unprotected && !mf && (() => {
            const trailRes = resolvedTrailPct(effectiveProtectionRec)
            const effectiveTrailPct = trailRes?.pct ?? ((off != null && trailPct != null) ? trailPct : null)
            const trailReady = effectiveTrailPct != null && stop != null
            const stopTip = `Queue a FIXED sell stop (stop-market) GTC at $${stop.toFixed(2)}. If the price falls to $${stop.toFixed(2)} a MARKET sell fires — it ALWAYS fills, but the fill can slip below $${stop.toFixed(2)} in a fast drop. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const limitTip = `Queue a FIXED sell stop-limit GTC triggering at $${stop.toFixed(2)}. If the price hits $${stop.toFixed(2)} a LIMIT sell (~$${stop.toFixed(2)}) fires — it avoids a bad fill, but may NOT fill if the price gaps straight through, leaving you unprotected on the way down. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const trailTip = trailReady ? `Queue a native TRAILING sell stop GTC, trailing ${effectiveTrailPct!.toFixed(0)}%${trailDollar != null ? ` (≈$${trailDollar.toFixed(2)})` : ''}. The stop starts near $${stop.toFixed(2)} and RATCHETS UP as the price rises (never down), locking in profit; if the price then falls ${effectiveTrailPct!.toFixed(0)}% from its high a MARKET sell fires.${off == null ? ' (optional trail — advisor recommended fixed only)' : ''}\n\n${STAGE2C_TIP}` : ''
            const actBtn = { ...lockBtn, cursor: 'pointer', border: '1px solid #64748b', color: WL.text.secondary }
            const recBtn = { ...lockBtn, cursor: 'pointer', border: `1px solid ${WL.signal.amber}`, background: 'rgba(245,166,35,.12)', color: WL.signal.amber }
            // Income holdings are held for yield — frame the level as OPTIONAL, not "ADVISED".
            const headColor = income ? WL.text.secondary : WL.signal.amber
            const orderTxt = trailReady ? `SELL TRAILING STOP, trail ${effectiveTrailPct!.toFixed(0)}% (starts ~$${stop.toFixed(2)})` : `SELL STOP $${stop.toFixed(2)}`
            const head = income ? `▸ OPTIONAL stop (income hold): ${orderTxt} GTC` : `▸ ADVISED: ${orderTxt} GTC`
            const qty = p.shares
            const open = (kind: string, label: string) => () => { _resetStop(); setStopOrder({ kind, qty, stop, trailPct: kind === 'TRAILING' ? effectiveTrailPct : null, income, label, advised: stop, cur: price ?? (Number(p.current_price) || null) }) }
            return <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: income ? 'rgba(148,163,184,.05)' : 'rgba(245,166,35,.06)', border: `1px solid ${income ? 'rgba(148,163,184,.18)' : 'rgba(245,166,35,.28)'}`, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10.5, fontWeight: 800, color: headColor }}>{head}</span>
              <span style={{ flex: 1 }} />
              <button onClick={open('STOP', `SELL ${qty} ${p.symbol} STOP $${stop.toFixed(2)} GTC`)} title={stopTip} style={trailReady ? actBtn : recBtn}>Queue stop (fixed){trailReady ? '' : ' ★'}</button>
              <button onClick={open('STOP_LIMIT', `SELL ${qty} ${p.symbol} STOP-LIMIT $${stop.toFixed(2)} GTC`)} title={limitTip} style={actBtn}>Queue stop-limit (fixed)</button>
              {trailReady && <button onClick={open('TRAILING', `SELL ${qty} ${p.symbol} TRAILING STOP ${effectiveTrailPct!.toFixed(0)}% GTC`)} title={trailTip} style={recBtn}>Queue trailing stop ★</button>}
              <button onClick={_snoozeStop} disabled={snoozeBusy} title="Acknowledge this stop and grant a 1-week grace period — suppresses the stop ALERT for 7 days. Advisory only: does NOT change or cancel the protective stop at the broker." style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 11px', borderRadius: 6, border: `1px solid ${WL.surface.edge}`, background: 'transparent', color: WL.text.dim, cursor: snoozeBusy ? 'not-allowed' : 'pointer' }}>{snoozeBusy ? '…' : '⏸ Ignore 1 week'}</button>
            </div>
          })()}
          {/* FRACTIONAL position: a broker STOP covers only whole shares (Schwab rejects fractional stops). Offer a
              synthetic stop that protects the FULL position via a monitored Market-Day sell-all on breach. */}
          {_isFractional && stop != null && unprotected && !mf && (
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: 'rgba(148,163,184,.05)', border: '1px solid rgba(148,163,184,.20)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, fontWeight: 800, color: WL.text.secondary }}>▸ Fractional ({_shares} sh) — broker stop covers only {Math.floor(_shares)} whole share{Math.floor(_shares) === 1 ? '' : 's'}. Synthetic stop or market sell-all covers all {_shares}.</span>
                <span style={{ flex: 1 }} />
                {_needsSellAll && (
                  <button onClick={_openSellAll} disabled={stopBusy || _needsReauth || stopDone} title={_needsReauth ? 'Schwab re-auth required' : `Market sell ALL ${_shares} sh · ${_sellAllTif} · per-order 2FA before live submit`}
                    style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 11px', borderRadius: 6, border: `1px solid ${WL.signal.red}`, background: 'transparent', color: WL.signal.red, cursor: (stopBusy || _needsReauth) ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
                    {stopDone ? '✓ Submitted' : `Sell all @ MKT ${_sellAllTif}`}
                  </button>
                )}
                <button onClick={() => _armSynthetic(stop)} disabled={synthBusy} title={`Arm a synthetic stop at $${stop.toFixed(2)} on the FULL ${_shares} sh. The monitor watches the price; on a breach it requests a Market-Day sell-all 2FA (Schwab accepts market sells of fractional qty). Nothing is placed at the broker now.`} style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 11px', borderRadius: 6, border: `1px solid ${WL.signal.amber}`, background: 'transparent', color: WL.signal.amber, cursor: synthBusy ? 'not-allowed' : 'pointer' }}>{synthBusy ? '…' : `Arm synthetic stop @ $${stop.toFixed(2)}`}</button>
              </div>
              {_isFractional && <div style={{ fontSize: 9.5, color: WL.text.dim, marginTop: 5, lineHeight: 1.4 }}>Schwab fractional market orders use DAY (not GTC). Use Sell all @ MKT for immediate exit; use synthetic stop for monitored protection.</div>}
            </div>
          )}
          {synthMsg && <div style={{ fontSize: 10.5, color: synthMsg.startsWith('✓') ? TEAL : WL.signal.red, marginTop: 5 }}>{synthMsg}</div>}
          {snoozeMsg && <div style={{ fontSize: 10.5, color: snoozeMsg.startsWith('✓') ? TEAL : WL.signal.amber, marginTop: 5 }}>{snoozeMsg}</div>}
        </>
      })()}
      {effectiveProtectionRec?.rationale && <div style={{ fontSize: 10.5, color: WL.text.secondary, marginTop: 6, lineHeight: 1.45 }}>{effectiveProtectionRec.rationale}</div>}
      <div style={{ display: 'flex', gap: 5, marginTop: 7, alignItems: 'center', flexWrap: 'wrap' }}><span style={{ fontSize: 9, color: WL.text.dim }}>reviewed by:</span>{Object.keys(lanes).length === 0 && <span style={{ fontSize: 9, color: WL.text.dim }}>no LLM review in 30d</span>}{Object.entries(lanes).map(([lane, c]: any) => { const m = LANE_META[lane]; return <span key={lane} title={`${c.model} · analyzed ${String(c.last_at).slice(0, 10)} · ${c.n} review${c.n > 1 ? 's' : ''}`} style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: m.c + '18', color: m.c, border: `1px solid ${m.c}44` }}>{m.label}</span> })}</div>
    </div>}

    {/* ⑤ Scale position (v3 flow, calm container) */}
    <ScaleControl p={p} terminalUi={terminalUi} />

    {/* ⑥ Context — company, technicals, analysts, earnings, flags, strategy rationale */}
    <div onClick={e => e.stopPropagation()} style={{ ...modRow(terminalUi), cursor: 'default' }}>
      <div style={modLabel(terminalUi)}><span>Context</span></div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {symCard?.description && (
          <div style={ctxLine(terminalUi)} title={symCard.description}>
            <span style={ctxKey(terminalUi)}>Company </span>
            {symCard.description}
            {symCard.vs_sector_week != null && (
              <span style={{ marginLeft: 6, fontWeight: 800, color: symCard.vs_sector_week >= 0 ? TEAL : WL.signal.red }}>
                {symCard.vs_sector_week >= 0 ? '+' : ''}{symCard.vs_sector_week}% vs sector
              </span>
            )}
          </div>
        )}
        <div style={ctxLine(terminalUi)}>
          <span style={ctxKey(terminalUi)}>Technicals </span>
          RSI {t.rsi != null ? num(t.rsi, 0) : '—'}{t.rsi_bucket ? ` ${t.rsi_bucket}` : ''}
          {t.trend_label && <span style={{ color: t.trend_label === 'bullish' ? TEAL : t.trend_label === 'bearish' ? WL.signal.red : WL.text.secondary }}> · {t.trend_label}</span>}
          {sr.sector && (
            <span style={{ color: vs5Color }}> · {sr.sector}{sr.sector_etf ? ` (${sr.sector_etf})` : ''}{vs5 != null ? ` ${pct(vs5)} vs sector (5d)` : ''}</span>
          )}
        </div>
        {p.analyst && (p.analyst.rating || p.analyst.target_mean != null) && (
          <div style={ctxLine(terminalUi)}>
            <span style={ctxKey(terminalUi)}>Analysts </span>
            {p.analyst.rating ? `${String(p.analyst.rating).toUpperCase()}${p.analyst.rating_mean != null ? ` (${Number(p.analyst.rating_mean).toFixed(1)})` : ''}` : 'no consensus'}
            {p.analyst.opinions != null && ` · ${p.analyst.opinions} opinions`}
            {p.analyst.target_mean != null && ` · target $${num(p.analyst.target_mean, 2)}`}
            {p.analyst.target_upside_pct != null && <span style={{ color: p.analyst.target_upside_pct > 0 ? TEAL : WL.signal.red, fontWeight: 800 }}> ({p.analyst.target_upside_pct > 0 ? '+' : ''}{num(p.analyst.target_upside_pct, 1)}% to target)</span>}
          </div>
        )}
        {p.earnings_date && (
          <div style={{ ...ctxLine(terminalUi), color: earnSoon ? WL.signal.amber : WL.text.secondary, fontWeight: earnSoon ? 700 : 400 }}>
            <span style={ctxKey(terminalUi)}>Earnings </span>
            {String(p.earnings_date).slice(0, 10)}{earnDays != null && Number.isFinite(earnDays) && earnDays >= 0 ? ` (${earnDays}d)` : ''}
          </div>
        )}
        {riskFlags.length > 0 && (
          <div style={{ ...ctxLine(terminalUi), color: WL.signal.red }}>
            <span style={ctxKey(terminalUi)}>Risk </span>
            {riskFlags.map(r => r.replace(/_/g, ' ')).join(' · ')}
          </div>
        )}
        {oppFlags.length > 0 && (
          <div style={{ ...ctxLine(terminalUi), color: TEAL }}>
            <span style={ctxKey(terminalUi)}>Opportunity </span>
            {oppFlags.map(o => o.replace(/_/g, ' ')).join(' · ')}
          </div>
        )}
        {p.strategy_rationale && (
          <div style={{ ...ctxLine(terminalUi), color: WL.text.muted, fontStyle: 'italic' }}>
            <span style={{ ...ctxKey(terminalUi), fontStyle: 'normal' }}>Why {p.strategy ?? 'strategy'} </span>
            {p.strategy_rationale}
          </div>
        )}
      </div>
    </div>

    {/* ⑦ News & catalysts — expander, as today */}
    <div onClick={e => e.stopPropagation()} style={{ ...modRow(terminalUi), cursor: 'default' }}>
      <div style={{ ...modLabel(terminalUi), marginBottom: expanded ? (terminalUi ? 4 : 7) : 0 }}>
        <span>News & catalysts</span>
        <Expander open={!!expanded} onToggle={onToggle} label={expanded ? 'less' : 'more'} />
      </div>
      {expanded && <>
        {news.length === 0 && <div style={{ fontSize: 10.5, color: WL.text.dim }}>No recent research surfaced.</div>}
        {news.map((n: any, i: number) => {
          const stale = (n.age_hours ?? 0) > 48
          return <div key={i} style={{ fontSize: 11, marginBottom: 7, opacity: stale ? 0.75 : 1, lineHeight: 1.45 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={chip('rgba(148,163,184,.08)', WL.text.secondary)}>{n.source}</span>
              {n.age_hours != null && <span style={{ fontSize: 9.5, color: stale ? WL.signal.amber : WL.text.dim }}>{Math.round(n.age_hours)}h{stale ? ' stale' : ''}</span>}
            </div>
            {n.url
              ? <a href={n.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="wlc4-link" style={{ display: 'inline-block', marginTop: 3, fontWeight: 650 }}>{n.title || ''}</a>
              : <div style={{ color: WL.text.secondary, marginTop: 3 }}>{n.title || ''}</div>}
            {n.why_it_matters && <div style={{ fontSize: 10.5, color: WL.text.muted, marginTop: 3 }}><b style={{ color: WL.text.secondary }}>Why it matters:</b> {n.why_it_matters}</div>}
          </div>
        })}
        <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 6 }}>
          SMA50 {t.sma50_pct != null ? pct(t.sma50_pct) : '—'} · SMA200 {t.sma200_pct != null ? pct(t.sma200_pct) : '—'} · RVOL {t.rvol ?? '—'}{sr.sector ? ` · ${sr.sector} ${sr.label}` : ''}{p.last_hermes_review_at ? ` · Hermes ${String(p.last_hermes_review_at).slice(0, 10)}` : ''}
        </div>
      </>}
    </div>
  </div>
}

// Mid-trade scale-IN / scale-OUT control (operator 2026-06-19) — flow identical to v3; container
// restyled to the v4 module rhythm. Both directions require a preview→confirm step. Broker-routed
// by the API: alpaca_paper = live paper, schwab_* = gated 2FA, fidelity_* = record-only. Scale-in
// is capped server-side at the percent-of-equity position headroom.
function ScaleControl({ p, terminalUi }: { p: any; terminalUi: boolean }) {
  const [qty, setQty] = useState('')
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const held = Number(p.shares) || 0
  const acct = String(p.account ?? '').toLowerCase()
  const broker = acct.includes('alpaca') ? 'alpaca' : acct.startsWith('schwab') ? 'schwab' : acct.startsWith('fidelity') ? 'fidelity' : 'unknown'
  if (held <= 0 || broker === 'unknown') return null
  const brokerNote = broker === 'alpaca' ? 'live paper order' : broker === 'schwab' ? 'Schwab — gated 2FA (no live order yet)' : 'Fidelity — record-only (execute at broker)'

  const send = async (sign: number, confirm: boolean) => {
    const n = Math.abs(parseInt(qty || '0', 10))
    if (!n) { setMsg('enter a share count'); return }
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/paper-trades/scale', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: p.account, symbol: p.symbol, delta_shares: sign * n, confirm })
      }).then(x => x.json())
      const d = r.data ?? r
      if (!confirm) {
        if (d.ok || d.preview || d.gated) setPreview({ ...d, sign, n })
        else { setMsg(d.error || 'preview failed'); setPreview(null) }
      } else {
        if (d.ok) setMsg(`✅ ${d.direction === 'scale_in' ? 'Added' : 'Trimmed'} ${d.applied ?? d.delta} ${p.symbol}${d.new_shares != null ? ` → ${d.new_shares} sh` : ''}${d.realized_pnl != null ? ` · P&L $${d.realized_pnl}` : ''}${d.stop ? ` · ${d.stop}` : ''}`)
        else if (d.gated) setMsg(`🔒 ${d.detail}`)
        else if (d.recorded) setMsg(`📝 ${d.detail}`)
        else setMsg(d.error || 'failed')
        setPreview(null); setQty('')
      }
    } catch (e: any) { setMsg(String(e).slice(0, 90)) } finally { setBusy(false) }
  }

  const inp = { width: 64, fontSize: 11, padding: '4px 7px', borderRadius: 6, border: `1px solid ${WL.surface.edge}`, background: WL.surface.inset, color: WL.text.primary }
  const btn = (c: string) => ({ fontSize: 10.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${c}`, background: 'transparent', color: c, cursor: busy ? 'not-allowed' as const : 'pointer' as const, whiteSpace: 'nowrap' as const })
  return <div onClick={e => e.stopPropagation()} style={{ ...modRow(terminalUi), cursor: 'default' }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: terminalUi ? 8 : 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: terminalUi ? BB.text3 : WL.text.dim }}>Scale position</span>
      <span style={{ fontSize: 9.5, color: WL.text.dim }}>held {held} sh · {brokerNote}</span>
      <span style={{ flex: 1 }} />
      <input style={inp} value={qty} onChange={e => setQty(e.target.value.replace(/[^0-9]/g, ''))} placeholder="shares" disabled={busy} />
      <button onClick={() => send(1, false)} disabled={busy} title="Add shares (capped at position headroom)" style={btn(TEAL)}>Scale in +</button>
      <button onClick={() => send(-1, false)} disabled={busy} title="Trim shares (partial close)" style={btn(WL.signal.amber)}>Scale out −</button>
    </div>
    {preview && <div style={{ marginTop: 9, padding: '8px 10px', borderRadius: 8, background: WL.surface.inset, border: `1px solid ${WL.surface.edge}` }}>
      <div style={{ fontSize: 11, color: WL.text.primary, fontWeight: 700 }}>
        Confirm {preview.direction === 'scale_in' ? 'scale-IN' : 'scale-OUT'}: {preview.side?.toUpperCase()} {preview.delta_applied ?? preview.delta ?? preview.n} {p.symbol}
        {preview.price ? ` @ ~$${Number(preview.price).toFixed(2)}` : ''}{preview.new_shares != null ? ` → ${preview.new_shares} sh` : ''}
      </div>
      {preview.cap_note && <div style={{ fontSize: 10, color: WL.signal.amber, marginTop: 3 }}>⚠ {preview.cap_note}</div>}
      {preview.detail && <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 3 }}>{preview.detail}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={() => send(preview.sign, true)} disabled={busy} style={btn(preview.gated ? WL.signal.amber : TEAL)}>{busy ? '…' : preview.gated ? 'Confirm (gated)' : 'Confirm'}</button>
        <button onClick={() => setPreview(null)} disabled={busy} style={btn(WL.text.dim)}>Cancel</button>
      </div>
    </div>}
    {msg && <div style={{ fontSize: 10.5, marginTop: 7, color: msg.startsWith('✅') ? TEAL : msg.startsWith('🔒') || msg.startsWith('📝') ? WL.text.secondary : WL.signal.amber }}>{msg}</div>}
  </div>
}
