// Portfolio › Levels & valuation — a truthful partial page. Levels render per symbol from what the producer
// serves; valuation is stated as not wired. Props only (LevelsLive owns the GET).
import type { FormEvent } from 'react'
import type { LevelsState } from './levelsAdapter'

export interface LevelsPageProps {
  state: LevelsState
  draft: string
  onDraft: (v: string) => void
  onSubmit: () => void
  badInput?: boolean
}

const px = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

export function LevelsPage({ state, draft, onDraft, onSubmit, badInput }: LevelsPageProps) {
  const submit = (e: FormEvent) => { e.preventDefault(); onSubmit() }
  return (
    <section className="lv" aria-label="Levels and valuation">
      <header>
        <div className="eyebrow">PORTFOLIO · LEVELS &amp; VALUATION</div>
        <h2>Levels and valuation</h2>
        <p className="muted">Partial: the producer serves price levels one symbol at a time. There is no portfolio-wide levels read and no valuation read yet.</p>
      </header>

      <form onSubmit={submit} className="lv-form" data-form="symbol">
        <label>Symbol <input value={draft} onChange={e => onDraft(e.target.value)} aria-label="Symbol" maxLength={10} autoCapitalize="characters" /></label>{' '}
        <button type="submit">Read levels</button>
        {badInput && <span role="alert" className="muted"> Not a valid symbol. Nothing was requested.</span>}
      </form>

      {state.kind === 'idle' && <p className="muted" data-state="idle">Enter a symbol to read its levels. Nothing is requested until you do.</p>}
      {state.kind === 'loading' && <p className="muted" data-state="loading">Reading levels for {state.symbol}…</p>}
      {state.kind === 'error' && (
        <div className="note bad" role="alert" data-state="error">
          <strong>Levels for {state.symbol} could not be read.</strong> {state.message}.{' '}
          {state.lastGoodAt !== null ? `A last good read from ${state.lastGoodAt} exists but is not shown as current.` : 'No earlier read is held.'} No level is printed.
        </div>
      )}
      {state.kind === 'empty' && <p className="note blue" data-state="empty">No levels served for {state.symbol} (read {state.fetchedAt}). Absence is not a level of zero.</p>}
      {state.kind === 'ok' && (
        <div data-state="served">
          <p className="muted" data-clock="levels">
            {state.model.symbol} · read {state.fetchedAt}. The producer serves no computed-at time or cache age for these levels, so their freshness is Unknown.
          </p>
          {state.model.groups.map(g => (
            <div className="table-wrap" key={g.name}>
              <table><caption>{g.name}</caption>
                <thead><tr><th scope="col">Level</th><th scope="col">Price (USD)</th></tr></thead>
                <tbody>{g.levels.map((l, i) => <tr key={i}><td>{l.label}</td><td>{px.format(l.price)}</td></tr>)}</tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      <div className="note blue" data-missing="valuation">
        <strong>Valuation is not wired.</strong> The valuation-assessment@1 contract has no producer, so every holding row carries valuation: null.
        No valuation verdict is shown or inferred. Each missing contract and its owner is listed in MISSING-CONTRACTS.md.
      </div>
    </section>
  )
}
