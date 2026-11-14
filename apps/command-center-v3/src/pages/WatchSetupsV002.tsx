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
import WatchDiscoverRecentV002 from './WatchDiscoverRecentV002'
import {
  ALERTS_API, ALERTS_POST, ALERT_VIEW_DEFAULT, DISCOVER_API, PAGE_LIMIT, PULLBACK_API, SECTORS_API, alertDefinitionState, alertDuplicates,
  alertGroups, alertLifecycle, alertPolicy, alertRows, alertSplit, alertTotals, alertViewFrom, alertViewQuery, certifiedOf, disarmAlert,
  discoverCards, discoveryGap, etText, evaluatorSource, findRows, gradeAlerts, gradeDiscover, gradePullback, gradeSectors, gradeSetups, poolRows, poolValidity,
  proposalState, pullbackProvenance, pullbackRows, sectorContext, sectorRows, setupsUrl, signalText, unwrap, SETUPS_EVIDENCE_GAP,
  type AlertRow, type AlertView, type Certified, type DiscoverCard, type EvaluatorSource, type FindRow, type Grade, type PoolRow,
  type PullbackProvenance, type PullbackRow, type SectorContext, type SectorRow, type TabKey,
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
  sectorCtx?: SectorContext | null
  finds: FindRow[]
  cards?: DiscoverCard[]
  alerts: AlertRow[]
  /** WR-09: Active/History + search + page, held in the URL. Optional so an older caller still renders the default. */
  alertView?: AlertView
  onAlertView?: (v: AlertView) => void
  evaluatorSrc?: EvaluatorSource | null
  certified: Certified | null
  pullback: PullbackRow[]
  pullbackInfo: PullbackProvenance | null
  /** The clock the pullback row ages are measured against. Optional so an older caller still renders; the host passes
   *  the same `nowMs` it graded the tab with, so a quote's age and the scan's grade never disagree. */
  nowMs?: number
  onPage: (offset: number) => void
  onDisarm: (a: AlertRow) => void
  onRetry: () => void
}

const pillTone = (st: string | undefined) => (st === 'OK' ? 'ok' : st === 'STALE' ? 'warn' : 'bad')

/** WR-10: proposal readiness is its own named state. A rejected/expired/missing proposal is a BLOCK, not a colour on a
 *  trigger, and it is drawn before the plan numbers. */
const proposalPill = (r: PullbackRow) => {
  const ps = proposalState(r.proposalLive, r.proposalStatus)
  const tone = ps.key === 'in_queue' ? 'info' : ps.key === 'missing' ? 'bad' : 'warn'
  return <span className={`v010-pill ${tone}`} data-testid={`pullback-proposal-${r.symbol}`} data-proposal={ps.key}>{ps.text}</span>
}

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
      {p.tab === 'alerts' && p.evaluatorSrc && !p.loading && (
        <div className="ws2-note" data-testid="alerts-evaluator" data-state={p.evaluatorSrc.state}>
          Evaluator {p.evaluatorSrc.state}: {p.evaluatorSrc.producer} · {p.evaluatorSrc.schedule} · {p.evaluatorSrc.record}. Row state below is the alert definition's, not evidence of monitoring.
        </div>
      )}
      {p.tab === 'alerts' && p.certified && !p.loading && (
        <div className={`ws2-note ${p.certified.mismatch ? 'bad' : p.certified.unknown ? 'warn' : ''}`} data-testid="alerts-certified"
          data-mismatch={p.certified.mismatch ? '1' : '0'} data-unknown={p.certified.unknown ? '1' : '0'}>
          {p.certified.text}{p.certified.mismatch ? ' — differs from the armed rows below' : ''}
        </div>
      )}
      {p.tab === 'discover' && p.gap && !p.loading && <div className="ws2-note warn" data-testid="discover-feed-gap">{p.gap}</div>}
      {p.tab === 'discover' && (p.cards?.length ?? 0) > 0 && !p.loading && (
        <div className="ws2-note" data-testid="discover-cards">
          {(p.cards ?? []).map(c => (
            <span key={c.key} data-testid={`discover-card-${c.key}`} data-state={c.state}>
              <strong>{c.title}</strong>: {c.state} — {c.detail}.{' '}
            </span>
          ))}
        </div>
      )}
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
          {` · monitor ${p.pullbackInfo.monitor ?? 'UNKNOWN (no monitor stamp in this read)'}`}
          {` · quote ${p.pullbackInfo.quote ?? 'UNKNOWN (no quote time in this read)'}`}
          {` · candidate last evaluated ${p.pullbackInfo.candidateEvaluated ?? 'UNKNOWN (first seen is not last evaluated)'}`}
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
        p.pool.length === 0 ? empty('No setups in the watchpool.') : (<>
          {/* OBS-W6-b: what the read does not carry, said once above the rows. The stored snapshot has the mechanics; the
              bounded read drops it. A page that printed "ACTIVE" as validity would be inventing an evaluation. */}
          <div className="ws2-note" data-testid="setups-evidence-gap">{SETUPS_EVIDENCE_GAP}</div>
          <ul className="ws2-rows" data-testid="setups-rows">
            {p.pool.map(r => {
              const v = poolValidity(r.expiresAt, p.nowMs ?? Date.now())
              return (
                <li key={`${r.symbol}-${r.strategy}-${r.origin}`} className="ws2-row" data-testid={`setup-${r.symbol}`}>
                  <Link className="v010-link ws2-sym" to={detail(r.symbol)}>{r.symbol}</Link><span>{r.strategy}</span><span>{r.status}</span><span className="ws2-dim">{r.origin}</span>
                  {etText(r.enteredAt) && <span className="ws2-dim">entered {etText(r.enteredAt)}</span>}
                  {etText(r.expiresAt) && <span className="ws2-dim">expires {etText(r.expiresAt)}</span>}
                  <span className={`ws2-dim${v.key === 'expired_unreaped' ? ' bad' : ''}`} data-testid={`setup-validity-${r.symbol}`} data-validity={v.key}>{v.text}</span>
                </li>
              )
            })}
          </ul></>)
      ) : p.tab === 'sectors' ? (
        p.sectors.length === 0 ? empty('No sectors.') : (<>
          {p.sectorCtx && (
            <div className="ws2-note" data-testid="sectors-context">
              <span data-testid="sectors-source">{p.sectorCtx.producer}{p.sectorCtx.asOfText ? ` · updated ${p.sectorCtx.asOfText}` : ' · update time unknown'} · limit {p.sectorCtx.limitText}</span>
              <span data-testid="sectors-momentum">Sector strength: {p.sectorCtx.momentum.state} — {p.sectorCtx.momentum.reason}</span>
              <span className="ws2-dim" data-testid="sectors-label-note">{p.sectorCtx.labelNote}</span>
            </div>
          )}
          <ul className="ws2-rows" data-testid="sectors-rows">
            {p.sectors.map(r => (
              <li key={r.sector} className="ws2-row" data-testid={`sector-${r.sector}`}><strong>{r.sector}</strong><span>{r.count} names</span>
                <span className="ws2-dim">{r.sample.slice(0, 5).map((s, i) => (
                  <span key={s}>{i > 0 ? ', ' : ''}<Link className="v010-link" to={detail(s)}>{s}</Link></span>
                ))}</span></li>
            ))}
          </ul></>)
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
                <span className={`v010-pill ${r.tier === 'trigger' ? 'ok' : ''}`} data-testid={`pullback-signal-${r.symbol}`}>{signalText(r.tier)}</span>
                {proposalPill(r)}
                {r.held && <span className={`v010-pill ${r.heldConflict ? 'bad' : 'info'}`}>{r.heldConflict ? 'HELD · near stop' : `held: ${r.held}`}</span>}
                {r.price !== null && <span>{r.price}</span>}
                {r.pullbackPct !== null && <span className="ws2-dim">pullback {r.pullbackPct}%</span>}
                {r.macdProxPct !== null && <span className="ws2-dim">MACD {r.macdProxPct}% away</span>}
                {r.entry !== null && <span className="ws2-dim">scan plan entry {r.entry} · stop {r.stop ?? '—'} · target {r.target1 ?? '—'} (assumptions as of the last scan)</span>}
                {r.rr !== null && <span className="ws2-dim">R:R {r.rr}</span>}
                {r.score !== null && <span className="ws2-dim">score {Math.round(r.score)}</span>}
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
        <AlertsPanel rows={p.alerts} view={p.alertView ?? ALERT_VIEW_DEFAULT} onView={p.onAlertView} onDisarm={p.onDisarm} />
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

/** WR-09: 100 mixed-history rows with no way to see what needs attention now. Active is the default side, History is its
 *  own side, and every row says what its own state means in the evaluator's terms (one-shot spent, repeating in cooldown,
 *  disarmed through the API). The listed totals are the READ's counts; the endpoint's 100-row cap is named wherever a
 *  total could be mistaken for a census, and nothing here merges, deletes or rewrites a definition. */
function AlertsPanel({ rows, view, onView, onDisarm }: {
  rows: AlertRow[]; view: AlertView; onView?: (v: AlertView) => void; onDisarm: (a: AlertRow) => void
}) {
  const split = alertSplit(rows, view)
  const dups = alertDuplicates(rows)
  const set = (v: Partial<AlertView>) => onView?.({ ...view, ...v })
  if (rows.length === 0) {
    return <div className="ws2-note" data-testid="watch-setups-empty">No alert definitions in this read. An empty read is not evidence that none exist.</div>
  }
  return (
    <>
      <div className="ws2-alert-toolbar" data-testid="alerts-toolbar" role="group" aria-label="Alert list filters">
        <button type="button" className="v010-btn" aria-pressed={view.filter === 'active'} data-testid="alerts-filter-active"
          onClick={() => set({ filter: 'active', page: 1 })}>Active ({split.active})</button>
        <button type="button" className="v010-btn" aria-pressed={view.filter === 'history'} data-testid="alerts-filter-history"
          onClick={() => set({ filter: 'history', page: 1 })}>History ({split.history})</button>
        <input type="search" className="ws2-search" value={view.q} data-testid="alerts-search"
          aria-label="Search alerts by symbol, condition, threshold or note"
          onChange={e => set({ q: e.target.value, page: 1 })} />
      </div>
      <div className="ws2-note" data-testid="alerts-totals" data-capped={split.capped ? '1' : '0'}>{alertTotals(split)}</div>
      {dups.length > 0 && (
        <div className="ws2-note" data-testid="alerts-duplicates">
          {dups.slice(0, 5).map(d => (
            <span key={d.key} data-testid={`alert-dup-${d.symbol}-${d.ids[0]}`}>
              {d.ids.length} definitions share {d.symbol} {d.condition} {d.threshold || 'no threshold'} (ids {d.ids.join(', ')}; {d.activeCount} armed) — review context; nothing is merged or deleted.
            </span>
          ))}
          {dups.length > 5 ? <span>{dups.length - 5} more duplicate group{dups.length - 5 === 1 ? '' : 's'} in this read.</span> : null}
        </div>
      )}
      {split.matching === 0 ? (
        <div className="ws2-note" data-testid="alerts-empty-filter">
          {view.q
            ? `No ${view.filter === 'active' ? 'armed' : 'history'} definition matches "${view.q}".`
            : `No ${view.filter === 'active' ? 'armed' : 'disarmed'} definitions in this read.`}
          {view.filter === 'active' && split.history > 0
            ? ` ${split.history} disarmed definition${split.history === 1 ? '' : 's'} ${split.history === 1 ? 'is' : 'are'} in History.`
            : ''}
        </div>
      ) : (
        <ul className="ws2-rows" data-testid="alerts-rows">
          {alertGroups(split.rows).flatMap(g => [
            <li key={`group-${g.symbol}`} className="ws2-grouphead" data-testid={`alert-group-${g.symbol}`}>
              {g.symbol} · {g.rows.length} definition{g.rows.length === 1 ? '' : 's'} in this view
            </li>,
            ...g.rows.map(a => {
              const pol = alertPolicy(a), life = alertLifecycle(a)
              return (
                <li key={a.id} className="ws2-row" data-testid={`alert-${a.id}`} data-active={a.active ? '1' : '0'}
                  data-policy={pol.key} data-lifecycle={life.key}>
                  {a.link
                    ? <Link className="v010-link ws2-sym" to={detail(a.link)}>{a.symbol}</Link>
                    : <strong className="ws2-sym">{a.symbol}</strong>}
                  <span className="ws2-dim" data-testid={`alert-id-${a.id}`}>#{a.id}</span>
                  <span>{a.condition}</span><span>{a.threshold}</span>
                  <span className={`v010-pill ${a.active ? 'ok' : 'info'}`}>{alertDefinitionState(a.active)}</span>
                  <span className="v010-pill info" data-testid={`alert-policy-${a.id}`}>{pol.label}</span>
                  {etText(a.lastFired)
                    ? <span className="ws2-dim">last fired {etText(a.lastFired)}</span>
                    : <span className="ws2-dim">never fired</span>}
                  <span className="ws2-dim" data-testid={`alert-lifecycle-${a.id}`}>{life.label} — {life.detail}</span>
                  {etText(a.createdAt) && <span className="ws2-dim">created {etText(a.createdAt)}</span>}
                  {a.note && <span className="ws2-dim">{a.note}</span>}
                  {a.active && <button type="button" className="v010-btn" data-testid={`alert-disarm-${a.id}`} onClick={() => onDisarm(a)}>Disarm</button>}
                </li>
              )
            }),
          ])}
        </ul>
      )}
      {split.matching > 0 && (
        <div className="ws2-paging" data-testid="alerts-paging">
          <span>{split.start}–{split.end} of {split.matching}</span>
          <button type="button" className="v010-btn" disabled={split.page <= 1} onClick={() => set({ page: split.page - 1 })}>Previous</button>
          <button type="button" className="v010-btn" disabled={split.page >= split.pages} onClick={() => set({ page: split.page + 1 })}>Next</button>
        </div>
      )}
    </>
  )
}

const URLS = (tab: TabKey, offset: number) => tab === 'setups' ? setupsUrl(offset) : tab === 'sectors' ? SECTORS_API
  : tab === 'discover' ? DISCOVER_API : tab === 'pullback' ? PULLBACK_API : ALERTS_API

/** One mounted tab. The parent keys this by tab, so a tab switch remounts it: useApi keeps its last body across a path
 *  change, and a body from another tab must never be graded or parsed by this tab (review 2993cr R4). */
export function WatchSetupsTab({ tab, alertView, onAlertView }: {
  tab: TabKey; alertView?: AlertView; onAlertView?: (v: AlertView) => void
}) {
  const [offset, setOffset] = useState(0)
  const [message, setMessage] = useState('')
  const { data, loading, error, refetch } = useApi<any>(URLS(tab, offset), tab === 'alerts' ? 60_000 : 120_000)
  const body = useMemo(() => unwrap(data), [data])
  const nowMs = Date.now()
  const grade = body ? (tab === 'setups' ? gradeSetups(body, nowMs) : tab === 'sectors' ? gradeSectors(body, nowMs)
    : tab === 'discover' ? gradeDiscover(body, nowMs) : tab === 'pullback' ? gradePullback(body, nowMs) : gradeAlerts(body, nowMs)) : null
  const pg = body?.pagination
  const finds = tab === 'discover' ? findRows(body) : []
  const disarm = async (a: AlertRow) => {
    const post = async (b: { action: 'disarm'; id: number }) => {
      const r = await fetch(ALERTS_POST, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
      return { ok: r.ok, status: r.status, body: await r.json().catch(() => ({})) }
    }
    const out = await disarmAlert(a.id, a.symbol, post)
    setMessage(out.message)
    // Only a read-back can prove the change was stored; the POST's ok:true is not proof.
    if (out.ok) refetch()
  }
  return (
    <>
      <WatchSetupsV002View
        tab={tab} grade={grade} loading={loading && !body} error={error ? String(error) : null} message={message} offset={offset}
        total={typeof pg?.total === 'number' ? pg.total : null} hasMore={pg?.has_more === true}
        gap={tab === 'discover' && body ? discoveryGap(body) : null}
        pool={tab === 'setups' ? poolRows(body) : []} sectors={tab === 'sectors' ? sectorRows(body) : []}
        sectorCtx={tab === 'sectors' && body ? sectorContext(body, nowMs) : null}
        finds={finds} cards={tab === 'discover' && body ? discoverCards(body, nowMs, finds.length) : []}
        alerts={tab === 'alerts' ? alertRows(body) : []}
        alertView={alertView} onAlertView={onAlertView}
        evaluatorSrc={tab === 'alerts' && body ? evaluatorSource(body, nowMs) : null}
        pullback={tab === 'pullback' ? pullbackRows(body) : []} pullbackInfo={tab === 'pullback' && body ? pullbackProvenance(body) : null}
        nowMs={nowMs}
        certified={tab === 'alerts' && body ? certifiedOf(body, nowMs) : null}
        onPage={setOffset} onDisarm={a => void disarm(a)} onRetry={() => refetch()}
      />
      {/* WR-04/WR-05: real discoveries with their own clock and the persisted Add to My List journey. */}
      {tab === 'discover' && <WatchDiscoverRecentV002 />}
    </>
  )
}

export default function WatchSetupsV002() {
  const [sp, setSp] = useSearchParams()
  const q = sp.get('tab')
  const tab: TabKey = q === 'sectors' || q === 'discover' || q === 'alerts' || q === 'pullback' ? q : 'setups'
  const alertView = alertViewFrom(sp)
  // WR-09: the alert filter, search and page are URL state — reload, Back and a shared link land on the same view.
  const onAlertView = (v: AlertView) => {
    const next = new URLSearchParams(sp)
    for (const k of ['filter', 'q', 'alert_page']) next.delete(k)
    for (const [k, val] of Object.entries(alertViewQuery(v))) next.set(k, val)
    setSp(next, { replace: true })
  }
  return <WatchSetupsTab key={tab} tab={tab} alertView={alertView} onAlertView={onAlertView} />
}
