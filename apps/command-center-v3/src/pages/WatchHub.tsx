import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import WatchpoolHub from './WatchpoolHub'
import SectorsHub from './SectorsHub'
import PullbackMacdHub from './PullbackMacdHub'
import ScreenerFindsHub from './ScreenerFindsHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab } from '../lib/terminalHubChrome'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Watchlist', 'Screener Finds', 'Watchpool', 'Sectors', 'Pullback/MACD'] as const
const TAB_SLUG: Record<typeof TABS[number], string> = {
  Watchlist: 'watchlist',
  'Screener Finds': 'screener-finds',
  Watchpool: 'watchpool',
  Sectors: 'sectors',
  'Pullback/MACD': 'pullback-macd',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([k, v]) => [v, k])) as Record<string, typeof TABS[number]>

export default function WatchHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab') ?? ''
  const initial = SLUG_TAB[raw] ?? 'Watchlist'
  const [tab, setTab] = useState<typeof TABS[number]>(initial)

  const selectTab = (t: typeof TABS[number]) => {
    setTab(t)
    const next = new URLSearchParams(searchParams)
    next.set('tab', TAB_SLUG[t])
    setSearchParams(next, { replace: true })
  }

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Watch</div>
          <div style={hubSubtitle(terminalUi)}>Curated list · screener finds · directive pool · sectors · pullback/MACD</div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={hubTab(tab === t, terminalUi)}>{t}</button>
          ))}
        </div>
      </div>
      <WatchRegimeStrip />
      {tab === 'Watchlist' && <WatchlistHub onDrill={onDrill} embedded />}
      {tab === 'Screener Finds' && <ScreenerFindsHub onDrill={onDrill} embedded />}
      {tab === 'Watchpool' && <WatchpoolHub onDrill={onDrill} embedded />}
      {tab === 'Sectors' && <SectorsHub onDrill={onDrill} embedded />}
      {tab === 'Pullback/MACD' && <PullbackMacdHub onDrill={onDrill} embedded />}
    </div>
  )
}

// Watch Desk v3 (WS-C): one tab-level regime chip on all buy-side tabs + WS-B alerts chip
import { useApi } from '../hooks/useApi'
function WatchRegimeStrip() {
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: alerts } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const label = String(regime?.regime_label || '').replace(/_/g, ' ')
  const riskOff = /off/i.test(label)
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '6px 0', fontSize: 11 }}>
      {label && (
        <span style={{ fontWeight: 800, color: riskOff ? '#f59e0b' : '#34d399', border: `1px solid ${riskOff ? '#f59e0b44' : '#34d39944'}`, borderRadius: 999, padding: '2px 10px' }}>
          regime {label}
        </span>
      )}
      {riskOff && <span style={{ color: 'var(--text3)' }}>Regime risk-off — pullback entries historically weaker; screeners unchanged.</span>}
      {(alerts?.active_count ?? 0) > 0 && (
        <span title="operator alerts armed — evaluated every 20 min RTH" style={{ fontWeight: 700, color: '#7dd3fc', border: '1px solid #7dd3fc44', borderRadius: 999, padding: '2px 10px' }}>
          🔔 {alerts.active_count} armed
        </span>
      )}
    </div>
  )
}
