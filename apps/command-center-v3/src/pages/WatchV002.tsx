/** Watch v002 — Overview (LQ-20261107-2993a). The old 8-tab hub stays at /v3/watch-classic.
 *  One read of /api/v2/watch/status per load (re-read on demand), no polling, no writes. The chip is the server's
 *  verdict re-checked against each input's own as_of (lib/watchV002): unread / stale renders UNKNOWN / STALE with its
 *  age, never green. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { DiagnosticsDrawer, useSheetA11y } from '../components/home/v010'
import { loadingRead, readOnce, type Read } from '../lib/homeV010'
import { WATCH_STATUS_API, buildWatchStatus, watchDiagnostics, type WatchInputRow, type WatchStatusModel, type WatchStatusWire } from '../lib/watchV002'
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

/** Presentational: takes the model, draws it. Exported so the render states can be tested without a network. */
export function WatchV002View({ m, checkedLabel, onOpenWhy, onOpenDiag, onRecheck }: {
  m: WatchStatusModel; checkedLabel: string; onOpenWhy: () => void; onOpenDiag: () => void; onRecheck: () => void
}) {
  return (
    <div className="v010" data-testid="watch-v002">
      <div className="v010-head">
        <h1 className="v010-title">Watch</h1>
        <button type="button" className="v010-chip-btn" data-testid="watch-data-chip" data-state={m.chip.state}
          aria-label={`${m.chip.text}. Open why.`} onClick={onOpenWhy}>
          <span className={pill(m.chip.tone)}>{m.chip.state}</span>{m.chip.text}
        </button>
        <button type="button" className="v010-btn" onClick={onOpenDiag}>Diagnostics</button>
        <button type="button" className="v010-btn" onClick={onRecheck}>Re-check</button>
        <Link className="v010-link" to="/watch-classic" data-testid="watch-classic-link">Classic Watch</Link>
      </div>
      <nav className="wv2-tabs" aria-label="Watch sections">
        <span className="wv2-tab" aria-current="page">Overview</span>
        {['My List', 'Suggestions', 'Prospects', 'Setups', 'Sectors', 'Discover', 'Alerts'].map(t => (
          <Link key={t} className="wv2-tab later" to="/watch-classic" title="Not in v002 yet: opens the classic Watch">{t} · classic</Link>
        ))}
      </nav>
      <section className="v010-card" id="card-watch-gates" aria-labelledby="h-wv2-gates">
        <div className="v010-card-hd">
          <h2 className="v010-h2" id="h-wv2-gates">Watch gates</h2>
          <span className="v010-meta">{checkedLabel}</span>
        </div>
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
      </section>
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

function WatchV002Page() {
  const [read, setRead] = useState<Read<WatchStatusWire>>(() => loadingRead<WatchStatusWire>(WATCH_STATUS_API))
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)

  const load = useCallback(() => {
    let alive = true
    void readOnce<WatchStatusWire>(WATCH_STATUS_API).then(r => { if (alive) { setRead(r); setNowMs(Date.now()) } })
    return () => { alive = false }
  }, [])
  useEffect(() => load(), [load])
  // Clock only, no network: an open tab must demote a status read older than STATUS_MAX_AGE_S.
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  const m = useMemo(() => buildWatchStatus(read, nowMs), [read, nowMs])
  const records = useMemo(() => watchDiagnostics(m), [m])

  return (
    <>
      <WatchV002View m={m} checkedLabel={checkedText(m)} onOpenWhy={() => setWhyOpen(true)} onOpenDiag={() => setDiagOpen(true)}
        onRecheck={() => { setRead(loadingRead<WatchStatusWire>(WATCH_STATUS_API)); load() }} />
      <WatchWhySheet open={whyOpen} onClose={() => setWhyOpen(false)} state={m.chip.state} cause={m.cause} blockers={m.blockers} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)} records={records} fetchedAt={read.at || undefined}
        error={m.chip.state === 'OK' ? undefined : m.cause} />
    </>
  )
}
