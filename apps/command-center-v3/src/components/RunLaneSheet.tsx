// LQ-20261107-611 · "Run a lane" full-screen sheet (Ops → Controls). Every n8n allowlisted lane, searchable, with [Dry run] and
// [Live run] (live disabled with its reason), plus [Run all dry] / [Run all live] that queue one run per lane through ONE Ops
// Controls request. The confirm / step-up step is the page's existing change flow; this sheet reads GET only and presses nothing.
import { useEffect, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import { TOKENS, TYPE } from '../lib/watchTokens'
import { RADIUS } from '../lib/designTokens'
import type { OpsRequest } from '../lib/opsControls'
import {
  KIND_ALL_DRY, KIND_ALL_LIVE, KIND_CANCEL, KIND_DRY, KIND_LIVE, LANES_PATH, batchPath, canCancelQueued, filterLanes,
  progressSummary, receiptLine, unwrapEnvelope, type BatchProgress, type LanesView,
} from '../lib/runLaneSheet'

export type StartRun = (kind: string, params: Record<string, unknown>, title: string, onDone?: (r: OpsRequest) => void) => void

const btn = (on: boolean, danger = false): CSSProperties => ({
  fontSize: TYPE.base, fontWeight: 600, borderRadius: RADIUS.sm, padding: '6px 10px', minHeight: 36, whiteSpace: 'nowrap',
  cursor: on ? 'pointer' : 'not-allowed', opacity: on ? 1 : 0.55, color: danger ? TOKENS.danger : TOKENS.text[1],
  background: TOKENS.bg[2], border: `1px solid ${danger ? TOKENS.danger : TOKENS.border}`,
})
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: '4px 0', overflowWrap: 'anywhere' }

function Progress({ batchId, start }: { batchId: string; start: StartRun }) {
  const api = useApi<unknown>(batchPath(batchId), 3_000)
  const p = unwrapEnvelope<BatchProgress>(api.data, 'counts')
  return <section data-testid="run-lane-progress" aria-label="Run progress" style={{ display: 'grid', gap: 6 }}>
    <h2 style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[0] }}>Progress</h2>
    <p style={muted} data-testid="run-lane-progress-summary">{progressSummary(p)}{p?.finished ? ' — finished' : ''}</p>
    {canCancelQueued(p) ? <button type="button" data-testid="run-lane-cancel-queued" style={btn(true, true)}
      onClick={() => start(KIND_CANCEL, { batch_id: batchId }, 'Cancel the queued runs of this batch')}>Cancel queued ({p!.counts.queued})</button> : null}
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}>
      {(p?.runs || []).map(r => <li key={r.run_id} style={{ ...muted, color: TOKENS.text[1] }}>
        <b style={{ color: TOKENS.text[0] }}>{r.lane_id}</b> · {r.mode} — {receiptLine(r)}{r.finished_at ? ` · ${r.finished_at}` : ''}
      </li>)}
    </ul>
  </section>
}

export default function RunLaneSheet({ onClose, start, initialBatch }: { onClose: () => void; start: StartRun; initialBatch?: string | null }) {
  const api = useApi<unknown>(LANES_PATH, 20_000)
  const view = unwrapEnvelope<LanesView>(api.data, 'lanes')
  const [q, setQ] = useState('')
  const [batch, setBatch] = useState<string | null>(initialBatch ?? null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const rows = filterLanes(view?.lanes, q)
  const go = (kind: string, params: Record<string, unknown>, title: string) =>
    start(kind, params, title, r => setBatch(r.request_id))
  const ra = view?.run_all
  return <div role="dialog" aria-modal="true" aria-label="Run a lane" data-testid="run-lane-sheet"
    style={{ position: 'fixed', inset: 0, zIndex: 900, background: TOKENS.bg[0], overflowY: 'auto', overflowX: 'hidden', padding: 16, display: 'grid', gap: 12, alignContent: 'start', boxSizing: 'border-box', maxWidth: '100vw' }}>
    <header style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', minWidth: 0 }}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Run a lane</h1>
      <button type="button" onClick={onClose} style={btn(true)} data-testid="run-lane-close">Close</button>
    </header>
    <p style={muted}>Queues a run into the same executor n8n uses, under the operator-manual caller. A dry run changes nothing durable. A live run needs your passkey and a typed phrase. {view?.note || 'Undo is not supported.'}</p>
    {api.error && !view ? <p role="alert" style={{ ...muted, color: TOKENS.warning }}>UNAVAILABLE — {String(api.error)}</p> : null}
    {view?.live_list_missing ? <p role="alert" style={{ ...muted, color: TOKENS.warning }}>The relay live list is missing, so every live run is refused.</p> : null}

    {ra ? <section aria-label="Run all" data-testid="run-lane-all" style={{ display: 'grid', gap: 6, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 10 }}>
      <h2 style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[0] }}>Run all</h2>
      <p style={muted}>One request queues one run per lane, one after another (the executor's worker cap and per-lane locks decide the order). A second Run all inside {Math.round(ra.cooldown_s / 60)} minutes is refused.</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" data-testid="run-lane-all-dry" style={btn(ra.dry_count > 0)} disabled={ra.dry_count === 0}
          onClick={() => go(KIND_ALL_DRY, { mode: 'dry_run' }, `Run all ${ra.dry_count} lanes (dry run)`)}>Run all dry ({ra.dry_count})</button>
        <button type="button" data-testid="run-lane-all-live" style={btn(ra.live_count > 0, true)} disabled={ra.live_count === 0}
          onClick={() => go(KIND_ALL_LIVE, { mode: 'live' }, `Run all ${ra.live_count} safe lanes (LIVE)`)}>Run all live ({ra.live_count}, passkey)</button>
      </div>
      <details data-testid="run-lane-all-excluded">
        <summary style={muted}>{ra.live_excluded.length} lanes are left out of Run all live, each with its reason</summary>
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {ra.live_excluded.map(x => <li key={x.lane_id} style={muted}><b style={{ color: TOKENS.text[0] }}>{x.lane_id}</b>: {x.reasons.join('; ')}</li>)}
        </ul>
      </details>
    </section> : null}

    {batch ? <Progress batchId={batch} start={start} /> : null}

    <label style={{ display: 'grid', gap: 4, fontSize: TYPE.sm, color: TOKENS.text[2] }}>Search lanes
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="lane or family" data-testid="run-lane-search" aria-label="Search lanes"
        style={{ fontSize: TYPE.base, color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '6px 8px', minHeight: 36, minWidth: 0 }} />
    </label>
    <p style={muted} data-testid="run-lane-count">{rows.length} of {view?.lanes?.length ?? 0} lanes</p>
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }} data-testid="run-lane-list">
      {rows.map(r => <li key={r.lane_id} data-testid="run-lane-row" style={{ border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.md, padding: 10, display: 'grid', gap: 6, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
          <b style={{ color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{r.lane_id}</b>
          <ChipRow><Chip tone="neutral">{r.family}</Chip>{r.schedule ? <Chip tone="neutral">{r.schedule}</Chip> : null}</ChipRow>
        </div>
        <p style={muted}>Last: {receiptLine(r.last_receipt)}{r.last_receipt?.finished_at ? ` · ${r.last_receipt.finished_at}` : ''}</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" style={btn(r.dry.available)} disabled={!r.dry.available} title={r.dry.reason || 'Queue a dry run'}
            onClick={() => go(KIND_DRY, { lane_id: r.lane_id, mode: 'dry_run' }, `Dry run ${r.lane_id}`)}>Dry run</button>
          <button type="button" style={btn(r.live.available, true)} disabled={!r.live.available} title={r.live.reason || 'Queue a live run (passkey)'}
            onClick={() => go(KIND_LIVE, { lane_id: r.lane_id, mode: 'live' }, `LIVE run ${r.lane_id}`)}>Live run</button>
        </div>
        {!r.dry.available ? <p style={muted}>Dry run unavailable: {r.dry.reason}</p> : null}
        {!r.live.available ? <p style={muted}>Live run unavailable: {r.live.reason}</p> : null}
      </li>)}
    </ul>
  </div>
}
