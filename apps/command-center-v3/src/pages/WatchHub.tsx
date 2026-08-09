import { useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import WatchpoolHub from './WatchpoolHub'
import SectorsHub from './SectorsHub'
import PullbackMacdHub from './PullbackMacdHub'
import WatchIntelligenceUnified from './WatchIntelligenceUnified'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, BB, TYPE, RAIL } from '../lib/watchTokens'
import { ChipLegend } from '../components/TerminalChip'
import { useApi } from '../hooks/useApi'

interface Props { onDrill: (ctx: DrillContext) => void }

/** Secondary research lenses only — Watchlist/Intelligence/Screener are NOT tabs. */
const TABS = ['Intelligence', 'Watchpool', 'Sectors', 'Pullback/MACD'] as const
const TAB_SLUG: Record<typeof TABS[number], string> = {
  Intelligence: 'intelligence',
  Watchpool: 'watchpool',
  Sectors: 'sectors',
  'Pullback/MACD': 'pullback-macd',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([key, value]) => [value, key])) as Record<string, typeof TABS[number]>

export default function WatchHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab') ?? ''

  // Legacy tab redirects → primary Intelligence (no Watchlist/Screener nav)
  useEffect(() => {
    if (raw === 'watchlist' || raw === 'screener-finds' || raw === '') {
      const next = new URLSearchParams(searchParams)
      next.set('tab', 'intelligence')
      // preserve view query if present
      if (!next.get('view') && raw === 'screener-finds') next.set('view', 'screener_finds')
      if (!next.get('view') && (raw === 'watchlist' || raw === '')) next.set('view', 'top_ideas')
      setSearchParams(next, { replace: true })
      return
    }
    if (!SLUG_TAB[raw]) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', 'intelligence')
      setSearchParams(next, { replace: true })
    }
  }, [raw, searchParams, setSearchParams])

  const tab = SLUG_TAB[raw] ?? 'Intelligence'

  const selectTab = (nextTab: typeof TABS[number]) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', TAB_SLUG[nextTab])
    setSearchParams(next, { replace: true })
  }

  return (
    <div data-watch-hub-primary>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>
            Watch <span style={{ color: BB.text3 }}>›</span> {tab === 'Intelligence' ? 'Intelligence' : tab}
          </div>
          <div style={hubSubtitle(terminalUi)}>
            {tab === 'Intelligence'
              ? 'Primary workspace · Screener filters integrated · legacy Watchlist hidden'
              : 'Secondary research lens'}
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {TABS.map(candidate => (
            <button
              type="button"
              key={candidate}
              aria-pressed={tab === candidate}
              onClick={() => selectTab(candidate)}
              style={hubTab(tab === candidate, terminalUi)}
            >
              {candidate}
            </button>
          ))}
          <Link
            to="/watch/discovery"
            style={{ fontSize: TYPE.xs, color: BB.text3, marginLeft: 6, textDecoration: 'none', fontWeight: 700 }}
          >
            Discovery
          </Link>
          <ChipLegend />
        </div>
      </div>
      <WatchRegimeStrip />
      {tab === 'Intelligence' && <WatchIntelligenceUnified />}
      {tab === 'Watchpool' && <WatchpoolHub onDrill={onDrill} embedded />}
      {tab === 'Sectors' && <SectorsHub onDrill={onDrill} embedded />}
      {tab === 'Pullback/MACD' && <PullbackMacdHub onDrill={onDrill} embedded />}
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
      {label && (
        <span style={{ fontWeight: 800, color: riskOff ? BB.amber : BB.green, border: `1px solid ${riskOff ? BB.amber : BB.green}55`, borderRadius: 999, padding: '2px 10px' }}>
          regime {label}
        </span>
      )}
      {riskOff && <span style={{ color: BB.text3 }}>Regime risk-off — pullback entries historically weaker.</span>}
      {(alerts?.active_count ?? 0) > 0 && (
        <span style={{ fontWeight: 700, color: BB.amber, border: `1px solid ${BB.amber}44`, borderRadius: 999, padding: '2px 10px' }}>
          🔔 {alerts.active_count} armed
        </span>
      )}
      <span style={{ color: BB.text3 }}>
        rail: <span style={{ color: BB.green }}>▎favorable</span>{' '}
        <span style={{ color: BB.amber }}>▎attention</span>{' '}
        <span style={{ color: BB.red }}>▎breach</span>{' '}
        <span style={{ color: RAIL.neutral }}>▎neutral</span>
      </span>
    </div>
  )
}
