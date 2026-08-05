import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import WatchTruthAuditPanel from '../components/WatchTruthAuditPanel'
import WatchlistHub from './WatchlistHub'
import WatchpoolHub from './WatchpoolHub'
import SectorsHub from './SectorsHub'
import PullbackMacdHub from './PullbackMacdHub'
import ScreenerFindsHub from './ScreenerFindsHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, BB, TYPE, RAIL } from '../lib/watchTokens'
import { ChipLegend } from '../components/TerminalChip'
import { useApi } from '../hooks/useApi'
import CioDailyPanel from '../components/rockville/CioDailyPanel'
import WatchCardV2 from '../components/rockville/WatchCardV2'
import WatchlistIntelligenceBoard from './WatchlistIntelligenceBoard'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Watchlist', 'Intelligence', 'Screener Finds', 'Watchpool', 'Sectors', 'Pullback/MACD'] as const
const TAB_SLUG: Record<typeof TABS[number], string> = {
  Watchlist: 'watchlist',
  Intelligence: 'intelligence',
  'Screener Finds': 'screener-finds',
  Watchpool: 'watchpool',
  Sectors: 'sectors',
  'Pullback/MACD': 'pullback-macd',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([key, value]) => [value, key])) as Record<string, typeof TABS[number]>

export default function WatchHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab') ?? ''
  const tab = SLUG_TAB[raw] ?? 'Watchlist'

  useEffect(() => {
    if (SLUG_TAB[raw]) return
    const next = new URLSearchParams(searchParams)
    next.set('tab', 'watchlist')
    setSearchParams(next, { replace: true })
  }, [raw, searchParams, setSearchParams])

  const selectTab = (nextTab: typeof TABS[number]) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', TAB_SLUG[nextTab])
    setSearchParams(next, { replace: true })
  }

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Watch <span style={{ color: BB.text3 }}>›</span> {tab}</div>
          <div style={hubSubtitle(terminalUi)}>
            {tab === 'Intelligence'
              ? 'Shadow Intelligence Board · Street rating primary · zero provider calls on load'
              : 'Watchlist is the default workspace · other tabs are explicit research lenses'}
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {TABS.map(candidate => (
            <button type="button" key={candidate} aria-pressed={tab === candidate} onClick={() => selectTab(candidate)} style={hubTab(tab === candidate, terminalUi)}>{candidate}</button>
          ))}
          <ChipLegend />
        </div>
      </div>
      <WatchRegimeStrip />
      {tab === 'Watchlist' && (
        <>
          <RockvilleWatchShadow />
          <WatchTruthAuditPanel />
          <WatchlistHub onDrill={onDrill} embedded />
        </>
      )}
      {tab === 'Intelligence' && <WatchlistIntelligenceBoard />}
      {tab === 'Screener Finds' && <ScreenerFindsHub onDrill={onDrill} embedded />}
      {tab === 'Watchpool' && <WatchpoolHub onDrill={onDrill} embedded />}
      {tab === 'Sectors' && <SectorsHub onDrill={onDrill} embedded />}
      {tab === 'Pullback/MACD' && <PullbackMacdHub onDrill={onDrill} embedded />}
    </div>
  )
}

/** Rockville card v2 + CIO panel — shadow by default; visible when flag on. */
function RockvilleWatchShadow() {
  const { data: cio } = useApi<any>('/api/v3/watch/cio/latest', 120_000)
  const { data: pri } = useApi<any>('/api/v3/watch/priority', 120_000)
  const flags = pri?.flags || cio?.flags || {}
  const shadow = flags.watch_card_v2_shadow !== false
  const visible = Boolean(flags.watch_card_v2_visible)
  const [showShadow, setShowShadow] = useState(true)
  if (!shadow && !visible) return null
  const cards = pri?.cards || []
  return (
    <div style={{ marginBottom: 14 }} data-rockville-shadow>
      {!visible && (
        <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', marginBottom: 6, letterSpacing: 0.4 }}>
          ROCKVILLE SHADOW (card v2 + CIO · not default){' '}
          <button type="button" onClick={() => setShowShadow(s => !s)} style={{ fontSize: 10, marginLeft: 6, cursor: 'pointer' }}>
            {showShadow ? 'hide' : 'show'}
          </button>
        </div>
      )}
      {(visible || showShadow) && (
        <>
          <CioDailyPanel artifact={cio?.artifact} status={cio?.status} />
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
            Live projection · {cards.length} cards · fixture_injected={String(pri?.fixture_injected ?? false)}
            {pri?.source ? ` · source ${pri.source}` : ''}
          </div>
          {cards.map((c: any) => (
            <WatchCardV2
              key={c.symbol}
              symbol={c.symbol}
              company={c.company}
              sector={c.sector}
              last={c.last}
              dayChangePct={c.day_change_pct}
              marketTs={c.market_ts || c.price_as_of}
              priceSource={c.price_source}
              quoteId={c.quote_id}
              sourceRecordId={c.source_record_id}
              marketSession={c.market_session}
              freshnessState={c.freshness_state}
              marketState={c.market_state}
              decision={c.decision}
              review={c.reflective_review}
              held={Boolean(c.held)}
            />
          ))}
        </>
      )}
    </div>
  )
}

function WatchRegimeStrip() {
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: alerts } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const label = String(regime?.regime_label || '').replace(/_/g, ' ')
  const riskOff = /off/i.test(label)
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '6px 0', fontSize: TYPE.sm, flexWrap: 'wrap' }}>
      {label && <span style={{ fontWeight: 800, color: riskOff ? BB.amber : BB.green, border: `1px solid ${riskOff ? BB.amber : BB.green}55`, borderRadius: 999, padding: '2px 10px' }}>regime {label}</span>}
      {riskOff && <span style={{ color: BB.text3 }}>Regime risk-off — pullback entries historically weaker; screeners unchanged.</span>}
      {(alerts?.active_count ?? 0) > 0 && <span title="operator alerts armed — evaluated every 20 min RTH" style={{ fontWeight: 700, color: BB.amber, border: `1px solid ${BB.amber}44`, borderRadius: 999, padding: '2px 10px' }}>🔔 {alerts.active_count} armed</span>}
      <span style={{ color: BB.text3 }}>rail: <span style={{ color: BB.green }}>▎favorable</span> <span style={{ color: BB.amber }}>▎attention</span> <span style={{ color: BB.red }}>▎breach</span> <span style={{ color: RAIL.neutral }}>▎neutral</span></span>
    </div>
  )
}
