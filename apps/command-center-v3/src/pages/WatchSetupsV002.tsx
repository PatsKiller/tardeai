/** Watch v002 — Setups / Sectors / Discover / Alerts (LQ-20261107-2993c).
 *
 *  One read per tab, each graded OK / STALE / UNKNOWN with its age. An unread list is never an empty list. Alerts are
 *  graded on the evaluator's last run and show the evaluator's own certified count next to the table count; disarm uses the
 *  existing POST /api/v2/watch/alerts. Watching only — no order, no size, no stop. */
import { useMemo, useState } from 'react'
import './WatchSetupsV002.css'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import WatchSubnav from '../components/watch/WatchSubnav'
import {
  ALERTS_API, ALERTS_POST, DISCOVER_API, PAGE_LIMIT, PULLBACK_API, SECTORS_API, alertRows, certifiedOf, disarmBody, discoveryGap, etText,
  findRows, gradeAlerts, gradeDiscover, gradePullback, gradeSectors, gradeSetups, poolRows, pullbackProvenance, pullbackRows, sectorRows,
  setupsUrl, unwrap,
  type AlertRow, type Certified, type FindRow, type Grade, type PoolRow, type PullbackProvenance, type PullbackRow, type SectorRow, type TabKey,
} from '../lib/watchSetupsV002'

const detail = (s: string) => `/watch/intelligence/${encodeURIComponent(s)}`

export type SetupsViewProps = {
  tab: TabKey
  grade: Grade | null
  loading: boolean
  error: string | null
  message: string
  offset: number
  total: number | null
  gap: string | null
  hasMore: boolean
  pool: PoolRow[]
  sectors: SectorRow[]
  finds: FindRow[]
  alerts: AlertRow[]
  certified: Certified | null
  pullback: PullbackRow[]
  pullbackInfo: PullbackProvenance | null
  onPage: (offset: number) => void
  onDisarm: (a: AlertRow) => void
  onRetry: () => void
}

const pillTone = (st: string | undefined) => (st === 'OK' ? 'ok' : st === 'STALE' ? 'warn' : 'bad')

export function WatchSetupsV002View(p: SetupsViewProps) {
  const unread = !p.grade && !p.loading
  const empty = (txt: string) => <div className="ws2-note" data-testid="watch-setups-empty">{txt}</div>
  const state = p.grade?.state ?? (p.loading ? 'LOADING' : 'UNKNOWN')
  return (
    <section className="v010 ws2" data-testid="watch-setups-v002">
      {/* W-04: the shared sub-nav IS the tab bar on this page — one tab set, no duplicate row. */}
      <WatchSubnav />
      <div className="ws2-asof" data-testid="setups-asof" data-state={state}>
        {p.loading ? <span className="v010-pill info">Loading…</span> : (
          <>
            <span className={`v010-pill ${pillTone(p.grade?.state)}`}>{p.grade ? p.grade.label : 'UNKNOWN'}</span>
            <span>{p.grade ? p.grade.basis.replace(/[_.]/g, ' ') : 'list could not be read'}</span>
          </>
        )}
        {p.grade?.reason ? <span className="ws2-why">{p.grade.reason}</span> : null}
      </div>
      {p.tab === 'alerts' && p.certified && !p.loading && (
        <div className={`ws2-note ${p.certified.mismatch ? 'bad' : p.certified.unknown ? 'warn' : ''}`} data-testid="alerts-certified"
          data-mismatch={p.certified.mismatch ? '1' : '0'} data-unknown={p.certified.unknown ? '1' : '0'}>
          {p.certified.text}{p.certified.mismatch ? ' — differs from the armed rows below' : ''}
        </div>
      )}
      {p.tab === 'discover' && p.gap && !p.loading && <div className="ws2-note warn" data-testid="discover-feed-gap">{p.gap}</div>}
      {p.tab === 'pullback' && p.pullbackInfo && !p.loading && (
        <div className="ws2-note" data-testid="pullback-provenance">
          {p.pullbackInfo.universe || 'Pullback/MACD screen'}
          {p.pullbackInfo.screened !== null ? ` · ${p.pullbackInfo.screened} screened` : ''}
          {p.pullbackInfo.triggers !== null
            ? ` · ${p.pullbackInfo.triggers} trigger${p.pullbackInfo.triggers === 1 ? '' : 's'}${p.pullbackInfo.triggersLive !== null ? ` (${p.pullbackInfo.triggersLive} with a live proposal)` : ''}`
            : ' · scan counts not reported'}
          {p.pullbackInfo.triggersStale !== null && p.pullbackInfo.triggersStale > 0 ? `, ${p.pullbackInfo.triggersStale} pointing at a dead proposal` : ''}
          {p.pullbackInfo.watch !== null ? ` · ${p.pullbackInfo.watch} watch` : ''}{p.pullbackInfo.held !== null ? ` · ${p.pullbackInfo.held} held` : ''}
          {p.pullbackInfo.dismissed !== null && p.pullbackInfo.dismissed > 0 ? ` · ${p.pullbackInfo.dismissed} in dismissal cooldown` : ''}
          {` · last scan ${etText(p.pullbackInfo.lastRun) ?? 'unknown'}`}
          {p.pullbackInfo.hit && p.pullbackInfo.hit.target1First !== null && p.pullbackInfo.hit.triggers !== null
            ? ` · ${p.pullbackInfo.hit.windowDays !== null ? `${p.pullbackInfo.hit.windowDays}-day` : 'record since ' + (etText(p.pullbackInfo.lastRun) ?? 'an unknown time')} record: ${p.pullbackInfo.hit.target1First}/${p.pullbackInfo.hit.triggers} reached target 1 first${p.pullbackInfo.hit.medianDays !== null ? `, median ${p.pullbackInfo.hit.medianDays} d` : ''}`
            : ' · no trigger record yet'}
        </div>
      )}
      {p.error && !p.loading && (
        <div className="ws2-note bad" data-testid="setups-error" role="alert">List could not be read: {p.error} <button type="button" className="v010-btn" onClick={p.onRetry}>Retry</button></div>
      )}
      {p.message && <div className="ws2-note" data-testid="setups-message" role="status">{p.message}</div>}
      {unread || p.loading ? null : p.tab === 'setups' ? (
        p.pool.length === 0 ? empty('No setups in the watchpool.') : (
          <ul className="ws2-rows" data-testid="setups-rows">
            {p.pool.map(r => (
              <li key={`${r.symbol}-${r.strategy}-${r.origin}`} className="ws2-row" data-testid={`setup-${r.symbol}`}>
                <Link className="v010-link ws2-sym" to={detail(r.symbol)}>{r.symbol}</Link><span>{r.strategy}</span><span>{r.status}</span><span className="ws2-dim">{r.origin}</span>
                {etText(r.enteredAt) && <span className="ws2-dim">entered {etText(r.enteredAt)}</span>}
              </li>
            ))}
          </ul>)
      ) : p.tab === 'sectors' ? (
        p.sectors.length === 0 ? empty('No sectors.') : (
          <ul className="ws2-rows" data-testid="sectors-rows">
            {p.sectors.map(r => (
              <li key={r.sector} className="ws2-row" data-testid={`sector-${r.sector}`}><strong>{r.sector}</strong><span>{r.count} names</span><span className="ws2-dim">{r.sample.slice(0, 5).join(', ')}</span></li>
            ))}
          </ul>)
      ) : p.tab === 'pullback' ? (
        p.pullback.length === 0 ? (
          p.grade?.state === 'UNKNOWN'
            ? <div className="ws2-note bad" data-testid="pullback-no-scan">No scan on record. The last completed Pullback/MACD scan is unknown, so an empty list here is not evidence of no candidates.</div>
            : empty('No pullback candidates from the last scan.')
        ) : (
          <ul className="ws2-rows" data-testid="pullback-rows">
            {p.pullback.map(r => (
              <li key={r.symbol} className="ws2-row" data-testid={`pullback-${r.symbol}`} data-tier={r.tier} data-held-conflict={r.heldConflict ? '1' : '0'}>
                <Link className="v010-link ws2-sym" to={detail(r.symbol)}>{r.symbol}</Link>
                <span className={`v010-pill ${r.tier === 'trigger' ? 'ok' : ''}`}>{r.tier}</span>
                {r.price !== null && <span>{r.price}</span>}
                {r.pullbackPct !== null && <span className="ws2-dim">pullback {r.pullbackPct}%</span>}
                {r.macdProxPct !== null && <span className="ws2-dim">MACD {r.macdProxPct}% away</span>}
                {r.entry !== null && <span className="ws2-dim">entry {r.entry} · stop {r.stop ?? '—'} · target {r.target1 ?? '—'}</span>}
                {r.rr !== null && <span className="ws2-dim">R:R {r.rr}</span>}
                {r.score !== null && <span className="ws2-dim">score {Math.round(r.score)}</span>}
                {r.proposalLive === true ? <span className="v010-pill info">in queue</span>
                  : r.proposalLive === false ? <span className="v010-pill warn">stale proposal{r.proposalStatus ? ` (${r.proposalStatus})` : ''}</span> : null}
                {r.held && <span className={`v010-pill ${r.heldConflict ? 'bad' : 'info'}`}>{r.heldConflict ? 'HELD · near stop' : `held: ${r.held}`}</span>}
                {r.redisplay && <span className="ws2-dim">{r.redisplay}</span>}
                {r.whyNot && <span className="ws2-dim">why not a trigger: {r.whyNot}</span>}
                {etText(r.firstSeenAt) && <span className="ws2-dim">first seen {etText(r.firstSeenAt)}</span>}
              </li>
            ))}
          </ul>)
      ) : p.tab === 'discover' ? (
        p.finds.length === 0 ? empty('No saved screener finds.') : (
          <ul className="ws2-rows" data-testid="discover-rows">
            {p.finds.map(r => (
              <li key={r.symbol} className="ws2-row" data-testid={`find-${r.symbol}`}><Link className="v010-link ws2-sym" to={detail(r.symbol)}>{r.symbol}</Link><span className="ws2-dim">{r.note}</span></li>
            ))}
          </ul>)
      ) : (
        p.alerts.length === 0 ? empty('No alerts armed.') : (
          <ul className="ws2-rows" data-testid="alerts-rows">
            {p.alerts.map(a => (
              <li key={a.id} className="ws2-row" data-testid={`alert-${a.id}`} data-active={a.active ? '1' : '0'}>
                <strong className="ws2-sym">{a.symbol}</strong><span>{a.condition}</span><span>{a.threshold}</span>
                <span className={`v010-pill ${a.active ? 'ok' : 'info'}`}>{a.active ? 'armed' : 'disarmed'}</span>
                {etText(a.lastFired) && <span className="ws2-dim">fired {etText(a.lastFired)}</span>}
                {a.active && <button type="button" className="v010-btn" data-testid={`alert-disarm-${a.id}`} onClick={() => p.onDisarm(a)}>Disarm</button>}
              </li>
            ))}
          </ul>)
      )}
      {p.tab === 'setups' && !unread && !p.loading && (
        <div className="ws2-paging" data-testid="setups-paging">
          <span>{p.total === null ? `${p.pool.length} shown · total unknown` : p.total === 0 ? 'none' : `${p.offset + 1}–${p.offset + p.pool.length} of ${p.total}`}</span>
          <button type="button" className="v010-btn" disabled={p.offset <= 0} onClick={() => p.onPage(Math.max(0, p.offset - PAGE_LIMIT))}>Previous</button>
          <button type="button" className="v010-btn" disabled={!p.hasMore} onClick={() => p.onPage(p.offset + PAGE_LIMIT)}>Next</button>
        </div>
      )}
    </section>
  )
}

const URLS = (tab: TabKey, offset: number) => tab === 'setups' ? setupsUrl(offset) : tab === 'sectors' ? SECTORS_API
  : tab === 'discover' ? DISCOVER_API : tab === 'pullback' ? PULLBACK_API : ALERTS_API

/** One mounted tab. The parent keys this by tab, so a tab switch remounts it: useApi keeps its last body across a path
 *  change, and a body from another tab must never be graded or parsed by this tab (review 2993cr R4). */
export function WatchSetupsTab({ tab }: { tab: TabKey }) {
  const [offset, setOffset] = useState(0)
  const [message, setMessage] = useState('')
  const { data, loading, error, refetch } = useApi<any>(URLS(tab, offset), tab === 'alerts' ? 60_000 : 120_000)
  const body = useMemo(() => unwrap(data), [data])
  const nowMs = Date.now()
  const grade = body ? (tab === 'setups' ? gradeSetups(body, nowMs) : tab === 'sectors' ? gradeSectors(body, nowMs)
    : tab === 'discover' ? gradeDiscover(body, nowMs) : tab === 'pullback' ? gradePullback(body, nowMs) : gradeAlerts(body, nowMs)) : null
  const pg = body?.pagination
  const disarm = async (a: AlertRow) => {
    try {
      const r = await fetch(ALERTS_POST, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(disarmBody(a.id)) })
      const j = unwrap(await r.json().catch(() => ({})))
      if (!r.ok || j?.ok === false) throw new Error(String(j?.error || `HTTP ${r.status}`))
      // The POST answers ok:true even when no row changed, so do not claim "disarmed": the refetched row says so.
      setMessage(`Disarm sent for ${a.symbol}. Check the row below: it reads "disarmed" once the change is stored.`); refetch()
    } catch (e) { setMessage(`Failed: ${String((e as Error).message || e).slice(0, 100)}`) }
  }
  return (
    <WatchSetupsV002View
      tab={tab} grade={grade} loading={loading && !body} error={error ? String(error) : null} message={message} offset={offset}
      total={typeof pg?.total === 'number' ? pg.total : null} hasMore={pg?.has_more === true}
      gap={tab === 'discover' && body ? discoveryGap(body) : null}
      pool={tab === 'setups' ? poolRows(body) : []} sectors={tab === 'sectors' ? sectorRows(body) : []}
      finds={tab === 'discover' ? findRows(body) : []} alerts={tab === 'alerts' ? alertRows(body) : []}
      pullback={tab === 'pullback' ? pullbackRows(body) : []} pullbackInfo={tab === 'pullback' && body ? pullbackProvenance(body) : null}
      certified={tab === 'alerts' && body ? certifiedOf(body, nowMs) : null}
      onPage={setOffset} onDisarm={a => void disarm(a)} onRetry={() => refetch()}
    />
  )
}

export default function WatchSetupsV002() {
  const [sp] = useSearchParams()
  const q = sp.get('tab')
  const tab: TabKey = q === 'sectors' || q === 'discover' || q === 'alerts' || q === 'pullback' ? q : 'setups'
  return <WatchSetupsTab key={tab} tab={tab} />
}
