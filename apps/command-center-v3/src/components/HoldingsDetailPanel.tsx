import { useEffect, useMemo, useState } from 'react'
import AnalystReviews, { useAnalystMap } from './AnalystReviews'
import HoldingProtectionActions from './HoldingProtectionActions'
import HoldingReportLinks from './HoldingReportLinks'
import ProAnalystPill, { useProAnalystMap } from './ProAnalystPill'
import { EvidenceBlock } from './EvidenceBlock'
import { laneLabel } from '../lib/laneLabels'
import { fmt$ } from '../lib/format'
import {
  accountBrand,
  accountFullName,
  buildHoldingsRowModel,
  plMetrics,
  resolveRsiZone,
  resolveVolTier,
} from '../lib/holdingsRowModel'
import { BB, type HoldingsCvdMode, semanticSigned, semanticUp } from '../lib/holdingsTerminalTokens'
import { mergeLiveStop, stopReviewTooltip } from '../lib/stopReviewTooltip'
import { holdingReportEligible } from '../lib/reportLinks'
import { volTierTooltip } from './HoldingsTableView'

export type HoldingDrawerTab =
  | 'overview'
  | 'pnl'
  | 'technicals'
  | 'analyst'
  | 'news'
  | 'earnings'
  | 'stops'
  | 'ai'

export interface HoldingsDetailContext {
  h: any
  protection?: any
  stopCuration?: any
  monitored?: any
  confirmedStop?: any
  brokerStopsFetchedAt?: string | null
  brokerStopReadOk?: string[]
  cardMap?: Record<string, any>
  fvMap?: Record<string, any>
  reportEntry?: any
  coverage?: any[]
  onRefreshMonitored?: () => void
  onPreflightUpdate?: (symbol: string, account: string, patch: { holding?: Record<string, unknown>; protection?: Record<string, unknown> }) => void
  cvdMode?: HoldingsCvdMode
  /** Legacy: focus stop management */
  drawerFocus?: 'stops' | null
  /** Preferred: which tab to open */
  initialTab?: HoldingDrawerTab | null
}

const TABS: { id: HoldingDrawerTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'pnl', label: 'P&L' },
  { id: 'technicals', label: 'Technicals' },
  { id: 'analyst', label: 'Analyst & Targets' },
  { id: 'news', label: 'News & Catalysts' },
  { id: 'earnings', label: 'Earnings' },
  { id: 'stops', label: 'Stop Management' },
  { id: 'ai', label: 'AI Insights' },
]

const REC_COLOR: Record<string, string> = {
  strong_buy: '#16a34a', buy: '#22c55e', hold: '#f59e0b', underperform: '#ef4444',
  sell: '#ef4444', strong_sell: '#b91c1c', none: BB.text3,
}

const DIST_TIERS: [string, string, string][] = [
  ['strong_buy', 'Strong Buy', '#16a34a'],
  ['buy', 'Buy', '#22c55e'],
  ['hold', 'Hold', '#f59e0b'],
  ['sell', 'Sell', '#ef4444'],
  ['strong_sell', 'Strong Sell', '#b91c1c'],
]

const rsiZoneColor = (s: string | null | undefined, cvd: HoldingsCvdMode) =>
  s === 'oversold' ? semanticUp(cvd) : s === 'overbought' ? BB.red : BB.text3

const signalColor = (s: string | undefined, cvd: HoldingsCvdMode) => {
  const t = (s || '').toUpperCase()
  if (['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE'].includes(t)) return semanticUp(cvd)
  if (['TRIM', 'SELL', 'REDUCE', 'EXIT'].includes(t)) return BB.red
  if (['MONITOR', 'WATCH', 'CAUTION'].includes(t)) return BB.amber
  return BB.text2
}

function MetricCard({
  label, value, color, tip, sub,
}: { label: string; value: string; color?: string; tip?: string; sub?: string }) {
  return (
    <div
      title={tip}
      style={{
        background: BB.bgRow, border: `1px solid ${BB.border}`, borderRadius: 8,
        padding: '10px 12px', cursor: tip ? 'help' : undefined,
      }}
    >
      <div style={{ fontSize: 9, color: BB.text3, textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color: color ?? BB.text0, marginTop: 4, fontFamily: BB.mono }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: BB.text3, marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{
        fontSize: 11, fontWeight: 800, color: BB.text2, textTransform: 'uppercase',
        letterSpacing: 0.5, marginBottom: 10,
      }}>{title}</div>
      {children}
    </div>
  )
}

function sentimentColor(s: string | null | undefined): string {
  const t = String(s || '').toLowerCase()
  if (/bull|pos|up/.test(t)) return BB.green
  if (/bear|neg|down/.test(t)) return BB.red
  return BB.text3
}

/**
 * Full ticker drawer body — tabbed sections with all available holding data.
 */
export default function HoldingsDetailPanel(ctx: HoldingsDetailContext) {
  const cvdMode = ctx.cvdMode ?? 'default'
  const h = ctx.h
  const symU = String(h.symbol || '').toUpperCase()
  const pr = ctx.protection ?? {}
  const sc = ctx.stopCuration
  const { dollars: pl$, pct: pl } = plMetrics(h)
  const paMap = useProAnalystMap()
  const aMap = useAnalystMap()
  const scard = ctx.cardMap?.[symU]
  const fv = ctx.fvMap?.[symU]
  /** Street consensus (Yahoo / Hermes pro-analyst pills) */
  const pro = paMap[symU] as any
  /** Full rating distribution + target ladder (analyst-detail) */
  const street = aMap[symU] as any
  /** ETF look-through / card-level analyst stub */
  const cardAnalyst = scard?.analyst as any
  const liveConf = mergeLiveStop(ctx.confirmedStop, undefined)
  const stopTip = stopReviewTooltip({
    advisoryAt: pr.at, advisoryModel: pr.model,
    priceAt: h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at,
    brokerFetchedAt: liveConf?.fetched_at ?? ctx.brokerStopsFetchedAt,
    brokerOrderId: liveConf?.order_id,
    confirmedAt: liveConf?.confirmed_at,
  })
  const sh = Number(h.shares) || 0
  const acct = String(h.account ?? '')
  const acctLabel = accountFullName(acct)
  const brand = accountBrand(acct)
  const schwabSmall = acct.startsWith('schwab') && sh > 0 && sh < 40
  const row = buildHoldingsRowModel({
    h, pr, confirmedStop: ctx.confirmedStop, monitored: ctx.monitored, fv, card: scard,
  })

  const defaultTab: HoldingDrawerTab =
    ctx.initialTab
    || (ctx.drawerFocus === 'stops' ? 'stops' : 'overview')

  const [tab, setTab] = useState<HoldingDrawerTab>(defaultTab)

  useEffect(() => {
    setTab(defaultTab)
  }, [defaultTab, symU, acct])

  const rsi = row.rsi
  const rsiZone = row.rsiStatus ?? resolveRsiZone(rsi, h.rsi_status ?? fv?.rsi_status)
  const volTier = row.volTier ?? resolveVolTier(pr?.volatility_tier)

  const newsItems = useMemo(() => {
    const fromCard = Array.isArray(scard?.news) ? scard.news : []
    if (fromCard.length) return fromCard
    if (h.news_title) {
      return [{
        title: h.news_title,
        source: h.news_source,
        at: h.news_at,
        url: h.news_url,
        sentiment: h.news_sentiment,
      }]
    }
    return []
  }, [scard, h])

  const earn = scard?.earnings || null
  const earnNext = row.earningsDate || earn?.next_date || h.next_earnings_date || null
  const catalysts = useMemo(() => {
    const raw = scard?.catalysts ?? scard?.catalyst_list ?? h.catalysts ?? []
    return Array.isArray(raw) ? raw : []
  }, [scard, h])

  const day$ = h.day_change != null
    ? Number(h.day_change)
    : (h.market_value != null && h.day_change_pct != null
      ? Number(h.market_value) * Number(h.day_change_pct) / 100
      : null)

  const stopSection = (
    <div
      data-testid="holding-stop-management"
      id="holding-stop-management"
      style={{
        padding: '14px 16px', borderRadius: 10, display: 'flex', flexDirection: 'column', gap: 12,
        background: tab === 'stops' ? BB.amberDim : BB.bgRow,
        border: `1px solid ${tab === 'stops' ? BB.amber : BB.border}`,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 800, color: tab === 'stops' ? BB.amber : BB.text2, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        Stop management · {symU} · {acctLabel}
      </div>
      <div title={row.stopTooltip} style={{ padding: '12px 14px', background: BB.bg, border: `1px solid ${BB.amber}44`, borderRadius: 8 }}>
        <div style={{ fontSize: 10, color: BB.text3, marginBottom: 4 }}>Recommended action</div>
        <div style={{ fontSize: 15, fontWeight: 800, color: BB.amberAlt, fontFamily: BB.mono }}>{row.stopInstruction}</div>
        {row.stopContext && <div style={{ fontSize: 11, color: BB.text2, marginTop: 6 }}>{row.stopContext}</div>}
        <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap', fontSize: 11 }}>
          {row.liveStopPrice != null && (
            <span title={stopTip} style={{ color: BB.text1 }}>
              Live stop <b style={{ fontFamily: BB.mono, color: BB.green }}>${row.liveStopPrice.toFixed(2)}</b>
            </span>
          )}
          {row.stopPrice != null && (
            <span style={{ color: BB.text1 }}>
              Advisory <b style={{ fontFamily: BB.mono }}>${row.stopPrice.toFixed(2)}</b>
            </span>
          )}
          {volTier && (
            <span
              title={volTierTooltip(pr, { stop: row.liveStopPrice, price: h.current_price ?? h.price })}
              style={{ color: volTier === 'high' ? BB.red : volTier === 'low' ? BB.green : BB.amber, fontWeight: 800 }}
            >
              VOL {volTier.toUpperCase()}
            </span>
          )}
        </div>
      </div>
      {(pr?.stop_price || schwabSmall || liveConf?.order_id) ? (
        <HoldingProtectionActions
          h={h}
          pr={pr}
          monitored={ctx.monitored}
          confirmedStop={ctx.confirmedStop}
          brokerStopsFetchedAt={ctx.brokerStopsFetchedAt}
          brokerStopReadOk={ctx.brokerStopReadOk}
          onRefresh={ctx.onRefreshMonitored}
          onPreflightUpdate={ctx.onPreflightUpdate}
        />
      ) : (
        <div style={{ fontSize: 11, color: BB.text3, lineHeight: 1.5 }}>
          No live broker stop controls for this lot yet. Use the portfolio Stop Management desk for the full book,
          or place a stop once an advisory is available.
        </div>
      )}
      {pr?.evidence?.length > 0 && (
        <EvidenceBlock title={`Stop advisory${pr.model ? ` · ${pr.model}` : ''}`} evidence={pr.evidence} dataIDoubt={pr.data_i_doubt} maxItems={6} />
      )}
      {sc?.evidence?.length > 0 && (() => {
        const claimsLiveStop = (sc.evidence || []).some((e: any) =>
          /live stop/i.test(String(e?.text ?? e ?? '')) && !/no live stop/i.test(String(e?.text ?? e ?? '')))
        const hasLiveStop = ctx.confirmedStop != null || ctx.monitored != null
        const contradicts = claimsLiveStop && !hasLiveStop
        return (
          <div>
            {contradicts && (
              <div style={{
                fontSize: 11, color: BB.amber, fontWeight: 700, padding: '6px 10px', marginBottom: 6,
                borderRadius: 6, background: BB.amberDim, border: `1px solid ${BB.amber}55`,
              }}>
                ⚠ OUTDATED curation mentions a live stop, but broker state shows none — trust live stop above.
              </div>
            )}
            <EvidenceBlock title={`${laneLabel('grok')} stop curation${sc.grade ? ` · ${sc.grade}` : ''}`} evidence={sc.evidence} dataIDoubt={sc.data_i_doubt} maxItems={5} />
          </div>
        )
      })()}
    </div>
  )

  return (
    <div data-testid="holding-ticker-drawer" style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: BB.fontMd, color: BB.text1 }}>
      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 24, fontWeight: 800, fontFamily: BB.mono, color: BB.text0 }}>{h.symbol}</span>
          <ProAnalystPill symbol={h.symbol} map={paMap} />
          {h.signal && (
            <span style={{
              fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 4,
              background: `${signalColor(h.signal, cvdMode)}22`, color: signalColor(h.signal, cvdMode),
            }}>{h.signal}</span>
          )}
          <span
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '3px 10px 3px 5px', borderRadius: 999,
              background: brand.bg, border: `1px solid ${brand.color}44`,
            }}
          >
            <span style={{
              width: 18, height: 18, borderRadius: 4, background: brand.color, color: '#0a0e1a',
              fontSize: 10, fontWeight: 900, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}>{brand.letter}</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: BB.text0 }}>{acctLabel}</span>
          </span>
          {h.name && <span style={{ fontSize: 11, color: BB.text3 }}>{h.name}</span>}
        </div>
        {holdingReportEligible(h) && (
          <HoldingReportLinks symbol={h.symbol} entry={ctx.reportEntry} reportType={ctx.reportEntry?.report_type} />
        )}
      </div>

      {/* Quick metrics always visible — money + Street targets + stop */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(118px, 1fr))', gap: 8 }}>
        <MetricCard label="Market value" value={fmt$(h.market_value, 0)} />
        <MetricCard
          label="Unrealized P/L"
          value={pl$ != null ? `${pl$ >= 0 ? '+' : ''}${fmt$(pl$, 0)}` : '—'}
          color={pl$ != null ? semanticSigned(pl$, cvdMode) : BB.text3}
          sub={pl != null ? `${pl >= 0 ? '+' : ''}${pl.toFixed(2)}%` : undefined}
        />
        <MetricCard
          label="Today"
          value={h.day_change_pct != null ? `${Number(h.day_change_pct) >= 0 ? '+' : ''}${Number(h.day_change_pct).toFixed(2)}%` : '—'}
          color={semanticSigned(Number(h.day_change_pct ?? 0), cvdMode)}
          sub={day$ != null ? `${day$ >= 0 ? '+' : ''}${fmt$(day$, 0)}` : undefined}
        />
        <MetricCard
          label="Weight"
          value={h.portfolio_pct != null ? `${Number(h.portfolio_pct).toFixed(1)}%` : '—'}
          tip="Share of total portfolio across all accounts"
        />
        <MetricCard
          label="Street rating"
          value={streetRatingLabel(street, pro, cardAnalyst)}
          color={streetRatingColor(street, pro)}
          tip="Yahoo / Finnhub consensus · open Analyst & Targets tab for full ladder"
          sub={streetAnalystCount(street, pro)}
        />
        <MetricCard
          label="Mean target"
          value={streetTarget(street, pro)}
          color={streetUpsideColor(street, pro, cvdMode)}
          tip="Mean analyst price target and % upside vs last"
          sub={streetUpsideSub(street, pro)}
        />
        <MetricCard
          label="RSI"
          value={rsi != null ? String(Math.round(rsi)) : '—'}
          color={rsiZoneColor(rsiZone, cvdMode)}
          sub={rsiZone || undefined}
        />
        <MetricCard
          label="Stop"
          value={row.liveStopPrice != null ? `$${row.liveStopPrice.toFixed(2)}` : 'None'}
          color={row.liveStopPrice != null ? BB.green : BB.amber}
          sub={row.stopLabel}
        />
      </div>

      {/* Tabs */}
      <div
        data-testid="holding-drawer-tabs"
        style={{
          display: 'flex', gap: 4, flexWrap: 'wrap', padding: '4px 0',
          borderBottom: `1px solid ${BB.border}`,
        }}
      >
        {TABS.map(t => {
          const active = tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              data-testid={`holding-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              style={{
                padding: '7px 12px', fontSize: 11, fontWeight: active ? 800 : 600, borderRadius: 6,
                cursor: 'pointer', border: `1px solid ${active ? BB.amber : BB.border}`,
                background: active ? BB.amberDim : 'transparent',
                color: active ? BB.amber : BB.text2,
              }}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      {/* Tab panels */}
      <div data-testid={`holding-panel-${tab}`} style={{ minHeight: 280 }}>
        {tab === 'overview' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Section title="Street consensus (at a glance)">
              <StreetConsensusCard
                street={street}
                pro={pro}
                cardAnalyst={cardAnalyst}
                scard={scard}
                cvdMode={cvdMode}
                onOpenAnalyst={() => setTab('analyst')}
              />
            </Section>
            <Section title="Position">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8, fontSize: 12 }}>
                {[
                  ['Shares', sh ? String(sh) : '—'],
                  ['Last', row.price != null ? `$${row.price.toFixed(2)}` : '—'],
                  ['Avg cost', row.cost != null ? `$${row.cost.toFixed(2)}` : '—'],
                  ['Cost basis', h.cost_basis != null ? fmt$(h.cost_basis, 0) : '—'],
                  ['Sector', scard?.sector || h.sector || '—'],
                  ['Industry', scard?.industry || h.industry || '—'],
                  ['Instrument', scard?.instrument_type || h.instrument_type || '—'],
                  ['Expense ratio', scard?.expense_ratio != null ? `${(Number(scard.expense_ratio) * 100).toFixed(2)}%` : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: BB.bgRow, border: `1px solid ${BB.border}`, borderRadius: 6, padding: '8px 10px' }}>
                    <div style={{ fontSize: 9, color: BB.text3, textTransform: 'uppercase' }}>{k}</div>
                    <div style={{ fontWeight: 700, color: BB.text0, marginTop: 2 }}>{v}</div>
                  </div>
                ))}
              </div>
            </Section>
            {scard?.description && (
              <Section title="Description">
                <div style={{ fontSize: 12, color: BB.text2, lineHeight: 1.55 }}>{scard.description}</div>
              </Section>
            )}
            {scard?.distribution && (
              <Section title="Distributions (ETF / income)">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                  <MetricCard label="TTM amount" value={scard.distribution.ttm_amount != null ? `$${scard.distribution.ttm_amount}` : '—'} />
                  <MetricCard label="Last amount" value={scard.distribution.last_amount != null ? `$${scard.distribution.last_amount}` : '—'} />
                  <MetricCard label="Last date" value={scard.distribution.last_date ? String(scard.distribution.last_date).slice(0, 10) : '—'} />
                  <MetricCard label="Next est." value={scard.distribution.next_est ? String(scard.distribution.next_est).slice(0, 10) : '—'} />
                  <MetricCard label="Cadence" value={scard.distribution.cadence || '—'} />
                </div>
              </Section>
            )}
            <Section title="Stop snapshot">
              <div style={{ fontSize: 13, fontFamily: BB.mono, fontWeight: 700, color: BB.text0 }}>{row.stopInstruction}</div>
              {row.stopContext && <div style={{ fontSize: 11, color: BB.text3, marginTop: 4 }}>{row.stopContext}</div>}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <button
                  type="button"
                  onClick={() => setTab('stops')}
                  style={{
                    fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6,
                    border: `1px solid ${BB.amber}66`, background: BB.amberDim, color: BB.amber, cursor: 'pointer',
                  }}
                >
                  Open Stop Management →
                </button>
                <button
                  type="button"
                  onClick={() => setTab('analyst')}
                  style={{
                    fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6,
                    border: `1px solid ${BB.blue}66`, background: BB.blueDim, color: BB.blue, cursor: 'pointer',
                  }}
                >
                  Analyst ratings & targets →
                </button>
              </div>
            </Section>
            {newsItems[0] && (
              <Section title="Latest news">
                <NewsList items={newsItems.slice(0, 3)} />
              </Section>
            )}
            {Array.isArray(ctx.coverage) && ctx.coverage.length > 0 && (
              <Section title="Research coverage (30d)">
                <CoverageChips cov={ctx.coverage} />
              </Section>
            )}
            <ShareReconHistory account={acct} symbol={symU} />
            <TransferHistorySection holding={h} account={acct} symbol={symU} />
          </div>
        )}

        {tab === 'pnl' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Section title="Unrealized P&L">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
                <MetricCard
                  label="Dollars"
                  value={pl$ != null ? `${pl$ >= 0 ? '+' : ''}${fmt$(pl$, 0)}` : '—'}
                  color={pl$ != null ? semanticSigned(pl$, cvdMode) : undefined}
                />
                <MetricCard
                  label="Percent"
                  value={pl != null ? `${pl >= 0 ? '+' : ''}${pl.toFixed(2)}%` : '—'}
                  color={pl != null ? semanticSigned(pl, cvdMode) : undefined}
                />
                <MetricCard label="Market value" value={fmt$(h.market_value, 0)} />
                <MetricCard label="Cost basis" value={h.cost_basis != null ? fmt$(h.cost_basis, 0) : '—'} />
                <MetricCard
                  label="Today $"
                  value={day$ != null ? `${day$ >= 0 ? '+' : ''}${fmt$(day$, 0)}` : '—'}
                  color={day$ != null ? semanticSigned(day$, cvdMode) : undefined}
                />
                <MetricCard
                  label="Today %"
                  value={h.day_change_pct != null ? `${Number(h.day_change_pct) >= 0 ? '+' : ''}${Number(h.day_change_pct).toFixed(2)}%` : '—'}
                  color={h.day_change_pct != null ? semanticSigned(Number(h.day_change_pct), cvdMode) : undefined}
                />
              </div>
            </Section>
            <Section title="Levels">
              <div style={{ fontSize: 12, color: BB.text2, lineHeight: 1.6 }}>
                <div>Last price: <b style={{ fontFamily: BB.mono, color: BB.text0 }}>{row.price != null ? `$${row.price.toFixed(2)}` : '—'}</b></div>
                <div>Avg cost / sh: <b style={{ fontFamily: BB.mono, color: BB.text0 }}>{row.cost != null ? `$${row.cost.toFixed(2)}` : '—'}</b></div>
                <div>Shares: <b style={{ fontFamily: BB.mono, color: BB.text0 }}>{sh || '—'}</b></div>
                {row.liveStopPrice != null && (
                  <div>Distance to stop: <b style={{ fontFamily: BB.mono, color: BB.amber }}>
                    {row.price != null && row.liveStopPrice
                      ? `${(((row.price - row.liveStopPrice) / row.price) * 100).toFixed(1)}%`
                      : '—'}
                  </b></div>
                )}
              </div>
            </Section>
          </div>
        )}

        {tab === 'technicals' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Section title="Momentum & volatility">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8 }}>
                <MetricCard label="RSI" value={rsi != null ? rsi.toFixed(1) : '—'} color={rsiZoneColor(rsiZone, cvdMode)} sub={rsiZone || undefined} />
                <MetricCard label="Week" value={fv?.perf_week != null ? `${fv.perf_week}%` : '—'} color={fv?.perf_week != null ? semanticSigned(Number(fv.perf_week), cvdMode) : undefined} />
                <MetricCard label="Month" value={fv?.perf_month != null ? `${fv.perf_month}%` : '—'} color={fv?.perf_month != null ? semanticSigned(Number(fv.perf_month), cvdMode) : undefined} />
                <MetricCard label="YTD" value={fv?.perf_ytd != null ? `${fv.perf_ytd}%` : '—'} color={fv?.perf_ytd != null ? semanticSigned(Number(fv.perf_ytd), cvdMode) : undefined} />
                <MetricCard label="vs SMA50" value={fv?.sma50 != null ? `${fv.sma50}%` : '—'} />
                <MetricCard label="ATR" value={fv?.atr != null ? String(fv.atr) : (h.atr != null ? String(h.atr) : '—')} />
                <MetricCard
                  label="Vol tier"
                  value={volTier ? volTier.toUpperCase() : '—'}
                  color={volTier === 'high' ? BB.red : volTier === 'low' ? BB.green : volTier ? BB.amber : undefined}
                />
                <MetricCard label="RVOL" value={fv?.rvol != null ? String(fv.rvol) : (h.rvol != null ? String(h.rvol) : '—')} />
              </div>
            </Section>
            {scard?.vs_sector_week != null && (
              <div style={{ fontSize: 12, color: semanticSigned(scard.vs_sector_week, cvdMode), fontWeight: 700 }}>
                {scard.vs_sector_week >= 0 ? '+' : ''}{scard.vs_sector_week}% vs sector this week
                {scard.sector ? ` (${scard.sector})` : ''}
              </div>
            )}
            <div style={{ fontSize: 10, color: BB.text3 }}>
              Sources: holdings RSI enrichment · Finviz strip · stop advisory volatility_tier
            </div>
          </div>
        )}

        {tab === 'analyst' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <StreetConsensusCard
              street={street}
              pro={pro}
              cardAnalyst={cardAnalyst}
              scard={scard}
              cvdMode={cvdMode}
              expanded
            />
            <Section title="Rating distribution (Street)">
              <RatingDistribution dist={street?.dist} period={street?.dist_period} source={street?.dist_source} />
            </Section>
            <Section title="Price target ladder">
              <TargetLadder street={street} pro={pro} cvdMode={cvdMode} last={row.price ?? street?.current} />
            </Section>
            {/* Compact bullet component used elsewhere */}
            <Section title="Analyst reviews (detail feed)">
              <AnalystReviews symbol={h.symbol} map={aMap} />
              {!street && !pro?.has && !cardAnalyst && (
                <div style={{ fontSize: 12, color: BB.text3, marginTop: 8 }}>
                  No Street consensus in analyst-detail / pro-analyst maps for {symU}.
                  ETFs often show look-through only (see card analyst above).
                </div>
              )}
            </Section>
            {pro && (
              <Section title="Pro-analyst pill (alignment)">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                  <MetricCard label="Street" value={pro.street || '—'} />
                  <MetricCard label="Internal" value={pro.internal || '—'} />
                  <MetricCard
                    label="Divergence"
                    value={pro.divergence || '—'}
                    color={pro.divergence === 'divergent' ? BB.red : pro.divergence === 'aligned' ? BB.green : BB.text3}
                  />
                  <MetricCard label="Source" value={pro.src || '—'} sub={pro.stale ? 'STALE >7d' : undefined} />
                  <MetricCard label="Event" value={pro.event ? String(pro.event).replace(/_/g, ' ') : '—'} />
                </div>
              </Section>
            )}
            {cardAnalyst && (
              <Section title="Symbol-card analyst (ETF look-through / proxy)">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                  <MetricCard label="Rating" value={String(cardAnalyst.rating || '—')} />
                  <MetricCard
                    label="Upside"
                    value={cardAnalyst.upside_pct != null ? `${cardAnalyst.upside_pct >= 0 ? '+' : ''}${cardAnalyst.upside_pct}%` : '—'}
                    color={cardAnalyst.upside_pct != null ? semanticSigned(Number(cardAnalyst.upside_pct), cvdMode) : undefined}
                  />
                  <MetricCard label="Basis" value={String(cardAnalyst.basis || scard?.analyst_basis || '—')} />
                  <MetricCard
                    label="Look-through"
                    value={scard?.analyst_look_through_pct != null ? `${scard.analyst_look_through_pct}%` : '—'}
                  />
                </div>
                {Array.isArray(cardAnalyst.sources) && (
                  <div style={{ fontSize: 10, color: BB.text3, marginTop: 8 }}>
                    Sources: {cardAnalyst.sources.join(', ')}
                  </div>
                )}
              </Section>
            )}
          </div>
        )}

        {tab === 'news' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Section title="Headlines">
              {newsItems.length === 0 ? (
                <div style={{ fontSize: 12, color: BB.text3 }}>No recent headlines in symbol cards / news ingest for {symU}.</div>
              ) : (
                <NewsList items={newsItems} />
              )}
            </Section>
            {catalysts.length > 0 && (
              <Section title="Catalysts">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {catalysts.map((c: any, i: number) => (
                    <div key={i} style={{
                      padding: '8px 10px', borderRadius: 6, background: BB.bgRow, border: `1px solid ${BB.border}`,
                      fontSize: 12, color: BB.text1,
                    }}>
                      {typeof c === 'string' ? c : (c.title || c.text || c.catalyst || JSON.stringify(c))}
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>
        )}

        {tab === 'earnings' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Section title="Next earnings">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                <MetricCard label="Next date" value={earnNext ? String(earnNext).slice(0, 10) : '—'} color={earnNext ? BB.amber : undefined} sub={row.earningsLabel || undefined} />
                <MetricCard label="Last date" value={earn?.last_date ? String(earn.last_date).slice(0, 10) : '—'} />
                <MetricCard label="EPS est." value={earn?.eps_estimate != null ? String(earn.eps_estimate) : '—'} />
                <MetricCard label="EPS actual" value={earn?.eps_actual != null ? String(earn.eps_actual) : '—'} />
                <MetricCard
                  label="Surprise"
                  value={earn?.surprise_pct != null ? `${earn.surprise_pct}%` : '—'}
                  color={earn?.surprise_pct != null ? semanticSigned(Number(earn.surprise_pct), cvdMode) : undefined}
                  sub={earn?.beat === true ? 'Beat' : earn?.beat === false ? 'Miss' : undefined}
                />
              </div>
            </Section>
            {!earn && !earnNext && (
              <div style={{ fontSize: 12, color: BB.text3 }}>
                No earnings record on symbol card for {symU}. ETFs often have no earnings calendar.
              </div>
            )}
          </div>
        )}

        {tab === 'stops' && stopSection}

        {tab === 'ai' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {(h.llm_health || h.llm_action) && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {h.llm_health && (
                  <span style={{
                    fontSize: 11, fontWeight: 800, padding: '4px 10px', borderRadius: 6,
                    background: BB.blueDim, border: `1px solid ${BB.blue}44`, color: BB.blue,
                  }}>Health · {h.llm_health}</span>
                )}
                {h.llm_action && (
                  <span style={{
                    fontSize: 11, fontWeight: 800, padding: '4px 10px', borderRadius: 6,
                    background: BB.bgRow, border: `1px solid ${BB.border}`, color: BB.text1,
                  }}>Action · {h.llm_action}</span>
                )}
                {h.llm_confidence != null && (
                  <span style={{ fontSize: 11, color: BB.text3 }}>Confidence {h.llm_confidence}</span>
                )}
              </div>
            )}
            {(h.llm_evidence?.length > 0 || h.llm_data_i_doubt) && (
              <div>
                {Number(h.llm_lots) > 1 && (
                  <div style={{
                    fontSize: 11, color: BB.amber, fontWeight: 700, padding: '6px 10px', marginBottom: 8,
                    borderRadius: 6, background: BB.amberDim, border: `1px solid ${BB.amber}44`,
                  }}>
                    ⚠ SYMBOL-LEVEL review — {h.symbol} spans {h.llm_lots} lots; facts may describe another account.
                  </div>
                )}
                <EvidenceBlock
                  title={h.llm_health ? `Holdings health · ${h.llm_health}` : 'Holdings LLM evidence'}
                  evidence={h.llm_evidence}
                  dataIDoubt={h.llm_data_i_doubt}
                  maxItems={10}
                />
              </div>
            )}
            {sc && (
              <Section title={`Stop curation (${laneLabel('grok')})`}>
                {(sc.grade || sc.recommendation) && (
                  <div style={{ fontSize: 12, color: BB.text1, marginBottom: 8, lineHeight: 1.45 }}>
                    {sc.grade && <b style={{ color: BB.amber }}>Grade {sc.grade}</b>}
                    {sc.recommendation && <span> · {sc.recommendation}</span>}
                    {sc.rr_assessment && <div style={{ fontSize: 11, color: BB.text3, marginTop: 4 }}>{sc.rr_assessment}</div>}
                  </div>
                )}
                {sc.evidence?.length > 0 && (
                  <EvidenceBlock title="Curation evidence" evidence={sc.evidence} dataIDoubt={sc.data_i_doubt} maxItems={6} />
                )}
              </Section>
            )}
            {Array.isArray(ctx.coverage) && ctx.coverage.length > 0 && (
              <Section title="LLM lanes that touched this symbol">
                <CoverageChips cov={ctx.coverage} />
              </Section>
            )}
            <Section title="Street analyst (same feed as Analyst tab)">
              <AnalystReviews symbol={h.symbol} map={aMap} />
              <button
                type="button"
                onClick={() => setTab('analyst')}
                style={{
                  marginTop: 8, fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 6,
                  border: `1px solid ${BB.blue}55`, background: BB.blueDim, color: BB.blue, cursor: 'pointer',
                }}
              >
                Open full Analyst & Targets →
              </button>
            </Section>
            {!h.llm_evidence?.length && !sc?.evidence?.length && !street && (
              <div style={{ fontSize: 12, color: BB.text3 }}>No AI evidence packed for this lot yet — Street data may still be on Analyst tab.</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Analyst / Street helpers ─────────────────────────────────────────── */

function streetRatingLabel(street: any, pro: any, card: any): string {
  const r = street?.rec || pro?.rec || card?.rating
  if (!r || String(r).toLowerCase() === 'none') {
    if (card?.rating) return String(card.rating).replace(/_/g, ' ')
    return '—'
  }
  return String(r).replace(/_/g, ' ')
}

function streetRatingColor(street: any, pro: any): string {
  const r = String(street?.rec || pro?.rec || '').toLowerCase()
  return REC_COLOR[r] || BB.text3
}

function streetAnalystCount(street: any, pro: any): string | undefined {
  const n = street?.n ?? pro?.n
  return n != null ? `${n} analysts` : undefined
}

function streetTarget(street: any, pro: any): string {
  const t = street?.target_mean ?? pro?.target
  return t != null ? `$${Number(t).toFixed(2)}` : '—'
}

function streetUpsideSub(street: any, pro: any): string | undefined {
  const u = street?.upside ?? pro?.upside
  if (u == null) return undefined
  return `${Number(u) >= 0 ? '+' : ''}${Number(u).toFixed(1)}% upside`
}

function streetUpsideColor(street: any, pro: any, cvd: HoldingsCvdMode): string | undefined {
  const u = street?.upside ?? pro?.upside
  return u != null ? semanticSigned(Number(u), cvd) : undefined
}

function StreetConsensusCard({
  street, pro, cardAnalyst, scard, cvdMode, expanded, onOpenAnalyst,
}: {
  street: any; pro: any; cardAnalyst: any; scard: any; cvdMode: HoldingsCvdMode
  expanded?: boolean; onOpenAnalyst?: () => void
}) {
  const hasStreet = Boolean(street || pro?.has)
  const hasCard = Boolean(cardAnalyst)
  if (!hasStreet && !hasCard) {
    return (
      <div style={{ fontSize: 12, color: BB.text3, lineHeight: 1.5 }}>
        No Street consensus or look-through analyst packed for this symbol yet
        (ETFs often lack Yahoo ratings — check look-through when available).
        {onOpenAnalyst && (
          <button type="button" onClick={onOpenAnalyst} style={{
            display: 'block', marginTop: 8, fontSize: 11, fontWeight: 700, padding: '5px 10px',
            borderRadius: 6, border: `1px solid ${BB.border}`, background: BB.bgRow, color: BB.text2, cursor: 'pointer',
          }}>Open Analyst tab →</button>
        )}
      </div>
    )
  }
  const rec = street?.rec || pro?.rec
  const rc = REC_COLOR[String(rec || '').toLowerCase()] || BB.text2
  const upside = street?.upside ?? pro?.upside ?? cardAnalyst?.upside_pct
  const target = street?.target_mean ?? pro?.target
  const n = street?.n ?? pro?.n
  return (
    <div style={{
      padding: '12px 14px', borderRadius: 10, background: 'rgba(96,165,250,.07)',
      border: `1px solid ${BB.blue}33`, display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        {rec && String(rec).toLowerCase() !== 'none' ? (
          <span style={{
            fontSize: 13, fontWeight: 800, padding: '4px 12px', borderRadius: 6,
            color: rc, border: `1px solid ${rc}`, textTransform: 'capitalize',
          }}>{String(rec).replace(/_/g, ' ')}</span>
        ) : cardAnalyst?.rating ? (
          <span style={{
            fontSize: 12, fontWeight: 800, padding: '4px 10px', borderRadius: 6,
            color: BB.blue, border: `1px solid ${BB.blue}55`,
          }}>{String(cardAnalyst.rating).replace(/_/g, ' ')}</span>
        ) : (
          <span style={{ fontSize: 12, color: BB.text3 }}>targets only / no rating</span>
        )}
        {n != null && <span style={{ fontSize: 12, color: BB.text2 }}><b>{n}</b> analysts</span>}
        {target != null && (
          <span style={{ fontSize: 13, fontFamily: BB.mono, fontWeight: 800, color: BB.text0 }}>
            Mean ${Number(target).toFixed(2)}
          </span>
        )}
        {upside != null && (
          <span style={{ fontSize: 13, fontWeight: 800, color: semanticSigned(Number(upside), cvdMode) }}>
            {Number(upside) >= 0 ? '+' : ''}{Number(upside).toFixed(1)}% to target
          </span>
        )}
        {pro?.stale && <span style={{ fontSize: 10, fontWeight: 800, color: BB.amber }}>STALE &gt;7d</span>}
        {pro?.divergence === 'divergent' && (
          <span style={{ fontSize: 11, fontWeight: 800, color: BB.red }}>≠ internal Street</span>
        )}
      </div>
      {(street?.target_high != null || street?.target_low != null) && (
        <div style={{ fontSize: 11, color: BB.text2, fontFamily: BB.mono }}>
          Range ${street.target_low ?? '—'} – ${street.target_high ?? '—'}
          {street?.target_median != null && ` · median $${street.target_median}`}
          {street?.current != null && ` · last $${street.current}`}
          {street?.as_of && ` · as of ${street.as_of}`}
        </div>
      )}
      {cardAnalyst && !hasStreet && (
        <div style={{ fontSize: 11, color: BB.text3 }}>
          ETF / proxy: {cardAnalyst.basis || scard?.analyst_basis || 'look-through'}
          {scard?.analyst_look_through_pct != null && ` · ${scard.analyst_look_through_pct}% look-through`}
        </div>
      )}
      {!expanded && onOpenAnalyst && (
        <button type="button" onClick={onOpenAnalyst} style={{
          alignSelf: 'flex-start', fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 6,
          border: `1px solid ${BB.blue}55`, background: BB.blueDim, color: BB.blue, cursor: 'pointer',
        }}>
          Full ratings, distribution & targets →
        </button>
      )}
      <div style={{ fontSize: 9, color: BB.text3 }}>
        Sources: /api/v2/analyst-detail · /api/v2/pro-analyst/pills · symbol-cards.analyst
      </div>
    </div>
  )
}

function RatingDistribution({ dist, period, source }: { dist?: Record<string, number>; period?: string; source?: string }) {
  if (!dist || !Object.keys(dist).length) {
    return <div style={{ fontSize: 12, color: BB.text3 }}>No rating distribution (common for ETFs / thin coverage).</div>
  }
  const total = DIST_TIERS.reduce((s, [k]) => s + (Number(dist[k]) || 0), 0) || 1
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {DIST_TIERS.map(([k, label, color]) => {
        const n = Number(dist[k]) || 0
        if (!n) return null
        const pct = (n / total) * 100
        return (
          <div key={k} style={{ display: 'grid', gridTemplateColumns: '100px 1fr 48px', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 700, color }}>{label}</span>
            <div style={{ height: 8, borderRadius: 4, background: BB.bg, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4 }} />
            </div>
            <span style={{ fontSize: 11, fontFamily: BB.mono, color: BB.text2, textAlign: 'right' }}>{n}</span>
          </div>
        )
      })}
      <div style={{ fontSize: 9, color: BB.text3, marginTop: 4 }}>
        Period {period || '—'} · source {source || 'finnhub'} (aggregated — no firm names)
      </div>
    </div>
  )
}

function TargetLadder({
  street, pro, cvdMode, last,
}: { street: any; pro: any; cvdMode: HoldingsCvdMode; last?: number | null }) {
  const mean = street?.target_mean ?? pro?.target
  const high = street?.target_high
  const low = street?.target_low
  const med = street?.target_median
  if (mean == null && high == null && low == null) {
    return <div style={{ fontSize: 12, color: BB.text3 }}>No price targets in feed.</div>
  }
  const rows: [string, any, string?][] = [
    ['High', high, BB.green],
    ['Mean', mean, semanticSigned(Number(street?.upside ?? pro?.upside ?? 0), cvdMode)],
    ['Median', med, BB.text1],
    ['Last', last ?? street?.current, BB.text0],
    ['Low', low, BB.red],
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8 }}>
      {rows.map(([lab, val, col]) => (
        val != null ? (
          <MetricCard key={lab} label={lab} value={`$${Number(val).toFixed(2)}`} color={col} />
        ) : null
      ))}
    </div>
  )
}

function CoverageChips({ cov }: { cov: any[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {cov.map((c, i) => (
        <span
          key={i}
          title={`${c.model} · ${c.lane} · ${c.n} · ${c.last_at}`}
          style={{
            fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6,
            background: BB.bgRow, border: `1px solid ${BB.border}`, color: BB.text2,
          }}
        >
          {c.lane || 'local'} · {c.model || '?'} · {c.n ?? 1}×
          {c.last_at && <span style={{ color: BB.text3, fontWeight: 500 }}> · {String(c.last_at).slice(0, 10)}</span>}
        </span>
      ))}
    </div>
  )
}

/** Past share reconciliations for this lot (tax / audit). */
function ShareReconHistory({ account, symbol }: { account: string; symbol: string }) {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => {
    const q = new URLSearchParams({ account, symbol, limit: '20' })
    fetch(`/api/v2/holdings/share-reconciliation/history?${q}`)
      .then(r => r.json())
      .then(j => setRows((j?.data || j)?.history || []))
      .catch(() => setRows([]))
  }, [account, symbol])
  if (!rows || rows.length === 0) return null
  return (
    <Section title="Share reconciliation history">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((r: any) => (
          <div key={r.id} style={{
            padding: '8px 10px', borderRadius: 6, background: BB.bgRow, border: `1px solid ${BB.border}`,
            fontSize: 11, color: BB.text1,
          }}>
            <span style={{ fontFamily: BB.mono, fontWeight: 700 }}>
              {r.previous_system_shares} → {r.new_system_shares}
            </span>
            <span style={{ color: BB.text3 }}> · {String(r.source || '').replace(/_/g, ' ')}</span>
            <span style={{ color: BB.text3 }}> · {String(r.reconciled_at || '').slice(0, 16)}</span>
            {r.notes && <div style={{ fontSize: 10, color: BB.text3, marginTop: 2 }}>{r.notes}</div>}
          </div>
        ))}
      </div>
    </Section>
  )
}

/** Cross-account transfer / rollover provenance (Fidelity→Schwab, Trad→Roth). */
function TransferHistorySection({
  holding, account, symbol,
}: { holding: any; account: string; symbol: string }) {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => {
    const q = new URLSearchParams({ account, symbol, limit: '20' })
    fetch(`/api/v2/holdings/transfer-history?${q}`)
      .then(r => r.json())
      .then(j => setRows((j?.data || j)?.history || []))
      .catch(() => setRows([]))
  }, [account, symbol])
  const localHist = Array.isArray(holding?.transfer_history) ? holding.transfer_history : []
  const tag = holding?.transfer_history_tag
  const displayRows = (rows && rows.length > 0)
    ? rows
    : localHist.map((e: any, i: number) => ({ id: e.event_id || i, ...e }))
  const normalized = Boolean(holding?.normalized_after_transfer || holding?.performance_adjusted)
  if (!displayRows.length && !normalized && !tag) return null
  return (
    <Section title="Transfer / rollover history">
      {normalized && (
        <div style={{
          fontSize: 11, fontWeight: 700, color: '#f59e0b', marginBottom: 8,
          padding: '6px 8px', borderRadius: 6, background: 'rgba(245,158,11,.08)',
          border: '1px solid rgba(245,158,11,.35)',
        }}>
          {holding?.normalization_status || 'Position normalized after rollover/transfer'}
          {holding?.transfer_display_note && (
            <span style={{ fontWeight: 500, color: BB.text2 }}> · {holding.transfer_display_note}</span>
          )}
        </div>
      )}
      {(holding?.original_source_account || holding?.current_account) && (
        <div style={{ fontSize: 11, color: BB.text2, marginBottom: 8 }}>
          Source <b style={{ color: BB.text0 }}>{holding.original_source_account || '—'}</b>
          {' → '}
          current <b style={{ color: BB.text0 }}>{holding.current_account || account}</b>
          {holding?.adjusted_for_transfer && (
            <span style={{ color: BB.text3 }}> · adjusted {String(holding.adjusted_for_transfer).slice(0, 10)}</span>
          )}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {displayRows.map((r: any) => (
          <div key={r.id || r.event_id} style={{
            padding: '8px 10px', borderRadius: 6, background: BB.bgRow, border: `1px solid ${BB.border}`,
            fontSize: 11, color: BB.text1,
          }}>
            <div>
              <span style={{ fontFamily: BB.mono, fontWeight: 700 }}>
                {r.from_account || '?'} → {r.to_account || account}
              </span>
              <span style={{ color: BB.text3 }}>
                {' · '}{r.shares_moved ?? r.shares ?? '—'} sh
              </span>
              {r.transfer_type && (
                <span style={{ color: '#f59e0b', fontWeight: 700 }}>
                  {' · '}{String(r.transfer_type).replace(/_/g, ' ')}
                </span>
              )}
            </div>
            <div style={{ fontSize: 10, color: BB.text3, marginTop: 2 }}>
              {r.display_note || r.notes || ''}
              {r.detected_at ? ` · ${String(r.detected_at).slice(0, 10)}` : r.date ? ` · ${String(r.date).slice(0, 10)}` : ''}
              {r.status ? ` · ${r.status}` : ''}
              {r.per_share_basis != null ? ` · basis $${Number(r.per_share_basis).toFixed(2)}` : ''}
            </div>
          </div>
        ))}
        {!displayRows.length && tag && (
          <div style={{
            padding: '8px 10px', borderRadius: 6, background: BB.bgRow, border: `1px solid ${BB.border}`,
            fontSize: 11, color: BB.text1,
          }}>
            <span style={{ fontFamily: BB.mono, fontWeight: 700 }}>
              {tag.from_account} → {tag.to_account}
            </span>
            <span style={{ color: BB.text3 }}> · {tag.shares} sh · {tag.display_note || tag.status}</span>
          </div>
        )}
      </div>
    </Section>
  )
}

function NewsList({ items }: { items: any[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((n, i) => {
        const title = n.title || n.headline || '—'
        const sent = n.sentiment || n.catalyst_type || null
        return (
          <div
            key={i}
            style={{
              padding: '10px 12px', borderRadius: 8, background: BB.bgRow,
              border: `1px solid ${BB.border}`, lineHeight: 1.4,
            }}
          >
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              {n.url ? (
                <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#93c5fd', fontSize: 13, fontWeight: 600, flex: 1 }}>
                  {title}
                </a>
              ) : (
                <span style={{ color: BB.text0, fontSize: 13, fontWeight: 600, flex: 1 }}>{title}</span>
              )}
              {sent && (
                <span style={{
                  fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4,
                  color: sentimentColor(String(sent)), border: `1px solid ${sentimentColor(String(sent))}55`,
                  textTransform: 'uppercase',
                }}>
                  {String(sent)}
                </span>
              )}
            </div>
            <div style={{ fontSize: 10, color: BB.text3, marginTop: 4 }}>
              {[n.source, n.at ? String(n.at).slice(0, 16) : null].filter(Boolean).join(' · ')}
            </div>
          </div>
        )
      })}
    </div>
  )
}
