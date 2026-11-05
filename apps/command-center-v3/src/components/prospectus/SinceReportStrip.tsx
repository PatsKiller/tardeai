/** "Since this report" strip (operator 2026-10-27, Prospectus NEWS methodology): at the top of the report, what
 *  happened after it was written — relevant headlines and filings with a material / not-material badge, the price
 *  move since the report, stop events, and the status of each (queued for the next run, or the CIO note). Read-only,
 *  from GET /api/v2/prospectus/{sym} `since_report` (no model call, no DB in the request path). Phone first: one
 *  column, every tap target ≥ 44px; collapsed to the first 3 items on a phone. Research only — never an order. */
import { useState } from 'react'
import { impactTone, whenEt, type SinceReport } from '../../lib/prospectusModel'

function pct(v: number | null | undefined): string | null {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return null
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

export default function SinceReportStrip({ since, phone }: { since?: SinceReport | null; phone: boolean }) {
  const [open, setOpen] = useState(false)
  if (!since) return null
  const items = since.items ?? []
  const move = pct(since.price?.move_pct)
  const stops = since.stop_events ?? []
  const hidden = Object.entries(since.hidden ?? {}).filter(([, n]) => n > 0)
  const limit = phone && !open ? 3 : items.length
  const empty = !items.length && !move && !stops.length
  return (
    <section className="psp-card psp-since" data-testid="prospectus-since" aria-label="Since this report">
      <div className="psp-since-head">
        <h2 className="psp-card-title">Since this report</h2>
        {move && (
          <span className={`psp-chip psp-tone-${Number(since.price?.move_pct) >= 0 ? 'success' : 'danger'}`} data-testid="prospectus-since-move">
            Price {move}{since.price?.as_of ? ` to ${whenEt(since.price.as_of)}` : ''}
          </span>
        )}
      </div>
      {since.rewrite?.status && (
        <p className="psp-since-rewrite" data-testid="prospectus-since-rewrite">Rewrite {since.rewrite.status}{since.rewrite.reason ? ` (${since.rewrite.reason.replace(/_/g, ' ')})` : ''}.</p>
      )}
      {stops.map((s, i) => (
        <p key={`stop-${i}`} className="psp-since-stop psp-tone-danger" data-testid="prospectus-since-stop">
          Stop levels changed since the report{s.status ? ` — ${s.status}` : ''}.
        </p>
      ))}
      {empty && (
        <p className="psp-since-empty" data-testid="prospectus-since-empty">
          Nothing relevant since this report{since.checked_at ? ` (checked ${whenEt(since.checked_at)})` : since.next_window?.time ? ` — news is checked at the ${since.next_window.time} run` : ''}.
        </p>
      )}
      {items.length > 0 && (
        <ul className="psp-since-list">
          {items.slice(0, limit).map(it => {
            const tone = it.note ? impactTone(it.note.impact) : 'neutral'
            return (
              <li key={it.id} className="psp-since-item" data-testid="prospectus-since-item">
                <div className="psp-since-row">
                  <span className={`psp-chip psp-since-badge psp-tone-${it.material ? 'warning' : 'neutral'}`} data-testid="prospectus-since-badge">{it.material ? 'Material' : 'Not material'}</span>
                  <span className="psp-since-when">{whenEt(it.at)}{it.source ? ` · ${it.source}` : ''}</span>
                </div>
                {it.url
                  ? <a className="psp-since-title" href={it.url} target="_blank" rel="noopener noreferrer">{it.title}</a>
                  : <span className="psp-since-title">{it.title}</span>}
                <div className={`psp-since-status psp-tone-${tone}`} data-testid="prospectus-since-status">
                  {it.status}{it.note?.which_breaker ? ` (${it.note.which_breaker})` : ''}{it.note?.one_line ? ` — ${it.note.one_line}` : ''}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {phone && items.length > 3 && (
        <button type="button" className="psp-btn psp-since-more" onClick={() => setOpen(o => !o)} aria-expanded={open} data-testid="prospectus-since-more">
          {open ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
      {hidden.length > 0 && (
        <p className="psp-since-hidden" data-testid="prospectus-since-hidden">
          Hidden: {hidden.map(([k, n]) => `${n} ${k === 'collision' ? 'about another company with this ticker' : 'duplicate copies'}`).join(' · ')}.
        </p>
      )}
      <p className="psp-gaps">Research only — not an order. CIO notes are checked at the 07:00 and 17:45 ET runs.</p>
    </section>
  )
}
