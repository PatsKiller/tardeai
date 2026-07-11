import { useEffect, useRef } from 'react'
import AnalystReviews, { useAnalystMap } from './AnalystReviews'
import HoldingProtectionActions from './HoldingProtectionActions'
import HoldingReportLinks from './HoldingReportLinks'
import ProAnalystPill, { useProAnalystMap } from './ProAnalystPill'
import { EvidenceBlock } from './EvidenceBlock'
import { fmt$ } from '../lib/format'
import { buildHoldingsRowModel, plMetrics } from '../lib/holdingsRowModel'
import { BB, type HoldingsCvdMode, semanticSigned, semanticUp } from '../lib/holdingsTerminalTokens'
import { mergeLiveStop, stopReviewTooltip } from '../lib/stopReviewTooltip'
import { holdingReportEligible } from '../lib/reportLinks'

export interface HoldingsDetailContext {
  h: any
  protection?: any
  stopCuration?: any
  monitored?: any
  confirmedStop?: any
  brokerStopsFetchedAt?: string | null
  cardMap?: Record<string, any>
  fvMap?: Record<string, any>
  reportEntry?: any
  coverage?: any[]
  onRefreshMonitored?: () => void
  onPreflightUpdate?: (symbol: string, account: string, patch: { holding?: Record<string, unknown>; protection?: Record<string, unknown> }) => void
  cvdMode?: HoldingsCvdMode
  /** When 'stops', scroll to and highlight this holding's stop management block. */
  drawerFocus?: 'stops' | null
}

const rsiZoneColor = (s: string | undefined, cvd: HoldingsCvdMode) =>
  s === 'oversold' ? semanticUp(cvd) : s === 'overbought' ? BB.amber : BB.text3
const signalColor = (s: string | undefined, cvd: HoldingsCvdMode) => {
  const t = (s || '').toUpperCase()
  if (['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE'].includes(t)) return semanticUp(cvd)
  if (['TRIM', 'SELL', 'REDUCE', 'EXIT'].includes(t)) return BB.red
  if (['MONITOR', 'WATCH', 'CAUTION'].includes(t)) return BB.amber
  return BB.text2
}

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
  const stopKey = `${symU}:${h.account}`
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
  const schwabSmall = acct.startsWith('schwab') && sh > 0 && sh < 40
  const row = buildHoldingsRowModel({ h, pr, confirmedStop: ctx.confirmedStop, monitored: ctx.monitored })
  const stopMgmtRef = useRef<HTMLDivElement>(null)
  const focusStops = ctx.drawerFocus === 'stops'

  useEffect(() => {
    if (!focusStops) return
    const t = window.setTimeout(() => {
      stopMgmtRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 80)
    return () => window.clearTimeout(t)
  }, [focusStops, symU, acct])

  const stopMgmtBlock = (pr?.stop_price || schwabSmall || pr?.rec || focusStops) ? (
    <div
      ref={stopMgmtRef}
      id="holding-stop-management"
      style={{
        padding: '12px 14px', borderRadius: 10, display: 'flex', flexDirection: 'column', gap: 10,
        background: focusStops ? BB.amberDim : BB.bgRow,
        border: `1px solid ${focusStops ? BB.amber : BB.border}`,
        boxShadow: focusStops ? `0 0 0 1px ${BB.amber}33` : undefined,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 800, color: focusStops ? BB.amber : BB.text2, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        Stop management · {symU} · {acct.replace(/_/g, ' ')}
      </div>
      <div title={row.stopTooltip} style={{ padding: '10px 12px', background: BB.amberDim, border: `1px solid ${BB.amber}44`, borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: BB.amberAlt, fontFamily: BB.mono }}>{row.stopInstruction}</div>
        {row.stopContext && <div style={{ fontSize: 10, color: BB.text2, marginTop: 4 }}>{row.stopContext}</div>}
        {row.liveStopPrice != null && row.stopPrice != null && (
          <div style={{ fontSize: 9, color: BB.text3, marginTop: 6 }} title={stopTip}>
            Live {row.liveStopPrice.toFixed(2)} · Target {row.stopPrice.toFixed(2)}
          </div>
        )}
      </div>
      {(pr?.stop_price || schwabSmall) ? (
        <HoldingProtectionActions
          h={h}
          pr={pr}
          monitored={ctx.monitored}
          confirmedStop={ctx.confirmedStop}
          brokerStopsFetchedAt={ctx.brokerStopsFetchedAt}
          onRefresh={ctx.onRefreshMonitored}
          onPreflightUpdate={ctx.onPreflightUpdate}
        />
      ) : (
        <div style={{ fontSize: 10, color: BB.text3 }}>No broker stop controls for this holding yet — check evidence below or Stop Management tab.</div>
      )}
    </div>
  ) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: BB.fontMd, color: BB.text1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 22, fontWeight: 800, fontFamily: BB.mono, color: BB.text0 }}>{h.symbol}</span>
        <ProAnalystPill symbol={h.symbol} map={paMap} compact />
        {h.signal && (
          <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 9px', borderRadius: 4, background: `${signalColor(h.signal, cvdMode)}22`, color: signalColor(h.signal, cvdMode) }}>{h.signal}</span>
        )}
        <span style={{ fontSize: 9, color: BB.text3 }}>{h.name}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {[
          { l: 'Market value', v: fmt$(h.market_value, 0) },
          { l: 'Unrealized P/L', v: pl$ != null ? `${pl$ >= 0 ? '+' : ''}${fmt$(pl$, 0)}${pl != null ? ` (${pl >= 0 ? '+' : ''}${pl.toFixed(1)}%)` : ''}` : '—', c: pl$ != null ? semanticSigned(pl$, cvdMode) : BB.text3 },
          { l: 'Today', v: h.day_change_pct != null ? `${Number(h.day_change_pct) >= 0 ? '+' : ''}${Number(h.day_change_pct).toFixed(2)}%` : '—', c: semanticSigned(Number(h.day_change_pct ?? 0), cvdMode) },
          { l: '% Portfolio', v: h.portfolio_pct != null ? `${Number(h.portfolio_pct).toFixed(1)}%` : '—', tip: 'Weight of this holding across your entire portfolio (all accounts combined)' },
        ].map(m => (
          <div key={m.l} title={(m as any).tip} style={{ background: BB.bgRow, border: `1px solid ${BB.border}`, borderRadius: 8, padding: '8px 10px', cursor: (m as any).tip ? 'help' : undefined }}>
            <div style={{ fontSize: 8, color: BB.text3, textTransform: 'uppercase' }}>{m.l}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: m.c ?? BB.text0, marginTop: 2 }}>{m.v}</div>
          </div>
        ))}
      </div>

      {fv && (
        <div style={{ display: 'flex', gap: 12, fontSize: 10, padding: '6px 10px', background: BB.bgRow, borderRadius: 6, border: `1px solid ${BB.border}` }}>
          <span>RSI <b style={{ color: BB.text0 }}>{fv.rsi ?? '—'}</b></span>
          <span>W <b>{fv.perf_week ?? '—'}%</b></span>
          <span>M <b>{fv.perf_month ?? '—'}%</b></span>
          <span>YTD <b>{fv.perf_ytd ?? '—'}%</b></span>
        </div>
      )}

      {stopMgmtBlock}

      {(h.llm_evidence?.length > 0 || h.llm_data_i_doubt) && (
        <EvidenceBlock title={h.llm_health ? `Holdings health · ${h.llm_health}` : 'Holdings LLM evidence'} evidence={h.llm_evidence} dataIDoubt={h.llm_data_i_doubt} maxItems={6} />
      )}

      {(pr?.evidence?.length > 0 || sc?.evidence?.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {pr?.evidence?.length > 0 && (
            <EvidenceBlock title={`Stop advisory${pr.model ? ` · ${pr.model}` : ''}`} evidence={pr.evidence} dataIDoubt={pr.data_i_doubt} maxItems={5} />
          )}
          {sc?.evidence?.length > 0 && (
            <EvidenceBlock title={`Grok stop curation${sc.grade ? ` · ${sc.grade}` : ''}`} evidence={sc.evidence} dataIDoubt={sc.data_i_doubt} maxItems={4} />
          )}
        </div>
      )}

      {holdingReportEligible(h) && (
        <HoldingReportLinks symbol={h.symbol} entry={ctx.reportEntry} reportType={ctx.reportEntry?.report_type} />
      )}

      {scard && (
        <div style={{ borderTop: `1px solid ${BB.border}`, paddingTop: 10 }}>
          {scard.description && <div style={{ fontSize: 11, color: BB.text2, lineHeight: 1.5, marginBottom: 8 }}>{scard.description}</div>}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 9, marginBottom: 6 }}>
            {scard.sector && <span style={{ color: '#60a5fa' }}>{scard.sector}</span>}
            {scard.vs_sector_week != null && (
              <span style={{ color: semanticSigned(scard.vs_sector_week, cvdMode), fontWeight: 700 }}>
                {scard.vs_sector_week >= 0 ? '+' : ''}{scard.vs_sector_week}% vs sector
              </span>
            )}
            {h.rsi != null && (
              <span style={{ color: rsiZoneColor(h.rsi_status, cvdMode) }}>RSI {Math.round(h.rsi)} {h.rsi_status}</span>
            )}
          </div>
          <AnalystReviews symbol={h.symbol} map={aMap} />
          {(scard.news ?? []).slice(0, 5).map((n: any, i: number) => (
            <div key={i} style={{ fontSize: 9, lineHeight: 1.35, marginTop: 4 }}>
              <span style={{ color: BB.text3 }}>{n.source} · </span>
              {n.url ? <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#93c5fd' }}>{n.title}</a> : <span>{n.title}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}