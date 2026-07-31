import { useState } from 'react'
import CountryFlag from './CountryFlag'
import HoldingReportLinks from './HoldingReportLinks'
import { StopKindPill } from './StopKindPill'
import { fmt$ } from '../lib/format'
import {
  accountBrand,
  buildHoldingsRowModel,
  type RsiZone,
  type VolTier,
} from '../lib/holdingsRowModel'
import { resolveCountry } from '../lib/country'
import {
  BB, type HoldingsCvdMode, primaryActionBg, primaryActionColor,
  semanticSigned, semanticUp, stopStatusBg, stopStatusColor,
} from '../lib/holdingsTerminalTokens'
import { holdingReportEligible } from '../lib/reportLinks'
import { ShareDriftPill } from './ShareReconciliationModal'
import { LevelLines, type LevelMap } from '../lib/supportResistance'

const LLM_LANE: Record<string, { label: string; c: string }> = {
  local: { label: 'G', c: '#2dd4bf' },
  grok: { label: 'G', c: '#f59e0b' },
  chatgpt: { label: 'GPT', c: '#a3e635' },
  claude: { label: 'C', c: '#d97757' },
}

const COL_TIPS: Record<string, string> = {
  symbol: 'Ticker and short security name',
  acct: 'Full brokerage account (color pill = brand)',
  value: 'Market value and today % change',
  pl: 'Unrealized P&L $ and % vs cost basis',
  wt: 'Portfolio weight across all accounts',
  px: 'Last price / average cost per share',
  rsi: 'RSI — oversold green, overbought red, neutral muted',
  vol: 'Volatility tier from stop advisory (LOW / MED / HIGH)',
  news: 'Latest headline — hover for full text; click opens source',
  earn: 'Next earnings date when known',
  stop: 'Stop status and recommended action',
  action: 'Open stop management (2FA / ticket) for this lot',
  reports: 'Analyst PDF / Word',
  agents: 'LLM research lanes (30d)',
}

/** Operator tooltip for vol tier band. */
export function volTierTooltip(pr: any, live?: { stop?: number | null; price?: number | null; distancePct?: number | null }): string {
  const tier = String(pr?.volatility_tier || '').toUpperCase()
  const fb = pr?.family_bounds || {}
  const stop = live?.stop
  let distance = live?.distancePct
  if (distance == null && stop != null && live?.price) distance = (live.price - stop) / live.price * 100
  const cur = stop != null
    ? `Current live stop: $${Number(stop).toFixed(2)}${distance != null ? ` (${distance.toFixed(1)}% below)` : ''}`
    : 'Current live stop: none'
  const regime = pr?.regime ? String(pr.regime).replace(/_/g, '-') : null
  const adj = pr?.regime_adjustment_pct
  const regimeBit = regime
    ? ` + ${regime} regime${adj != null ? `, ${adj > 0 ? '+' : ''}${adj}% cap` : ''}`
    : ''
  const tMin = fb.trail_min_pct != null ? Number(fb.trail_min_pct) : null
  const tMax = fb.trail_max_pct != null ? Number(fb.trail_max_pct) : null
  let advise: string
  if (tMin != null && tMax != null) {
    const range = `${tMin}\u2013${tMax}%`
    const verb = stop == null ? 'Set'
      : distance != null && distance < tMin ? 'Widen to'
      : distance != null && distance > tMax ? 'Tighten to' : null
    advise = verb
      ? `Advisory: ${verb} ${range} trailing (based on ${tier} tier${regimeBit}).`
      : `Advisory: ${range} trailing \u2014 within band (${tier} tier${regimeBit}).`
  } else {
    advise = `Advisory: ${tier || '—'} tier${regimeBit}.`
  }
  const floor = fb.stop_min_pct != null
    ? `Minimum floor: ${fb.stop_min_pct}% (family/swing-low still governs).`
    : 'Family/swing-low rule still governs final placement.'
  return `${cur}\n${advise}\n${floor}`
}

export interface HoldingsTableRowContext {
  h: any
  pr?: any
  monitored?: any
  confirmedStop?: any
  brokerStopReadOk?: string[]
  reportEntry?: any
  coverage?: any[]
  fv?: any
  card?: any
}

interface Props {
  rows: HoldingsTableRowContext[]
  /** symbol → closed-session support/resistance from portfolio.reentry.resistance.v1 */
  resistanceMap?: LevelMap
  acctColor: (a: string) => string
  focusKey?: string | null
  cvdMode?: HoldingsCvdMode
  /** Full ticker drawer (Overview tab) — row click except action cells */
  onOpenDetail: (ctx: HoldingsTableRowContext) => void
  /** Stop Management drawer tab — symbol / stop column / action button */
  onOpenStops: (ctx: HoldingsTableRowContext) => void
  /** @deprecated use onOpenStops — kept as alias for action buttons */
  onPrimaryAction?: (ctx: HoldingsTableRowContext) => void
  /** Open share-reconciliation modal for this holding (when drift pending) */
  onShareDrift?: (ctx: HoldingsTableRowContext) => void
}

/**
 * Column template — scannable Bloomberg grid.
 * Two-line cells where needed (value/today, P&L $/%, price/cost, news/earn).
 */
const GRID = [
  '22px',           // expand
  'minmax(100px, 1.1fr)', // symbol + name
  'minmax(132px, 1.15fr)', // account full + pill
  '88px',           // value · today
  '86px',           // P&L
  '48px',           // wt
  '72px',           // px / cost
  '52px',           // RSI
  '56px',           // VOL
  'minmax(90px, 1.2fr)', // news
  '72px',           // earn
  'minmax(110px, 1.15fr)', // stop
  '108px',          // action
  '56px',           // reports
  '48px',           // agents
].join(' ')

function HeaderCell({ label, tip }: { label: string; tip: string }) {
  return (
    <span title={tip} style={{ cursor: 'help', userSelect: 'none' }}>{label}</span>
  )
}

function AgentBadges({ cov }: { cov?: any[] }) {
  if (!cov?.length) {
    return <span title="No LLM research in last 30 days" style={{ color: BB.text3, fontSize: 9 }}>—</span>
  }
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 2, flexWrap: 'wrap' }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return (
          <span
            key={lane}
            title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review(s)`}
            style={{
              fontSize: 8, fontWeight: 800, padding: '1px 4px', borderRadius: 3,
              background: `${m.c}22`, color: m.c, border: `1px solid ${m.c}44`, cursor: 'help',
            }}
          >
            {m.label}
          </span>
        )
      })}
    </span>
  )
}

function rsiColor(zone: RsiZone, cvd: HoldingsCvdMode): string {
  if (zone === 'oversold') return semanticUp(cvd)
  if (zone === 'overbought') return BB.red
  return BB.text2
}

function volMeta(tier: VolTier): { label: string; color: string } | null {
  if (tier === 'low') return { label: 'LOW', color: BB.green }
  if (tier === 'medium') return { label: 'MED', color: BB.amber }
  if (tier === 'high') return { label: 'HIGH', color: BB.red }
  return null
}

function truncate(s: string, n: number): string {
  const t = s.replace(/\s+/g, ' ').trim()
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

function AccountPill({ account, label }: { account: string; label: string }) {
  const brand = accountBrand(account)
  return (
    <span
      title={account}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, maxWidth: '100%',
        padding: '3px 8px 3px 4px', borderRadius: 999,
        background: brand.bg, border: `1px solid ${brand.color}44`,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 18, height: 18, borderRadius: 4, flexShrink: 0,
          background: brand.color, color: '#0a0e1a',
          fontSize: 10, fontWeight: 900, display: 'inline-flex',
          alignItems: 'center', justifyContent: 'center', fontFamily: BB.mono,
        }}
      >
        {brand.letter}
      </span>
      <span style={{
        fontSize: 11, fontWeight: 700, color: BB.text0,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        letterSpacing: 0.1,
      }}>
        {label}
      </span>
    </span>
  )
}

function DualMetric({
  primary, secondary, primaryColor, secondaryColor, tip,
}: {
  primary: string
  secondary?: string | null
  primaryColor?: string
  secondaryColor?: string
  tip?: string
}) {
  return (
    <div title={tip} style={{ lineHeight: 1.35, fontFamily: BB.mono, minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: primaryColor ?? BB.text0 }}>{primary}</div>
      {secondary != null && secondary !== '' && (
        <div style={{ fontSize: 10, fontWeight: 700, color: secondaryColor ?? BB.text3 }}>{secondary}</div>
      )}
    </div>
  )
}

function rowTooltip(m: ReturnType<typeof buildHoldingsRowModel>, h: any): string {
  const ctry = resolveCountry({ symbol: h.symbol, country: h.country, countryName: h.country_name })
  return [
    `${m.symbol}${h.name ? ` · ${h.name}` : ''}`,
    ctry ? `HQ: ${ctry.name}` : '',
    m.accountLabel,
    m.shares != null ? `${m.shares} shares` : '',
    m.pl$ != null
      ? `Unrealized ${m.pl$ >= 0 ? '+' : ''}${fmt$(m.pl$, 0)}${m.plPct != null ? ` (${m.plPct >= 0 ? '+' : ''}${m.plPct.toFixed(1)}%)` : ''}`
      : '',
    m.rsi != null ? `RSI ${m.rsi.toFixed(1)}${m.rsiStatus ? ` (${m.rsiStatus})` : ''}` : '',
    m.volTier ? `Vol tier: ${m.volTier.toUpperCase()}` : '',
    m.earningsDate ? `Next earnings: ${m.earningsDate}` : '',
    m.newsTitle ? `News: ${m.newsTitle}${m.newsSource ? ` · ${m.newsSource}` : ''}` : '',
    m.stopInstruction,
    m.stopContext,
    m.liveStopPrice != null ? `Live stop $${m.liveStopPrice.toFixed(2)}` : '',
    m.plIfFired != null ? `P/L if stop fills: ${m.plIfFired >= 0 ? '+' : ''}${fmt$(m.plIfFired, 0)}` : '',
    m.needsAction ? '⚠ Action needed' : 'No urgent stop action',
    'Click row → drawer · Action → stop management',
  ].filter(Boolean).join('\n')
}

/** Compact ratio: 2dp under 10, 1dp under 100, whole above. Null when not a finite number. */
function fmtRatio(value: unknown): string | null {
  if (value == null || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  const a = Math.abs(n)
  return a >= 100 ? n.toFixed(0) : a >= 10 ? n.toFixed(1) : n.toFixed(2)
}

/**
 * `P/E x · P/B y` sub-line under the ticker. P/E (and fwd P/E, PEG, EPS) come from
 * /api/v2/portfolio/holdings; P/B from the Finviz strip already fetched by the hub.
 * Renders only the fields that exist — ETFs with no earnings show just P/B (or nothing),
 * never a fabricated zero. Advisory fundamentals, mirroring the LevelLines pattern.
 */
function FundLine({ h, fv }: { h: any; fv?: any }) {
  // Synthetic cash must never inherit equity Finviz/fundamentals (CASH ticker contamination).
  const isCash = Boolean(h?.is_cash)
    || String(h?.symbol || '').toUpperCase() === 'CASH'
    || ['cash', 'currency', 'cash_equivalent'].includes(String(h?.asset_type || h?.assetType || '').toLowerCase())
  if (isCash) return null
  const pe = fmtRatio(h?.pe ?? fv?.pe)
  const pb = fmtRatio(fv?.pb ?? h?.pb)
  if (!pe && !pb) return null
  const fwd = fmtRatio(h?.forward_pe ?? fv?.forward_pe)
  const peg = fmtRatio(h?.peg ?? fv?.peg)
  const eps = h?.eps_ttm ?? h?.eps
  const epsStr = eps != null && eps !== '' && Number.isFinite(Number(eps)) ? Number(eps).toFixed(2) : null
  const tip = [
    pe ? `P/E (ttm) ${pe}` : null,
    fwd ? `Fwd P/E ${fwd}` : null,
    peg ? `PEG ${peg}` : null,
    pb ? `P/B ${pb}` : null,
    epsStr ? `EPS ttm ${epsStr}` : null,
  ].filter(Boolean).join(' · ') + '. Source: /api/v2/portfolio/holdings + Finviz strip. Fundamentals, advisory.'
  return (
    <div title={tip} style={{ fontSize: 10, color: BB.text3, whiteSpace: 'nowrap', lineHeight: 1.35 }}>
      {pe && <>P/E <span style={{ color: BB.text2, fontWeight: 700 }}>{pe}</span></>}
      {pe && pb ? ' · ' : ''}
      {pb && <>P/B <span style={{ color: BB.text2, fontWeight: 700 }}>{pb}</span></>}
    </div>
  )
}

/**
 * Bloomberg-style holdings table: tall rows, full account names + brand pills,
 * dual-line money cells, RSI/VOL badges, news + earnings, stop + action.
 */
export default function HoldingsTableView({
  rows, resistanceMap = {}, focusKey, cvdMode = 'default', onOpenDetail, onOpenStops, onPrimaryAction, onShareDrift,
}: Props) {
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const openStops = onOpenStops || onPrimaryAction || onOpenDetail
  const models = rows.map(r => ({
    ctx: r,
    m: buildHoldingsRowModel({
      h: r.h, pr: r.pr, confirmedStop: r.confirmedStop, monitored: r.monitored, brokerStopReadOk: r.brokerStopReadOk, fv: r.fv, card: r.card,
    }),
  }))
  // Placement permission ≠ verification required. Never count UNVERIFIABLE / CASH as place-stop.
  const placementCount = models.filter(x => x.m.needsAction && x.m.protectionState === 'NO_STOP').length
  const resizeCount = models.filter(x => x.m.needsAction && x.m.protectionState === 'PROTECTED').length
  const verificationCount = models.filter(x => x.m.needsVerification || x.m.protectionState === 'UNVERIFIABLE').length
  const actionableCount = placementCount + resizeCount

  return (
    <div
      data-testid="holdings-table"
      style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 8, overflow: 'hidden' }}
    >
      {/* Sticky header */}
      <div
        data-testid="holdings-table-legend"
        role="row"
        style={{
          display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '10px 12px',
          fontSize: 9, fontWeight: 700, color: BB.text3, textTransform: 'uppercase', letterSpacing: 0.4,
          borderBottom: `1px solid ${BB.border}`, background: BB.bgRow,
          position: 'sticky', top: 0, zIndex: 2, alignItems: 'end',
        }}
      >
        <span />
        <HeaderCell label="Symbol" tip={COL_TIPS.symbol} />
        <HeaderCell label="Account" tip={COL_TIPS.acct} />
        <HeaderCell label="Value · Today" tip={COL_TIPS.value} />
        <HeaderCell label="P&L" tip={COL_TIPS.pl} />
        <HeaderCell label="Wt %" tip={COL_TIPS.wt} />
        <HeaderCell label="Px / Cost" tip={COL_TIPS.px} />
        <HeaderCell label="RSI" tip={COL_TIPS.rsi} />
        <HeaderCell label="Vol" tip={COL_TIPS.vol} />
        <HeaderCell label="News" tip={COL_TIPS.news} />
        <HeaderCell label="Earn" tip={COL_TIPS.earn} />
        <HeaderCell label="Stop" tip={COL_TIPS.stop} />
        <HeaderCell label="Action" tip={COL_TIPS.action} />
        <HeaderCell label="Rpt" tip={COL_TIPS.reports} />
        <HeaderCell label="AI" tip={COL_TIPS.agents} />
      </div>

      <div style={{ maxHeight: 'calc(100vh - 300px)', overflowY: 'auto' }}>
        {models.map(({ ctx: rowCtx, m }, i) => {
          const h = rowCtx.h
          const focused = focusKey === m.key.replace(':', '-')
          const hovered = hoverKey === m.key
          const bg = focused ? BB.bgRowFocus : hovered ? BB.bgRowHover : i % 2 ? BB.bgRowAlt : BB.bgRow
          const actionColor = primaryActionColor(m.primaryAction.tone, cvdMode)
          const actionBg = primaryActionBg(m.primaryAction.tone, cvdMode)
          const stopColor = stopStatusColor(m.stopStatus)
          const isAmber = m.primaryAction.tone === 'amber'
          const isRed = m.primaryAction.tone === 'red'
          const rc = rsiColor(m.rsiStatus, cvdMode)
          const vol = volMeta(m.volTier)
          const nameLine = m.name || (h.name ? String(h.name).slice(0, 36) : null)
          const hasShareDrift = h.share_drift_status === 'pending'
            || (h.broker_actual_shares != null && h.shares != null
              && Math.abs(Number(h.broker_actual_shares) - Number(h.shares)) > 0.01)
          const transferNote = h.transfer_display_note
            || h.transfer_history_tag?.display_note
            || (h.normalized_after_transfer ? 'normalized after transfer' : null)

          return (
            <div
              key={m.key}
              id={`hold-${h.symbol}-${h.account}`}
              role="row"
              tabIndex={0}
              title={rowTooltip(m, h)}
              onKeyDown={e => { if (e.key === 'Enter') onOpenDetail(rowCtx) }}
              onMouseEnter={() => setHoverKey(m.key)}
              onMouseLeave={() => setHoverKey(null)}
              onClick={() => onOpenDetail(rowCtx)}
              style={{
                display: 'grid', gridTemplateColumns: GRID, gap: 8, alignItems: 'center',
                padding: '12px 12px', minHeight: BB.rowH, background: bg,
                borderBottom: `1px solid ${BB.borderSubtle}`, cursor: 'pointer',
                borderLeft: m.needsAction
                  ? `3px solid ${isRed ? BB.red : BB.amberAlt}`
                  : focused ? `3px solid ${BB.amber}` : '3px solid transparent',
                outline: focused ? `2px solid ${BB.amber}55` : 'none',
              }}
            >
              {/* Expand */}
              <button
                type="button"
                title="Open drawer"
                onClick={e => { e.stopPropagation(); onOpenDetail(rowCtx) }}
                style={{
                  background: 'transparent', border: 'none', color: BB.text2,
                  cursor: 'pointer', fontSize: 12, padding: 0, lineHeight: 1,
                }}
              >▸</button>

              {/* Symbol + short name — click opens Stop Management drawer */}
              <div
                role="button"
                title="Open Stop Management for this symbol"
                onClick={e => { e.stopPropagation(); openStops(rowCtx) }}
                style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, cursor: 'pointer' }}
              >
                <CountryFlag symbol={h.symbol} country={h.country} countryName={h.country_name} size={16} />
                <div style={{ minWidth: 0, lineHeight: 1.35 }}>
                  <div style={{
                    fontFamily: BB.mono, fontWeight: 800, fontSize: 13.5, color: BB.blue,
                    letterSpacing: 0.2, textDecoration: 'underline', textDecorationColor: `${BB.blue}55`,
                  }}>
                    {m.symbol}
                  </div>
                  {nameLine && (
                    <div style={{
                      fontSize: 9, color: BB.text3, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {nameLine}
                    </div>
                  )}
                  <LevelLines symbol={m.symbol} row={resistanceMap[m.symbol]} />
                  <FundLine h={h} fv={rowCtx.fv} />
                  {hasShareDrift && (
                    <div style={{ marginTop: 3 }} onClick={e => e.stopPropagation()}>
                      <ShareDriftPill compact onClick={() => onShareDrift?.(rowCtx)} />
                    </div>
                  )}
                  {transferNote && (
                    <div
                      title={h.normalization_status || transferNote}
                      style={{
                        marginTop: 3, fontSize: 8, fontWeight: 800, color: '#f59e0b',
                        letterSpacing: 0.2, textTransform: 'uppercase',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 120,
                      }}
                    >
                      {String(transferNote).slice(0, 28)}
                    </div>
                  )}
                </div>
              </div>

              {/* Account — full name + brand pill */}
              <AccountPill account={m.account} label={m.accountLabel} />

              {/* Value · Today */}
              <DualMetric
                tip={[
                  `Market value ${fmt$(m.marketValue, 0)}`,
                  m.dayPct != null ? `Today ${m.dayPct >= 0 ? '+' : ''}${m.dayPct.toFixed(2)}%` : null,
                ].filter(Boolean).join(' · ')}
                primary={fmt$(m.marketValue, 0)}
                secondary={m.dayPct != null ? `${m.dayPct >= 0 ? '+' : ''}${m.dayPct.toFixed(2)}%` : '—'}
                secondaryColor={m.dayPct != null ? semanticSigned(m.dayPct, cvdMode) : BB.text3}
              />

              {/* Unrealized P&L */}
              {m.pl$ != null ? (
                <DualMetric
                  tip={`Unrealized vs cost basis`}
                  primary={`${m.pl$ >= 0 ? '+' : ''}${fmt$(m.pl$, 0)}`}
                  secondary={m.plPct != null ? `${m.plPct >= 0 ? '+' : ''}${m.plPct.toFixed(1)}%` : '—'}
                  primaryColor={semanticSigned(m.pl$, cvdMode)}
                  secondaryColor={m.plPct != null ? semanticSigned(m.plPct, cvdMode) : BB.text3}
                />
              ) : (
                <span style={{ color: BB.text3, fontSize: 11 }}>—</span>
              )}

              {/* Weight */}
              <span
                title={m.portfolioPct != null ? `${m.portfolioPct.toFixed(1)}% of total portfolio` : 'Weight unknown'}
                style={{ fontFamily: BB.mono, fontSize: 11, fontWeight: 700, color: BB.text2 }}
              >
                {m.portfolioPct != null ? `${m.portfolioPct.toFixed(1)}%` : '—'}
              </span>

              {/* Price / Cost */}
              <DualMetric
                tip={[
                  m.price != null ? `Last $${m.price.toFixed(2)}` : null,
                  m.cost != null ? `Avg cost $${m.cost.toFixed(2)}` : null,
                ].filter(Boolean).join(' · ') || 'Price / cost unavailable'}
                primary={m.price != null ? `$${m.price.toFixed(2)}` : '—'}
                secondary={m.cost != null ? `$${m.cost.toFixed(2)}` : '—'}
              />

              {/* RSI */}
              <span
                title={m.rsi != null ? `RSI ${m.rsi.toFixed(1)}${m.rsiStatus ? ` · ${m.rsiStatus}` : ''}` : 'RSI n/a'}
                style={{
                  fontFamily: BB.mono, fontSize: 12, fontWeight: 800, color: rc, cursor: 'help',
                }}
              >
                {m.rsi != null ? Math.round(m.rsi) : '—'}
              </span>

              {/* Vol tier badge */}
              {vol ? (
                <span
                  title={volTierTooltip(rowCtx.pr, {
                    stop: m.liveStopPrice,
                    price: h.current_price ?? h.price,
                  })}
                  style={{
                    justifySelf: 'start',
                    fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4,
                    background: `${vol.color}1a`, border: `1px solid ${vol.color}55`,
                    color: vol.color, letterSpacing: 0.4, cursor: 'help',
                  }}
                >
                  {vol.label}
                </span>
              ) : (
                <span style={{ fontSize: 10, color: BB.text3 }}>—</span>
              )}

              {/* News */}
              <div
                title={m.newsTitle
                  ? [m.newsTitle, m.newsSource, m.newsAt ? String(m.newsAt).slice(0, 16) : null].filter(Boolean).join('\n')
                  : 'No recent headline'}
                onClick={e => {
                  if (!m.newsUrl) return
                  e.stopPropagation()
                  window.open(m.newsUrl, '_blank', 'noopener,noreferrer')
                }}
                style={{
                  fontSize: 10, color: m.newsTitle ? BB.text1 : BB.text3, fontWeight: 500,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  textDecoration: m.newsUrl ? 'underline' : undefined,
                  textDecorationColor: `${BB.blue}55`,
                  cursor: m.newsUrl ? 'pointer' : 'help',
                  minWidth: 0,
                }}
              >
                {m.newsTitle ? truncate(m.newsTitle, 48) : '—'}
              </div>

              {/* Earnings */}
              <span
                title={m.earningsDate ? `Next earnings: ${m.earningsDate}` : 'No earnings date'}
                style={{
                  fontFamily: BB.mono, fontSize: 10, fontWeight: 700,
                  color: m.earningsLabel ? BB.amber : BB.text3, cursor: 'help',
                }}
              >
                {m.earningsLabel || '—'}
              </span>

              {/* Stop — click opens Stop Management drawer (size mismatch → PARTIAL badge + Update size action).
                  CASH rows are non-actionable; UNVERIFIABLE opens for read-only verification only. */}
              <div
                role="button"
                data-testid={m.stopCoverage?.kind === 'partial' || m.stopCoverage?.kind === 'oversized' ? 'holdings-stop-size-badge' : undefined}
                data-protection-state={m.protectionState}
                title={[
                  m.protectionState === 'CASH' ? 'Cash — no protective stop'
                    : m.protectionState === 'UNVERIFIABLE' ? 'Click → verify broker stops (do not place duplicate)'
                    : 'Click → Stop Management drawer (2FA replace when size mismatch)',
                  m.stopTooltip,
                  m.liveStopPrice != null ? `Live $${m.liveStopPrice.toFixed(2)}` : null,
                  m.stopCoverage?.kind === 'partial' || m.stopCoverage?.kind === 'oversized'
                    ? m.stopCoverage.tip : null,
                ].filter(Boolean).join('\n')}
                onClick={e => {
                  e.stopPropagation()
                  if (m.protectionState === 'CASH') return
                  openStops(rowCtx)
                }}
                style={{
                  minWidth: 0, padding: '5px 7px', borderRadius: 4,
                  cursor: m.protectionState === 'CASH' ? 'default' : 'pointer',
                  background: (m.stopCoverage?.kind === 'partial' || m.stopCoverage?.kind === 'oversized')
                    ? (m.stopCoverage.kind === 'oversized' ? 'rgba(239,68,68,.18)' : 'rgba(245,158,11,.18)')
                    : stopStatusBg(m.stopStatus),
                  borderLeft: `2px solid ${(m.stopCoverage?.kind === 'oversized') ? BB.red : (m.stopCoverage?.kind === 'partial') ? BB.amberAlt : stopColor}`,
                  lineHeight: 1.35,
                }}
              >
                <div style={{ fontSize: 9, fontWeight: 800, color: (m.stopCoverage?.kind === 'partial' || m.stopCoverage?.kind === 'oversized') ? (m.stopCoverage.kind === 'oversized' ? BB.red : BB.amberAlt) : stopColor, textTransform: 'uppercase' }}>
                  {m.stopLabel}
                  {m.liveStopPrice != null && (
                    <span style={{ color: BB.text2, fontWeight: 700, marginLeft: 4, fontFamily: BB.mono }}>
                      ${m.liveStopPrice.toFixed(2)}
                    </span>
                  )}
                </div>
                <div style={{ margin: '2px 0' }}>
                  <StopKindPill kind={m.stopKind} trailPct={m.stopTrailPct} distPct={m.stopLiveDistPct} orderType={m.stopOrderType} small />
                </div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: m.needsAction ? BB.amberAlt : BB.text0,
                  fontFamily: BB.mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {m.stopInstruction}
                </div>
                {m.plIfFired != null && (
                  <div
                    title={`Realized P/L on this position if the current stop fills (${m.liveStopPrice != null ? 'live broker stop' : 'advisory stop'} $${(m.liveStopPrice ?? m.stopPrice)!.toFixed(2)})`}
                    style={{ fontSize: 10, fontWeight: 800, color: semanticSigned(m.plIfFired, cvdMode), fontFamily: BB.mono, whiteSpace: 'nowrap' }}
                  >
                    if fired {m.plIfFired >= 0 ? '+' : ''}{fmt$(m.plIfFired, 0)}
                  </div>
                )}
              </div>

              {/* Action → Stop Management (verify-only when UNVERIFIABLE; disabled for CASH) */}
              <button
                type="button"
                data-testid={`hold-action-${m.symbol}-${m.account}`}
                data-protection-state={m.protectionState}
                title={m.primaryActionTooltip}
                disabled={m.protectionState === 'CASH'}
                onClick={e => {
                  e.stopPropagation()
                  if (m.protectionState === 'CASH') return
                  openStops(rowCtx)
                }}
                style={{
                  width: '100%', padding: '8px 8px', fontSize: 10, fontWeight: 800, borderRadius: 5,
                  cursor: m.protectionState === 'CASH' ? 'default' : 'pointer',
                  border: m.needsVerification
                    ? `2px solid ${BB.amberAlt}`
                    : isAmber ? `2px solid ${BB.amberAlt}` : isRed ? `2px solid ${BB.red}` : `1px solid ${actionColor}55`,
                  background: m.needsVerification
                    ? 'rgba(245,158,11,0.16)'
                    : isAmber ? 'rgba(255,160,40,0.28)' : isRed ? BB.redDim : actionBg,
                  color: m.needsVerification ? BB.amberAlt : isAmber ? BB.amberAlt : actionColor,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  opacity: m.protectionState === 'CASH' ? 0.55 : 1,
                }}
              >
                {m.needsAction || m.needsVerification ? '▸ ' : ''}{m.primaryAction.label}
              </button>

              {/* Reports */}
              <span onClick={e => e.stopPropagation()}>
                {holdingReportEligible(h) ? (
                  <HoldingReportLinks
                    symbol={h.symbol}
                    entry={rowCtx.reportEntry}
                    compact
                    reportType={rowCtx.reportEntry?.report_type}
                  />
                ) : (
                  <span style={{ fontSize: 9, color: BB.text3 }}>—</span>
                )}
              </span>

              {/* Agents */}
              <AgentBadges cov={rowCtx.coverage} />
            </div>
          )
        })}
      </div>

      <div style={{
        fontSize: 9, color: BB.text3, padding: '8px 12px', borderTop: `1px solid ${BB.border}`,
        display: 'flex', gap: 12, flexWrap: 'wrap',
      }}>
        <span data-testid="holdings-row-count">
          {rows.length} positions · row click → full ticker drawer (75%) · symbol/stop/action → Stop Management
        </span>
        {placementCount > 0 && (
          <span data-testid="holdings-placement-count" style={{ color: BB.amberAlt, fontWeight: 700 }}>
            ▸ {placementCount} need stop placement
          </span>
        )}
        {resizeCount > 0 && (
          <span data-testid="holdings-resize-count" style={{ color: BB.amberAlt, fontWeight: 700 }}>
            ▸ {resizeCount} need stop resize
          </span>
        )}
        {verificationCount > 0 && (
          <span data-testid="holdings-verification-count" style={{ color: BB.amberAlt, fontWeight: 700 }}>
            ▸ {verificationCount} verification required
          </span>
        )}
        {actionableCount === 0 && verificationCount === 0 && (
          <span style={{ color: BB.text3 }}>No stop placement backlog</span>
        )}
        <span>Hover for full news / stop detail</span>
      </div>
    </div>
  )
}
