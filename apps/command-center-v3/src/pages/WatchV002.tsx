/** Watch v002 — Overview (LQ-20261107-2993a; section order fixed by W-04, lead 00:47 ET).
 *
 *  Action/Triggers → Validation Gates → Since Last Visit → Watch Status → Details.
 *
 *  Reads (one per load, no polling): /api/v2/watch/status, /api/v2/watch/alerts/list,
 *  /api/v2/pullback-macd/candidates?tier=trigger and the ui/prefs `watch.last_seen` anchor. The visit is recorded only
 *  AFTER the window is computed, so a page load cannot erase the "since" window it is about to draw.
 *
 *  The chip is the server's verdict re-checked against each input's own as_of (lib/watchV002): unread / stale renders
 *  UNKNOWN / STALE with its age, never green. A section whose read failed says so; it never draws an empty success.
 *  Reading only — no order, no size, no stop, no write except the visit stamp.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { DiagnosticsDrawer, useSheetA11y } from '../components/home/v010'
import WatchSubnav from '../components/watch/WatchSubnav'
import { loadingRead, readOnce, type Read } from '../lib/homeV010'
import {
  RECHECK_IDLE, WATCH_STATUS_API, buildWatchStatus, recheckText, sourceClockOf, watchDiagnostics,
  type Recheck, type WatchInputRow, type WatchStatusModel, type WatchStatusWire,
} from '../lib/watchV002'
import {
  ALERTS_LIST_API, LAST_SEEN_API, LAST_SEEN_KEY, LAST_SEEN_POST, PULLBACK_TRIGGERS_API, actionMeta, actionRows, lastVisit,
  sinceRows, stampResult,
  type ActionRow, type LastVisit, type SinceRow,
} from '../lib/watchOverviewV002'
import './WatchV002.css'

const pill = (tone: string) => `v010-pill ${tone === 'ok' ? 'ok' : tone === 'warn' ? 'warn' : tone === 'bad' ? 'bad' : ''}`

export function WatchWhySheet({ open, onClose, state, cause, blockers }: { open: boolean; onClose: () => void; state: string; cause: string; blockers: WatchInputRow[] }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  useSheetA11y(open, onClose, dialogRef, closeRef)
  if (!open) return null
  return (
    <div className="v010-why-scrim" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="v010-why" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="wv2-why-title" id="sheet-why">
        <div className="v010-why-head">
          <h2 className="v010-why-title" id="wv2-why-title">Watch data: {state}{state === 'OK' ? '' : ' · why:'}</h2>
          <button type="button" ref={closeRef} className="v010-why-close" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <p className="v010-why-note">{cause}</p>
        {state !== 'OK' && (
          <>
            <p className="v010-why-note">UNKNOWN or STALE always overrides OK: an input that cannot be proven fresh is not called fresh.</p>
            {blockers.length === 0
              ? <p className="v010-why-note">No input detail: the status read itself failed.</p>
              : <ul className="v010-why-list">{blockers.map(b => (
                  <li className="v010-why-item" key={b.id}>
                    <div className="v010-why-txt">
                      <span className="v010-why-cat">{b.label}</span>
                      <span className="v010-why-detail">{b.reason || b.state}</span>
                      <span className="v010-why-age">{b.age !== '—' ? `${b.age} old · limit ${b.threshold}` : `limit ${b.threshold}`} · owner {b.owner}</span>
                    </div>
                    <span className={`v010-why-chip ${b.state === 'STALE' ? 'warn' : 'bad'}`}>{b.state}</span>
                  </li>))}
                </ul>}
          </>
        )}
      </div>
    </div>
  )
}

/** The two new sections' inputs, already computed by lib/watchOverviewV002. */
export type OverviewView = {
  actions: ActionRow[]
  since: SinceRow[]
  lastVisit: LastVisit
  /** Why this visit was not stamped (null = recorded, or not attempted). The anchor will not advance. */
  visitError?: string | null
  /** Names of the reads these sections depend on that did not answer OK. */
  unread: string[]
  loading: boolean
  statusState: string
  statusAt: string | null
  readFrom: string | null
  session: string
}

const Section = ({ id, title, meta, children }: { id: string; title: string; meta?: string; children: React.ReactNode }) => (
  <section className="v010-card" data-testid={id} aria-labelledby={`${id}-h`}>
    <div className="v010-card-hd">
      <h2 className="v010-h2" id={`${id}-h`}>{title}</h2>
      {meta ? <span className="v010-meta">{meta}</span> : null}
    </div>
    {children}
  </section>
)

/** Presentational: takes the models, draws them. Exported so the render states can be tested without a network. */
export function WatchV002View({ m, checkedLabel, ov, onOpenWhy, onOpenDiag, onRecheck, recheck, nowMs = 0 }: {
  m: WatchStatusModel; checkedLabel: string; ov: OverviewView; onOpenWhy: () => void; onOpenDiag: () => void; onRecheck: () => void
  /** WL-05: what the last "Recheck status" did, and its readback. Optional so render tests can omit it. */
  recheck?: Recheck; nowMs?: number
}) {
  const unreadOf = (...names: string[]) => ov.unread.filter(u => names.includes(u))
  const actionUnread = unreadOf('alert list', 'pullback candidates')
  const sinceUnread = unreadOf('alert list', 'pullback candidates', 'last visit')
  // WL-01: the verdict is computed over the required inputs only; say so and mark each input's scope, so a green
  // four-input verdict cannot be read as a certification of every Watch feature.
  const requiredIds = new Set(m.gates.map(g => g.id))
  const requiredCount = m.inputs.filter(i => requiredIds.has(i.id)).length
  const optionalCount = m.inputs.length - requiredCount
  return (
    <div className="v010" data-testid="watch-v002">
      <div className="v010-head">
        <h1 className="v010-title">Watch</h1>
        <button type="button" className="v010-chip-btn" data-testid="watch-data-chip" data-state={m.chip.state}
          aria-label={`${m.chip.text}. Open why.`} onClick={onOpenWhy}>
          <span className={pill(m.chip.tone)}>{m.chip.state}</span>{m.chip.text}
        </button>
        <button type="button" className="v010-btn" onClick={onOpenDiag}>Diagnostics</button>
        {/* WL-05: this reads the stored verdict and the overview lists again; it does not run a source writer. The label
            says "status", the title says what it does, and the readback below reports pending / success / failure. */}
        <button type="button" className="v010-btn" data-testid="watch-recheck" data-state={recheck?.state ?? 'IDLE'}
          disabled={recheck?.state === 'PENDING'} onClick={onRecheck}
          title="Re-reads the stored Watch verdict and the overview lists (reads only, and it records your visit). It does not start a source writer or refresh source data.">
          Recheck status
        </button>
        {/* The one remaining door to the classic hub, and it is not a tab: it is the surface's escape hatch, deep links
            keep working through it (reviews 2993r R1). No sub-nav item points here (lib/watchNav). */}
        <Link className="v010-link" to="/watch-classic" data-testid="watch-classic-link">Classic Watch</Link>
      </div>
      {recheck && recheck.state !== 'IDLE' && (
        <div className={`wv2-recheck ${recheck.state === 'FAILED' ? 'bad' : recheck.state === 'PENDING' ? '' : 'ok'}`}
          data-testid="recheck-readback" data-state={recheck.state} data-source-before={recheck.sourceBefore ?? 'none'}
          data-source-after={recheck.sourceAfter ?? 'none'} data-source-moved={recheck.sourceMoved === null ? 'unknown' : String(recheck.sourceMoved)}
          role={recheck.state === 'FAILED' ? 'alert' : 'status'}>
          {recheckText(recheck, nowMs)}
        </div>
      )}
      <WatchSubnav />

      <Section id="ov-actions" title="Action / Triggers" meta={actionMeta(ov.actions.length, actionUnread.length, ov.loading)}>
        {ov.loading ? <div className="v010-line">Reading actions…</div> : (
          <>
            {actionUnread.length > 0 && (
              <div className="v010-line" data-testid="ov-actions-unread" role="alert">
                Could not be read: {actionUnread.join(', ')}. This list may be incomplete — it is not evidence that nothing needs action.
              </div>
            )}
            {ov.actions.length === 0 ? (
              actionUnread.length === 0 ? <div className="v010-line" data-testid="ov-actions-none">No pullback trigger and no fired alert.</div> : null
            ) : (
              <ul className="wv2-list" data-testid="ov-action-rows">
                {ov.actions.map(a => (
                  <li className="wv2-row" key={a.id} data-testid={`action-${a.kind}-${a.symbol}`}>
                    <span className={`v010-pill ${a.tone}`}>{a.kind === 'trigger' ? 'trigger' : 'alert'}</span>
                    <Link className="v010-link wv2-row-t" to={a.href}>{a.symbol}</Link>
                    <span>{a.text}</span>
                    <span className="wv2-row-d">{a.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Section>

      <Section id="ov-gates" title="Validation Gates" meta={checkedLabel}>
        <div className="wv2-cause" data-testid="watch-cause">{m.cause}</div>
        {m.gates.length === 0 ? (
          <div className="v010-line" data-testid="watch-gates-none">{m.chip.state === 'LOADING' ? 'Reading Watch inputs…' : 'Watch inputs not available: the status could not be read.'}</div>
        ) : m.gates.map(g => (
          <div className="wv2-gate" key={g.id} data-testid={`watch-gate-${g.id}`} data-state={g.state}>
            <span className="wv2-gate-n">{g.label}</span>
            <span className={pill(g.state === 'OK' ? 'ok' : g.state === 'STALE' ? 'warn' : 'bad')}>{g.state}</span>
            <span className="wv2-gate-m">{g.age !== '—' ? `${g.age} old · limit ${g.threshold}` : `no timestamp · limit ${g.threshold}`}</span>
            <span className="wv2-gate-r">{g.reason ? `${g.reason} · ` : ''}source {g.source} · owner {g.owner}{g.needsBackend ? ' · NEEDS BACKEND' : ''}</span>
          </div>
        ))}
      </Section>

      <Section id="ov-since" title="Since Last Visit" meta={ov.loading ? 'reading…' : ov.lastVisit.label}>
        {ov.loading ? <div className="v010-line">Reading what changed…</div> : (
          <>
            {!ov.lastVisit.recorded && (
              <div className="v010-line" data-testid="ov-since-window" data-recorded="0">{ov.lastVisit.label}. The window is a fallback, not your last visit.</div>
            )}
            {ov.visitError ? (
              <div className="v010-line" data-testid="ov-visit-unrecorded" role="status">
                This visit could not be recorded ({ov.visitError}), so the next visit&apos;s window starts from the earlier anchor.
              </div>
            ) : null}
            {sinceUnread.length > 0 && (
              <div className="v010-line" data-testid="ov-since-unread" role="alert">
                Could not be read: {sinceUnread.join(', ')}. What changed may be incomplete.
              </div>
            )}
            {ov.since.length === 0 ? (
              sinceUnread.length === 0 ? <div className="v010-line" data-testid="ov-since-none">Nothing new in this window.</div> : null
            ) : (
              <ul className="wv2-list" data-testid="ov-since-rows">
                {ov.since.map(r => (
                  <li className="wv2-row" key={r.id} data-testid={`since-${r.kind}-${r.symbol}`}>
                    <span className={`v010-pill ${r.kind === 'alert' ? 'warn' : ''}`}>{r.kind}</span>
                    <Link className="v010-link wv2-row-t" to={`/watch/intelligence/${encodeURIComponent(r.symbol)}`}>{r.symbol}</Link>
                    <span>{r.text}</span>
                    <span className="wv2-row-d">{r.atText ?? 'time unknown'}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Section>

      <Section id="ov-status" title="Watch Status" meta={checkedLabel}>
        <div className="wv2-gate" data-testid="ov-status-row" data-state={m.chip.state}>
          <span className="wv2-gate-n">Verdict</span>
          <span className={pill(m.chip.tone)}>{m.chip.state}</span>
          {/* WL-01/WL-06: state the scope of the verdict exactly once — the cause itself is rendered in Validation
              Gates above, not repeated here; and the verdict is only as wide as the required inputs it covers. */}
          <span className="wv2-gate-m" data-testid="ov-status-scope">{`computed over ${m.gates.length} required input${m.gates.length === 1 ? '' : 's'}${optionalCount ? ` · ${optionalCount} optional input${optionalCount === 1 ? '' : 's'} not in the verdict` : ''}`}</span>
          <span className="wv2-gate-r">
            session {ov.session} · status read {ov.statusState}{ov.statusAt ? ` at ${new Date(ov.statusAt).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })} ET` : ''}
            {ov.readFrom ? ` · read from ${ov.readFrom}` : ''}
          </span>
        </div>
      </Section>

      <Section id="ov-details" title="Details" meta={`${m.inputs.length} input${m.inputs.length === 1 ? '' : 's'} · ${requiredCount} required`}>
        {m.inputs.length === 0 ? (
          <div className="v010-line" data-testid="ov-details-none">No input detail: the status read carried none.</div>
        ) : m.inputs.map(i => (
          <div className="wv2-detail" key={`d-${i.id}`} data-testid={`detail-${i.id}`} data-state={i.state}>
            <span className="wv2-gate-n">{i.label}</span>
            <span className={pill(i.state === 'OK' ? 'ok' : i.state === 'STALE' ? 'warn' : 'bad')}>{i.state}</span>
            <span className="v010-pill" data-testid={`detail-${i.id}-scope`}>{requiredIds.has(i.id) ? 'required' : 'optional'}</span>
            <span className="wv2-detail-s">{i.source} · owner {i.owner} · {i.asOfText} · age {i.age} · limit {i.threshold}</span>
            <span className="wv2-gate-r">{i.reason ?? 'within its threshold'}{i.needsBackend ? ' · NEEDS BACKEND' : ''}</span>
          </div>
        ))}
      </Section>
    </div>
  )
}

const checkedText = (m: WatchStatusModel) => (m.checkedAt
  ? `checked ${new Date(m.checkedAt).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })} ET · session ${m.session}` : '')

/** Every query written for the old hub (?tab=, ?view=, ?symbol=, ?conflict=, ?review= ...) keeps working: the Overview takes
 *  no query, so any non-empty one is a legacy deep link and opens the classic hub with the SAME query (REVIEW-2993r R1). */
export function classicTarget(search: string): string | null {
  const q = new URLSearchParams(search)
  return Array.from(q.keys()).length > 0 ? `/watch-classic${search.startsWith('?') ? search : `?${search}`}` : null
}

export default function WatchV002() {
  const loc = useLocation()
  const to = classicTarget(loc.search)
  if (to) return <Navigate to={to} replace />
  return <WatchV002Page />
}

type Body = Record<string, unknown> | null
type Reads = { status: Read<WatchStatusWire>; alerts: Read<Body>; candidates: Read<Body>; prefs: Read<Body> }

/** Record this visit with the server's stamp, after the window has been computed from the PREVIOUS one. A refusal or a
 *  failure is reported to `onError`: the anchor does not advance, and the section says so rather than silently showing a
 *  window that will never move. HTTP 200 is not a stamp: the prefs route answers 200 without a `value` when the key is
 *  not registered as a last-seen key, so the BODY is classified (review W-04 C1) and the line is drawn today and keeps
 *  working once `watch.last_seen` is registered. */
export function recordVisit(onError: (msg: string) => void): Promise<void> | void {
  if (typeof window === 'undefined') return
  const device = window.innerWidth <= 600 ? 'phone' : 'desktop'
  const body = JSON.stringify({ key: LAST_SEEN_KEY, value: { device } })
  try {
    return fetch(LAST_SEEN_POST, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body })
      .then(res => {
        if (!res.ok) { onError(`HTTP ${res.status}`); return }
        return res.json().then(
          (b: unknown) => { const why = stampResult(b); if (why) onError(why) },
          () => onError(stampResult(null) as string),
        )
      })
      .catch((e: unknown) => onError(e instanceof Error ? e.message : 'request failed'))
  } catch (e) {
    onError(e instanceof Error ? e.message : 'request failed')
  }
}

function WatchV002Page() {
  const [r, setR] = useState<Reads>(() => ({
    status: loadingRead<WatchStatusWire>(WATCH_STATUS_API), alerts: loadingRead<Body>(ALERTS_LIST_API),
    candidates: loadingRead<Body>(PULLBACK_TRIGGERS_API), prefs: loadingRead<Body>(LAST_SEEN_API),
  }))
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [visitErr, setVisitErr] = useState<string | null>(null)
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  // WL-05: the last good verdict, kept so a failed recheck never replaces good data with nothing.
  const lastGoodRef = useRef<Read<WatchStatusWire> | null>(null)
  const [recheck, setRecheck] = useState<Recheck>(RECHECK_IDLE)

  const load = useCallback((onDone?: (reads: Reads) => void) => {
    let alive = true
    void Promise.all([
      readOnce<WatchStatusWire>(WATCH_STATUS_API), readOnce<Body>(ALERTS_LIST_API),
      readOnce<Body>(PULLBACK_TRIGGERS_API), readOnce<Body>(LAST_SEEN_API),
    ]).then(([status, alerts, candidates, prefs]) => {
      if (!alive) return
      if (status.state === 'OK') lastGoodRef.current = status
      setR({ status, alerts, candidates, prefs }); setNowMs(Date.now())
      onDone?.({ status, alerts, candidates, prefs })
      // AFTER the window is drawn from the stored anchor; a failed stamp does not advance the anchor and is shown.
      recordVisit(msg => { if (alive) setVisitErr(msg) })
    })
    return () => { alive = false }
  }, [])
  useEffect(() => load(), [load])
  // Clock only, no network: an open tab must demote a status read older than STATUS_MAX_AGE_S.
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  const m = useMemo(() => buildWatchStatus(r.status, nowMs), [r.status, nowMs])
  const records = useMemo(() => watchDiagnostics(m), [m])
  /** WL-05: "Recheck status" re-reads the stored verdict; it never starts a source writer. So its readback reports the
   *  one data fact it can prove — whether the oldest source clock moved — and on failure it puts the last good verdict
   *  back on screen with its own, growing age instead of leaving the operator with nothing. */
  const doRecheck = useCallback(() => {
    if (recheck.state === 'PENDING') return
    const at = new Date().toISOString()
    const before = sourceClockOf(m)
    setRecheck({ state: 'PENDING', at, sourceBefore: before, sourceAfter: null, sourceMoved: null, lastGoodAt: null, error: null })
    load(({ status }) => {
      const kept = status.state === 'OK' ? null : lastGoodRef.current
      if (kept) setR(prev => ({ ...prev, status: kept }))
      const afterM = buildWatchStatus(kept ?? status, Date.now())
      setRecheck({
        state: status.state === 'OK' ? 'OK' : 'FAILED', at,
        sourceBefore: before, sourceAfter: sourceClockOf(afterM),
        // A kept body is the SAME body: comparing it with itself would "prove" an unchanged clock that was never re-read.
        sourceMoved: kept ? null : before !== null && sourceClockOf(afterM) !== null ? before !== sourceClockOf(afterM) : null,
        lastGoodAt: kept ? kept.at : null,
        error: status.state === 'OK' ? null : status.error || `the status read did not complete (${status.state})`,
      })
    })
  }, [recheck.state, m, load])
  const ov = useMemo<OverviewView>(() => {
    const lv = lastVisit(r.prefs, nowMs)
    return {
      actions: actionRows(r.alerts.state === 'OK' ? r.alerts.data : null, r.candidates.state === 'OK' ? r.candidates.data : null),
      since: sinceRows(r.alerts.state === 'OK' ? r.alerts.data : null, r.candidates.state === 'OK' ? r.candidates.data : null, lv.startMs),
      lastVisit: lv,
      visitError: visitErr,
      unread: [
        ...(r.alerts.state === 'OK' ? [] : ['alert list']),
        ...(r.candidates.state === 'OK' ? [] : ['pullback candidates']),
        ...(lv.recorded || lv.status !== 'UNKNOWN' ? [] : ['last visit']),
      ],
      loading: [r.alerts, r.candidates, r.prefs].some(x => x.state === 'LOADING'),
      statusState: r.status.state, statusAt: r.status.at, readFrom: (r.status.data as WatchStatusWire | undefined)?.read_from ?? null,
      session: m.session,
    }
  }, [r, nowMs, m, visitErr])

  return (
    <>
      <WatchV002View m={m} checkedLabel={checkedText(m)} ov={ov} onOpenWhy={() => setWhyOpen(true)} onOpenDiag={() => setDiagOpen(true)}
        onRecheck={doRecheck} recheck={recheck} nowMs={nowMs} />
      <WatchWhySheet open={whyOpen} onClose={() => setWhyOpen(false)} state={m.chip.state} cause={m.cause} blockers={m.blockers} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)} records={records} fetchedAt={r.status.at || undefined}
        error={m.chip.state === 'OK' ? undefined : m.cause} />
    </>
  )
}
