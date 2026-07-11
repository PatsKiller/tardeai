import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import WatchpoolHub from './WatchpoolHub'
import SectorsHub from './SectorsHub'
import PullbackMacdHub from './PullbackMacdHub'
import ScreenerFindsHub from './ScreenerFindsHub'

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
      <div className="hub-title-row">
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Watch</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Curated list · screener finds · directive pool · sectors · pullback/MACD</div>
        </div>
        <div className="hub-tabs">
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
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