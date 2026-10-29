/** Bookmarkable TradeInView sections. Backend owns business facts; legacy journal links remain supported. */
import { useEffect, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import JournalHub from './JournalHub'
import TradeJourney from './TradeJourney'
import TradeCalendar from '../components/tradeinview/TradeCalendar'
import TradeReplayPage from '../components/tradeinview/TradeReplayPage'
import HoldingHistory from '../components/tradeinview/HoldingHistory'
import ReadableTime from '../components/ReadableTime'
import { useApi } from '../hooks/useApi'
import { FONT, TOKENS, TYPE } from '../lib/designTokens'
import { API_LIST, TOOLTIPS, unwrap } from '../lib/tradeJourneyModel'
import { TRADE_TABS, serverNumber, tabParams, tradeTab } from '../lib/tradeInViewModel'
import '../components/tradeinview/TradeInViewLayout.css'

export default function TradeInViewPage({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  const [params, setParams] = useSearchParams()
  const [handoff, setHandoff] = useState(() => { try { return !!sessionStorage.getItem('journal_tab') } catch { return false } })
  const tab = tradeTab(params, handoff)
  const api = useApi<any>(API_LIST, 60_000, { enabled: tab === 'journeys' || tab === 'replay' })
  const payload = unwrap(api.data)
  // Recharts measures tick labels in a hidden body-level span and never removes it, so the last
  // measured tick (e.g. a Journal chart axis value) lingered as stray page text on other tabs.
  useEffect(() => { document.getElementById('recharts_measurement_span')?.remove() }, [tab])
  const choose = (next: typeof tab) => { setHandoff(false); setParams(tabParams(params, next), { replace: true }) }
  // History → Replay is a push so browser/phone Back returns to the selected name.
  const replayTrip = (tradeId: string) => { setHandoff(false); const next = tabParams(params, 'replay'); next.set('trade', tradeId); next.delete('interval'); setParams(next) }
  return <div className="tradeinview" data-testid="tradeinview-page" style={{ color: TOKENS.text[0], fontFamily: FONT.sans, fontSize: TYPE.base, '--tradeinview-font-sm': `${TYPE.sm}px` } as CSSProperties}>
    <div className="tradeinview-heading"><h1 style={{ margin: 0, fontSize: TYPE.xl - 2, fontWeight: 600 }}>TradeInView</h1>
      {payload && (tab === 'journeys' || tab === 'replay') && <span style={{ color: TOKENS.text[2] }}>{serverNumber(payload.counts.open)} open · {serverNumber(payload.counts.closed)} closed{payload.window_days != null ? ` in ${payload.window_days} days` : ' · range unavailable'} · {serverNumber(payload.counts.internal)} from internal · {serverNumber(payload.counts.unknown)} origin unknown</span>}
    </div>
    {payload?.interim && (tab === 'journeys' || tab === 'replay') && <span data-testid="tj-interim" title={TOOLTIPS.interim} style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{payload.source_label}</span>}
    <nav className="tradeinview-tabs" role="tablist" aria-label="TradeInView sections">{TRADE_TABS.map(([key, label]) => <button type="button" role="tab" key={key} id={`trade-tab-${key}`} aria-selected={tab === key} aria-controls={`trade-panel-${key}`} tabIndex={tab === key ? 0 : -1} onClick={() => choose(key)} onKeyDown={e => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
      e.preventDefault(); const index = TRADE_TABS.findIndex(([value]) => value === key)
      const next = e.key === 'Home' ? 0 : e.key === 'End' ? TRADE_TABS.length - 1 : (index + (e.key === 'ArrowRight' ? 1 : -1) + TRADE_TABS.length) % TRADE_TABS.length
      choose(TRADE_TABS[next][0]); document.getElementById(`trade-tab-${TRADE_TABS[next][0]}`)?.focus()
    }}>{label}</button>)}</nav>
    {api.stale && (tab === 'journeys' || tab === 'replay') && <div role="status" style={{ color: TOKENS.warning }}>Journeys refresh unavailable — last successful snapshot collected <ReadableTime value={payload?.as_of} fallback="at an unknown time" />.</div>}
    {TRADE_TABS.map(([panel]) => <div key={panel} role="tabpanel" id={`trade-panel-${panel}`} aria-labelledby={`trade-tab-${panel}`} hidden={tab !== panel}>
      {tab === panel && <>
      {tab === 'journeys' && <TradeJourney payload={payload} loading={api.loading} error={api.error} embedded />}
      {tab === 'calendar' && <TradeCalendar />}
      {tab === 'replay' && <TradeReplayPage key={`${params.get('trade') || payload?.journeys[0]?.trade_id || ''}:${params.get('interval') || '1D'}`} payload={payload} loading={api.loading} error={api.error} />}
      {tab === 'history' && <HoldingHistory onReplay={replayTrip} />}
      {tab === 'classic' && <><Link to="/journal?tab=journeys" data-testid="tj-back" onClick={() => setHandoff(false)} style={{ color: TOKENS.info, display: 'inline-block', marginBottom: 10 }}>← Trade journeys</Link><JournalHub onDrill={onDrill} /></>}
      </>}
    </div>)}
  </div>
}
