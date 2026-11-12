import { useRef } from 'react'
import { useSheetA11y } from './WhySheet'
import './DiagnosticsDrawer.css'

export interface DiagRecord { widget: string; source: string; refreshRate: string; age: string; threshold: string; status: 'OK'|'STALE'|'UNKNOWN'|'TIMED OUT'|'WARN'|'NOT AVAILABLE'; failureMode: string; needsBackend?: boolean }

interface Props { open: boolean; onClose: () => void; records: DiagRecord[]; fetchedAt?: string; error?: string }

const NB_TITLE = 'Backend support not yet available'

function chipClass(s: DiagRecord['status']): string {
  if (s === 'OK') return 'ok'
  if (s === 'WARN' || s === 'STALE') return 'warn'
  if (s === 'UNKNOWN' || s === 'TIMED OUT') return 'bad'
  return ''
}

function fmtET(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET'
}

const Chip = ({ s }: { s: DiagRecord['status'] }) => <span className={`v010-diag-chip ${chipClass(s)}`}>{s}</span>

export default function DiagnosticsDrawer({ open, onClose, records, fetchedAt, error }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  useSheetA11y(open, onClose, dialogRef, closeRef)
  if (!open) return null

  return (
    <div className="v010-diag-scrim" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="v010-diag" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="v010-diag-title" id="sheet-diag">
        <div className="v010-diag-head">
          <h2 className="v010-diag-title" id="v010-diag-title">Diagnostics</h2>
          <button type="button" ref={closeRef} className="v010-diag-close" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {fetchedAt && <p className="v010-diag-sub">fetched {fmtET(fetchedAt)}</p>}
        {error && <p className="v010-diag-err" role="alert">{error}</p>}
        {records.length === 0 ? (
          <div className="v010-diag-empty">
            <span>No diagnostics available</span>
            <span className="v010-diag-tag" title={NB_TITLE}>NEEDS BACKEND</span>
          </div>
        ) : (
          <>
            <div className="v010-diag-cards">
              {records.map((r, i) => (
                <div className="v010-diag-card" key={`${r.widget}-${i}`}>
                  <dl>
                    <div className="v010-diag-row"><dt>Widget</dt><dd>{r.widget}</dd></div>
                    <div className="v010-diag-row"><dt>Source</dt><dd>{r.source}</dd></div>
                    <div className="v010-diag-row"><dt>Refresh rate</dt><dd>{r.refreshRate}</dd></div>
                    <div className="v010-diag-row"><dt>Age</dt><dd>{r.age}</dd></div>
                    <div className="v010-diag-row"><dt>Threshold</dt><dd>{r.threshold}</dd></div>
                    <div className="v010-diag-row"><dt>Status</dt><dd><Chip s={r.status} /></dd></div>
                    <div className="v010-diag-row"><dt>Failure mode</dt><dd>{r.failureMode}</dd></div>
                  </dl>
                  {r.needsBackend && <span className="v010-diag-tag" title={NB_TITLE}>NEEDS BACKEND</span>}
                </div>
              ))}
            </div>
            <div className="v010-diag-table-wrap">
              <table id="diag-table">
                <thead><tr>
                  <th>Widget</th><th>Source</th><th>Refresh rate</th><th>Age</th><th>Threshold</th><th>Status</th><th>Failure mode</th>
                </tr></thead>
                <tbody>
                  {records.map((r, i) => (
                    <tr key={`${r.widget}-${i}`}>
                      <td>{r.widget}{r.needsBackend && <> <span className="v010-diag-tag" title={NB_TITLE}>NB</span></>}</td>
                      <td>{r.source}</td><td>{r.refreshRate}</td><td>{r.age}</td><td>{r.threshold}</td>
                      <td><Chip s={r.status} /></td><td>{r.failureMode}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
