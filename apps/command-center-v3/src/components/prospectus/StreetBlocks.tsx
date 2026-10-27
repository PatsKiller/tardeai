/** Ticker Prospectus — the institutional ("Street") blocks and the validation badge (operator 2026-10-27: "does it also
 *  have analyst reviews and what are analysts saying along with catalysts? … something I can use on the Goldman desk,
 *  Citadel, anywhere" and "We don't need to see [citations] on the frontend … If it's been validated, that's good.").
 *
 *  The backend computes every number (scripts/lib/prospectus/street.py) and shapes the tables once
 *  (tables.street_tables → presentation.street), so the page, the HTML, the PDF and the Word file say the same thing.
 *  Desktop: a card per table. Phone (≤820): each row becomes a small stacked card — no sideways scrolling. */
import { useState } from 'react'
import {
  isBlankValue, streetRows, validationOf, validationTone, whenEt,
  type ProspectusDoc, type StreetTable, type Validation,
} from '../../lib/prospectusModel'

const TONE: Record<string, string> = {
  analyst_coverage: 'info', analyst_targets_trend: 'info', analyst_actions: 'info', estimates: 'success',
  estimates_history: 'success', catalyst_calendar: 'warning', catalyst_history: 'warning', positioning: 'ai',
  valuation_history: 'neutral', fundamentals_xbrl: 'neutral',
}

function Cell({ v }: { v: string }) {
  if (/^https:\/\//.test(v)) {
    return <a className="psp-link" href={v} target="_blank" rel="noopener noreferrer">{/sec\.gov/.test(v) ? 'EDGAR' : 'open'}</a>
  }
  return <>{v}</>
}

function Kpis({ kpis }: { kpis?: [string, string][] }) {
  const shown = (kpis ?? []).filter(([, v]) => !isBlankValue(v) && !/^n\/a\b/i.test(String(v)))
  if (!shown.length) return null
  return (
    <div className="psp-st-kpis">
      {shown.map(([k, v]) => <div key={k} className="psp-st-kpi"><span>{k}</span><b>{v}</b></div>)}
    </div>
  )
}

export function StreetTableCard({ t, phone }: { t: StreetTable; phone: boolean }) {
  const { rows, absent } = streetRows(t)
  const [open, setOpen] = useState(false)
  const many = phone && rows.length > 6
  const shown = many && !open ? rows.slice(0, 6) : rows
  return (
    <section className="psp-card psp-st" data-testid={`prospectus-street-${t.id}`} aria-label={t.title}>
      <h2 className={`psp-card-title psp-tone-${TONE[t.id] ?? 'neutral'}`}>{t.title}</h2>
      <Kpis kpis={t.kpis} />
      {shown.length > 0 && (phone ? (
        <div className="psp-st-rows">
          {shown.map((r, i) => (
            <div key={i} className={`psp-st-row${t.highlight === i ? ' psp-st-hl' : ''}`} data-testid="prospectus-street-row">
              <div className="psp-st-row-h"><Cell v={String(r[0] ?? '')} /></div>
              {r.slice(1).map((c, k) => (isBlankValue(c) || c === '' ? null : (
                <div key={k} className="psp-st-row-kv"><span>{t.columns[k + 1]}</span><span><Cell v={String(c)} /></span></div>
              )))}
            </div>
          ))}
          {many && (
            <button type="button" className="psp-btn psp-st-more" onClick={() => setOpen(o => !o)} aria-expanded={open}>
              {open ? 'Show fewer' : `Show all ${rows.length}`}
            </button>
          )}
        </div>
      ) : (
        <div className="psp-table-wrap">
          <table className={`psp-table${t.columns[0] === 'Measure' ? ' psp-table-left' : ''}`}>
            <thead><tr>{t.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i} className={t.highlight === i ? 'psp-st-hl' : undefined}>
                  {r.map((c, k) => <td key={k}><Cell v={String(c ?? '')} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {absent.length > 0 && <p className="psp-notin" data-testid="prospectus-not-in-data">Not in our data: {absent.join(', ')}</p>}
      {t.note && <p className="psp-st-note">{t.note}</p>}
    </section>
  )
}

/** All Street tables, in reading order; desktop pairs the shorter ones two-up. */
export function StreetBlocks({ tables, phone, only }: { tables: StreetTable[]; phone: boolean; only?: string[] }) {
  const list = only ? tables.filter(t => only.includes(t.id)) : tables
  if (!list.length) return null
  return (
    <div className={phone ? 'psp-st-stack' : 'psp-st-grid'} data-testid="prospectus-street">
      {list.map(t => <StreetTableCard key={t.id} t={t} phone={phone} />)}
    </div>
  )
}

/** ONE validation statement near the header; tapping opens a compact summary (counts by source type and anything not
 *  validated) — never a citation list. */
export function ValidationBadge({ doc }: { doc: ProspectusDoc | null | undefined }) {
  const v: Validation | null = validationOf(doc)
  const [open, setOpen] = useState(false)
  if (!v) return null
  const tone = validationTone(v)
  const bySource = Object.entries(v.by_source ?? {})
  return (
    <div className="psp-valid" data-testid="prospectus-validation" data-status={v.status}>
      <button type="button" className={`psp-valid-btn psp-tone-${tone}`} aria-expanded={open} onClick={() => setOpen(o => !o)}
        data-testid="prospectus-validation-badge">
        {v.line}
      </button>
      {open && (
        <div className="psp-valid-panel" data-testid="prospectus-validation-panel" role="region" aria-label="Validation summary">
          <p className="psp-muted">{v.figures ?? 0} figures in this report were checked against {v.sources ?? 0} source types
            {v.as_of ? ` (${whenEt(v.as_of)})` : ''}.</p>
          {bySource.length > 0 && (
            <ul className="psp-valid-list">{bySource.map(([k, n]) => <li key={k}><span>{k}</span><b>{n}</b></li>)}</ul>
          )}
          {((v.unreliable ?? []).length > 0 || (v.reasons ?? []).length > 0) && (
            <>
              <p className="psp-valid-h">Not validated</p>
              <ul className="psp-valid-list psp-valid-bad">
                {(v.unreliable ?? []).map(u => <li key={u.id} data-fact-id={u.id}><span>{u.label}</span><b>{u.reason}</b></li>)}
                {(v.reasons ?? []).filter(r => !(v.unreliable ?? []).some(u => r.toLowerCase().includes(u.reason))).map(r => <li key={r}><span>{r}</span></li>)}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}
