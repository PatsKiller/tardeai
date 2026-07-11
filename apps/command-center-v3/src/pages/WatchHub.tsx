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
      {tab === 'Watchlist' && <WatchlistHub onDrill={onDrill} embedded />}
      {tab === 'Screener Finds' && <ScreenerFindsHub onDrill={onDrill} embedded />}
      {tab === 'Watchpool' && <WatchpoolHub onDrill={onDrill} embedded />}
      {tab === 'Sectors' && <SectorsHub onDrill={onDrill} embedded />}
      {tab === 'Pullback/MACD' && <PullbackMacdHub onDrill={onDrill} embedded />}
    </div>
  )
}