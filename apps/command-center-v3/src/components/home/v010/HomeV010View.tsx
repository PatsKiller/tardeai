/** Home v010 — the presentational page (element ids kept from the approved v010 Home mockup in design/pages). Pure: takes the model, draws it.
 *  Every block with no production source carries a visible NEEDS BACKEND tag; a failed read is drawn as UNKNOWN. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { etTime, type HomeV010Model, type RowState } from '../../../lib/homeV010'
import './HomeV010.css'

export const P0_VISIBLE = 3

const NB = () => <span className="v010-nb" title="No production source in this build">NEEDS BACKEND</span>

function pillClass(s: RowState): string {
  if (s === 'OK') return 'v010-pill ok'
  if (s === 'WARN' || s === 'STALE') return 'v010-pill warn'
  if (s === 'LOADING') return 'v010-pill'
  return 'v010-pill bad'
}

export interface HomeV010ViewProps {
  model: HomeV010Model
  nowIso: string
  onOpenWhy: () => void
  onOpenDiag: () => void
}

export default function HomeV010View({ model: m, nowIso, onOpenWhy, onOpenDiag }: HomeV010ViewProps) {
  const [showAllP0, setShowAllP0] = useState(false)
  const p0Shown = showAllP0 ? m.p0 : m.p0.slice(0, P0_VISIBLE)
  const p0More = m.p0.length - p0Shown.length

  const action = (
    <section className="v010-card" id="card-action" aria-labelledby="h-action">
      <div className="v010-card-hd">
        <h2 className="v010-h2" id="h-action">Action required</h2>
        <span className="v010-meta">{m.checkedAt ? `checked ${etTime(m.checkedAt)}` : ''}</span>
      </div>
      {m.loading && m.p0.length === 0 && m.unread.length === 0 ? (
        <div className="v010-line" data-testid="action-loading">Reading action sources…</div>
      ) : m.actionEmpty ? (
        <div className="v010-line" data-testid="action-clear">Nothing needs action · checked {etTime(m.checkedAt)}</div>
      ) : (
        <>
          {m.unread.map(u => (
            <div className="v010-unk" key={u.source} data-testid="action-unknown">
              {u.state === 'TIMED OUT' ? 'TIMED OUT' : 'UNKNOWN'} — could not read {u.label} ({u.source}){u.lastGood ? ` (last good ${etTime(u.lastGood)})` : ' (no last good read)'}
            </div>
          ))}
          {p0Shown.map(p => (
            <div className="v010-p0" key={p.id}>
              <div className="v010-p0-k">P0 · {p.title.split(' · ')[0].toUpperCase()}</div>
              <div className="v010-p0-t">{p.title}</div>
              {p.detail.map((d, i) => <div className="v010-p0-d" key={i}>{d}</div>)}
            </div>
          ))}
          {p0More > 0 && (
            <button type="button" className="v010-btn" style={{ width: '100%', marginBottom: 8 }} onClick={() => setShowAllP0(true)}>+{p0More} more P0 items</button>
          )}
          {m.stops.map(s => (
            <div className="v010-stop" key={s.id}>
              <div className="v010-p0-k" style={{ color: 'var(--text-2)' }}>STOP ADVICE (CIO brief)</div>
              <div className="v010-p0-t">{s.title}</div>
              {s.detail.map((d, i) => <div className="v010-p0-d" key={i}>{d}</div>)}
            </div>
          ))}
          {((m.approvalsCount ?? 0) > 0 || (m.p1Count ?? 0) > 0) && (
            <div className="v010-line">
              <span className="v010-pill warn">P1</span>
              <span>{[m.approvalsCount ? `${m.approvalsCount} approval${m.approvalsCount === 1 ? '' : 's'}` : null,
                m.p1Count ? `${m.p1Count} P1 incident${m.p1Count === 1 ? '' : 's'}` : null].filter(Boolean).join(' · ')}</span>
              {m.approvalsCount ? <Link className="v010-link" to="/approvals" style={{ marginLeft: 'auto' }}>Review</Link> : null}
            </div>
          )}
        </>
      )}
    </section>
  )

  const gates = (
    <section className="v010-card" id="card-gates" aria-labelledby="h-gates">
      <div className="v010-card-hd">
        <h2 className="v010-h2" id="h-gates">Trading gates {m.gates ? null : <NB />}</h2>
        <span className="v010-meta">{m.gates ? 'from /api/v2/home/status' : ''}</span>
      </div>
      {m.gates && m.gates.length > 0 ? m.gates.map(g => (
        <div className="v010-srow" id={`gate-${g.id}`} key={g.id} data-state={g.state} data-testid="gate-row">
          <span className="v010-srow-n">{g.label}</span>
          <span className={pillClass(g.state)}>{g.state}</span>
          <span className="v010-srow-v">{g.asOf ? `as of ${etTime(g.asOf, true)}${g.age ? ` · ${g.age} old` : ''}` : 'no as-of'} {g.needsBackend ? <NB /> : null}</span>
          {g.state !== 'OK' && (
            <span className="v010-srow-c">{g.reason ? <>Why: <b>{g.reason}</b> · </> : null}Source: <b>{g.source}</b></span>
          )}
        </div>
      )) : (
        <div className="v010-line" data-testid="gates-na">{m.loading && m.tradeReadyCause === 'reading…' ? 'Trading gates: reading…' : 'Trading gates: not available'}</div>
      )}
    </section>
  )

  const since = (
    <section className="v010-card" id="card-since" aria-labelledby="h-since">
      <div className="v010-card-hd">
        <h2 className="v010-h2" id="h-since">Since your last visit</h2>
        <span className="v010-meta" data-testid="since-window">{m.since.header}</span>
      </div>
      {m.since.state === 'LOADING' ? <div className="v010-muted">reading…</div>
        : m.since.state !== 'OK' ? <div className="v010-unk">{m.since.state} — could not read incidents</div>
        : m.since.rows.length === 0 ? <div className="v010-line">No new incidents in this window</div>
        : m.since.rows.map(r => (
          <div className="v010-since" key={r.id}>
            {r.label ? <span className={`v010-pill ${r.label === 'MONITORING' ? 'info' : r.label === 'FIXED' ? 'ok' : 'warn'}`}>
              {r.label}</span> : <span />}
            <span>{r.text}</span>
            <span className="v010-since-t">{r.time}</span>
          </div>
        ))}
      <div className="v010-muted" style={{ marginTop: 4 }}>FIXED / UNPROVEN / MONITORING labels <NB /></div>
    </section>
  )

  const status = (
    <section className="v010-card" id="card-status" aria-labelledby="h-status">
      <div className="v010-card-hd">
        <h2 className="v010-h2" id="h-status">System status</h2>
        <button type="button" className="v010-link" onClick={onOpenDiag}>Diagnostics ›</button>
      </div>
      {m.status.map(r => (
        <div className="v010-srow" id={r.id} key={r.id} data-state={r.state}>
          <span className="v010-srow-n">{r.name}</span>
          <span className={pillClass(r.state)}>{r.state === 'LOADING' ? '…' : r.state}</span>
          <span className="v010-srow-v">{r.value} {r.needsBackend ? <NB /> : null}</span>
          {r.state !== 'OK' && r.state !== 'LOADING' && (
            <span className="v010-srow-c">Cause: <b>{r.cause || 'unknown'}</b> · Source: <b>{r.source || 'unknown'}</b> · Owner: <b>{r.owner || 'NEEDS BACKEND'}</b></span>
          )}
        </div>
      ))}
    </section>
  )

  const priorities = (
    <section className="v010-card" id="card-priorities" aria-labelledby="h-prio">
      <div className="v010-card-hd"><h2 className="v010-h2" id="h-prio">Today's priorities <NB /></h2></div>
      <div className="v010-muted">No server ranking in this build; see Action required above.</div>
    </section>
  )

  const diagEntry = (
    <section className="v010-card" id="card-diag-entry">
      <button type="button" className="v010-btn" onClick={onOpenDiag}>Open diagnostics (data freshness)</button>
    </section>
  )

  return (
    <div className="v010" data-page="home-v010">
      <header className="v010-head">
        <h1 className="v010-title">Command Center</h1>
        <span className="v010-time">{etTime(nowIso, true)}</span>
        <button type="button" id="chip-trade-ready" className="v010-chip-btn" onClick={onOpenWhy} aria-haspopup="dialog" data-testid="chip-trade-ready"
          data-verdict={m.tradeReady} title={m.tradeReadyCause}>
          Trade-ready: {m.tradeReady} ›
        </button>
        {m.tradeReadyServed ? null : <NB />}
        <span className="v010-meta" data-testid="chip-cause">{m.tradeReadyCause}</span>
        {m.p0.length > 0 && <span className="v010-pill bad">{m.p0.length} P0</span>}
      </header>
      <div className="v010-grid">
        <div className="v010-col">{action}{gates}{since}</div>
        <div className="v010-col">{status}{priorities}{diagEntry}</div>
      </div>
      <footer className="v010-foot">
        <Link className="v010-link" to="/home-classic" data-testid="classic-home-link">Classic Home</Link>
      </footer>
    </div>
  )
}
