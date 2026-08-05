/**
 * Legacy Watchlist implementation — rollback only.
 * No normal navigation entry. Do not use as default.
 */
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import WatchTruthAuditPanel from '../components/WatchTruthAuditPanel'
import { BB, TYPE, hubTitle, hubSubtitle } from '../lib/watchTokens'
import { Link } from 'react-router-dom'
import { useTerminalUi } from '../lib/terminalUi'
import { useApi } from '../hooks/useApi'
import CioDailyPanel from '../components/rockville/CioDailyPanel'
import WatchCardV2 from '../components/rockville/WatchCardV2'
import { useState } from 'react'

interface Props { onDrill?: (ctx: DrillContext) => void }

export default function WatchLegacy({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  return (
    <div data-watch-legacy>
      <div style={{ marginBottom: 12 }}>
        <Link to="/watch" style={{ fontSize: TYPE.xs, color: BB.text3, textDecoration: 'none' }}>← Watch Intelligence (primary)</Link>
        <div style={hubTitle()}>Watch Legacy (rollback)</div>
        <div style={hubSubtitle(terminalUi)}>
          Hidden from normal navigation. Retained only for rollback and residual backend surfaces.
        </div>
      </div>
      <div style={{ border: `1px solid ${BB.border}`, background: BB.bgShift, color: BB.amber, borderRadius: 8, padding: 10, fontSize: TYPE.xs, marginBottom: 12 }}>
        <b>ROLLBACK SURFACE.</b> Competing Rockville / queue / card-wall content may appear here. Prefer /v3/watch.
      </div>
      <RockvilleWatchShadow />
      <WatchTruthAuditPanel />
      <WatchlistHub onDrill={onDrill || (() => {})} embedded />
    </div>
  )
}

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
        <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', marginBottom: 6 }}>
          ROCKVILLE SHADOW (legacy rollback only){' '}
          <button type="button" onClick={() => setShowShadow(s => !s)} style={{ fontSize: 10, marginLeft: 6, cursor: 'pointer' }}>
            {showShadow ? 'hide' : 'show'}
          </button>
        </div>
      )}
      {(visible || showShadow) && (
        <>
          <CioDailyPanel artifact={cio?.artifact} status={cio?.status} />
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
