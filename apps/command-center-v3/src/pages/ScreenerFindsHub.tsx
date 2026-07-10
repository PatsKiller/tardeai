import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

export default function ScreenerFindsHub({ onDrill, embedded }: Props) {
  const { data } = useApi<any>('/api/v2/screener-finds/candidates', 60_000)
  const count = data?.count ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{
        background: 'linear-gradient(90deg, rgba(96,165,250,.14), rgba(96,165,250,.04))',
        border: '1px solid rgba(96,165,250,.35)', borderRadius: 10, padding: '10px 14px',
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: '#f8fafc' }}>
          🔍 Screener Finds — Auto-Research lane
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, lineHeight: 1.45 }}>
          {count} active · Finviz screener discoveries with auto-research briefs ·
          stays visible while CIO is <b style={{ color: '#22c55e' }}>BUY</b>, <b style={{ color: '#22c55e' }}>STRONG_BUY</b>, <b style={{ color: '#60a5fa' }}>ADD</b>, or <b style={{ color: '#60a5fa' }}>ADD_ON_PULLBACK</b> ·
          full watchlist cards below
        </div>
      </div>
      <WatchlistHub onDrill={onDrill} embedded={embedded ?? true} lane="screener_finds" />
    </div>
  )
}