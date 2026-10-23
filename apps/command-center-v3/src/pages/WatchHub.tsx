import { useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import WatchpoolHub from './WatchpoolHub'
import SectorsHub from './SectorsHub'
import PullbackMacdHub from './PullbackMacdHub'
import WatchIntelligenceUnified from './WatchIntelligenceUnified'
import WatchProspects from './WatchProspects'
import WatchMyList from './WatchMyList'
import WatchSuggests from './WatchSuggests'
import { HOW_FALLBACK, TAB_TIPS } from '../lib/watchListsModel'
import OpportunitiesHub from './OpportunitiesHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, BB, TYPE, RAIL } from '../lib/watchTokens'
import { ChipLegend } from '../components/TerminalChip'
import { useApi } from '../hooks/useApi'

interface Props { onDrill: (ctx: DrillContext) => void }

/** My Watchlist is the default Watch view (operator 2026-10-23: "where is my traditional watch list ... and where is
 *  the automated watch list"): My Watchlist (your names) · System Suggests (the system's proposals) · Prospects (every
 *  Watch name by stage) · Full universe (research; the curator's whole ranked list, slug "opportunities" kept for old
 *  links). The old Intelligence view stays reachable as "Classic view" (?tab=intelligence). */
const TABS = ['MyWatchlist', 'Suggests', 'Prospects', 'Opportunities', 'Watchpool', 'Sectors', 'Pullback/MACD', 'Intelligence'] as const
const TAB_LABEL: Record<typeof TABS[number], string> = {
  MyWatchlist: 'My Watchlist', Suggests: 'System Suggests', Prospects: 'Prospects', Opportunities: 'Full universe',
  Watchpool: 'Watchpool', Sectors: 'Sectors', 'Pullback/MACD': 'Pullback/MACD', Intelligence: 'Classic view',
}
const TAB_SLUG: Record<typeof TABS[number], string> = {
  MyWatchlist: 'my-watchlist',
  Suggests: 'suggests',
  Prospects: 'prospects',
  Intelligence: 'intelligence',
  Opportunities: 'opportunities',
  Watchpool: 'watchpool',
  Sectors: 'sectors',
  'Pullback/MACD': 'pullback-macd',
}
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([key, value]) => [value, key])) as Record<string, typeof TABS[number]>

export default function WatchHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab') ?? ''

  // No tab → My Watchlist (operator 2026-10-23). Legacy watchlist / screener deep links carry a classic `view`, so they open
  // the Classic (Intelligence) view they were written for.
  useEffect(() => {
    if (raw === 'watchlist' || raw === 'screener-finds') {
      const next = new URLSearchParams(searchParams)
      next.set('tab', 'intelligence')
      // preserve view query if present
      if (!next.get('view') && raw === 'screener-finds') next.set('view', 'screener_finds')
      if (!next.get('view') && raw === 'watchlist') next.set('view', 'top_ideas')
      setSearchParams(next, { replace: true })
      return
    }
    if (!SLUG_TAB[raw]) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', 'my-watchlist')
      setSearchParams(next, { replace: true })
    }
  }, [raw, searchParams, setSearchParams])

  const tab = SLUG_TAB[raw] ?? 'MyWatchlist'

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
            Watch <span style={{ color: BB.text3 }}>›</span> {TAB_LABEL[tab]}
          </div>
          <div style={hubSubtitle(terminalUi)}>
            {tab === 'MyWatchlist'
              ? 'Your names — starred first · never dropped by caps or expiry · last trade and re-entry for names you sold'
              : tab === 'Suggests'
              ? 'What the system proposes for your list · top of the Full universe ranking · add or dismiss'
              : tab === 'Prospects'
              ? 'Every Watch name by stage · yours always listed · conflicts shown, not hidden'
              : tab === 'Intelligence'
              ? 'Classic Intelligence view · kept for one release · Prospects is the primary Watch view'
              : tab === 'Opportunities'
                ? 'Research: everything the CIO curator scored, ranked by conviction · System Suggests is its top'
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
              data-testid={`watch-tab-${TAB_SLUG[candidate]}`}
              title={candidate === 'Intelligence' ? 'The previous Watch Intelligence view, kept for one release.' : TAB_TIPS[TAB_SLUG[candidate]]}
            >
              {TAB_LABEL[candidate]}
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
      <details data-testid="watch-how" style={{ margin: '2px 0 6px', fontSize: TYPE.sm, color: BB.text3 }}>
        <summary style={{ cursor: 'pointer', fontWeight: 700 }} title="What each Watch list is, and how it differs from Trading → Proposals.">How this page works — My Watchlist vs System Suggests vs Full universe vs Proposals</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, marginTop: 4 }}>
          {HOW_FALLBACK.map(h => (
            <div key={h.id} data-how={h.id}><b style={{ color: BB.text1 }}>{h.title}</b><div>{h.body}</div></div>
          ))}
        </div>
      </details>
      {tab === 'MyWatchlist' && <WatchMyList />}
      {tab === 'Suggests' && <WatchSuggests />}
      {tab === 'Prospects' && <WatchProspects />}
      {tab === 'Intelligence' && <WatchIntelligenceUnified />}
      {tab === 'Opportunities' && <OpportunitiesHub />}
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
