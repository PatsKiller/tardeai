import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubStrip } from '../lib/terminalHubChrome'
import { BB } from '../lib/watchlistTerminalTokens'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

export default function ScreenerFindsHub({ onDrill, embedded }: Props) {
  const [terminalUi] = useTerminalUi()
  const { data } = useApi<any>('/api/v2/screener-finds/candidates', 60_000)
  const count = data?.count ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: terminalUi ? 6 : 12 }}>
      <div className="cc-panel" style={hubStrip(terminalUi)}>
        {terminalUi ? (
          <>
            <span style={{ fontWeight: 800, color: BB.amber, letterSpacing: '.06em' }}>SCREENER FINDS</span>
            {' · '}{count} active · auto-research lane · CIO BUY/STRONG_BUY/ADD only
          </>
        ) : (
          <>
            <div style={{ fontSize: 13, fontWeight: 800, color: '#f8fafc' }}>🔍 Screener Finds — Auto-Research lane</div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, lineHeight: 1.45 }}>
              {count} active · Finviz screener discoveries with auto-research briefs ·
              stays visible while CIO is <b style={{ color: '#22c55e' }}>BUY</b>, <b style={{ color: '#22c55e' }}>STRONG_BUY</b>, <b style={{ color: '#60a5fa' }}>ADD</b>, or <b style={{ color: '#60a5fa' }}>ADD_ON_PULLBACK</b> ·
              full watchlist cards below
            </div>
          </>
        )}
      </div>
      <WatchlistHub onDrill={onDrill} embedded={embedded ?? true} lane="screener_finds" />
    </div>
  )
}