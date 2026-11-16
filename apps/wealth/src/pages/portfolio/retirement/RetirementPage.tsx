// Portfolio › Retirement — a truthful partial page. It renders what /api/v2/retirement serves, with the clocks
// the response carries, and names every contract that is missing (see ../MISSING-CONTRACTS.md). Props only: no
// fetch here (RetirementLive owns the two GETs).
import type { ReactNode } from 'react'
import type { Field, Retirement, Research, Section } from './retirementAdapter'

export interface RetirementPageProps {
  retirement: Section<Retirement>
  research: Section<Research>
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

function F<T>({ f, fmt }: { f: Field<T>; fmt?: (v: T) => string }) {
  if (f.state === 'unknown') return <span className="rt-unknown" title={f.reason}>Unknown <small>({f.reason})</small></span>
  return <>{fmt ? fmt(f.value) : String(f.value)}</>
}
const money = (v: number) => usd.format(v)

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <tr><th scope="row">{k}</th><td>{children}</td></tr>
}

function Err({ what, s }: { what: string; s: Extract<Section<unknown>, { kind: 'error' }> }) {
  return (
    <div className="note bad" role="alert" data-state="error">
      <strong>{what} could not be read.</strong> {s.message}.{' '}
      {s.lastGoodAt !== null ? `A last good read from ${s.lastGoodAt} exists but is not shown as current.` : 'No earlier read is held.'} No figure is
      printed for this section.
    </div>
  )
}

function Missing({ items }: { items: string[] }) {
  return (
    <div className="note blue" data-missing="contracts">
      <strong>Not served, so not shown.</strong>
      <ul>{items.map(i => <li key={i}>{i}</li>)}</ul>
      Each missing item and its owner is listed in MISSING-CONTRACTS.md.
    </div>
  )
}

export function RetirementPage({ retirement, research }: RetirementPageProps) {
  return (
    <section className="rt" aria-label="Retirement">
      <header>
        <div className="eyebrow">PORTFOLIO · RETIREMENT</div>
        <h2>Retirement roadmap</h2>
        <p className="muted">Partial: only fields the producer serves are shown; producer defaults and zero-fills are Unknown. Not advice and not a projection.</p>
      </header>

      {retirement.kind === 'loading' && <p className="muted" data-state="loading">Reading the retirement roadmap…</p>}
      {retirement.kind === 'error' && <Err what="The retirement roadmap" s={retirement} />}
      {retirement.kind === 'ok' && (() => {
        const m = retirement.model
        return (
          <div data-state="served">
            <p className="muted" data-clock="roadmap">
              Roadmap as of <F f={m.asOf} /> · built <F f={m.generated} />
              {m.ageDays !== null ? ` (${m.ageDays} d old)` : ''} · read {retirement.fetchedAt}. No staleness verdict is served, so freshness is not asserted.
            </p>
            <div className="table-wrap"><table><caption>Accounts as stored in the roadmap</caption><tbody>
              <Row k="Current age"><F f={m.currentAge} /></Row>
              <Row k="Portfolio total (holdings, or roadmap as fallback; which one is not served)"><F f={m.accounts.total} fmt={money} /></Row>
              <Row k="Roth"><F f={m.accounts.roth} fmt={money} /></Row>
              <Row k="Traditional"><F f={m.accounts.traditional} fmt={money} /></Row>
              <Row k="Taxable"><F f={m.accounts.taxable} fmt={money} /></Row>
              <Row k="Holdings total (stored state)"><F f={m.canonicalTotal} fmt={money} /></Row>
            </tbody></table></div>
            <div className="table-wrap"><table><caption>Loan</caption><tbody>
              <Row k="Balance"><F f={m.loan.balance} fmt={money} /></Row>
              <Row k="Deadline"><F f={m.loan.deadline} /></Row>
              <Row k="Days remaining (as stored at build, not recounted)"><F f={m.loan.storedDaysRemaining} /></Row>
              <Row k="Monthly to pay off"><F f={m.loan.monthlyToPayoff} fmt={money} /></Row>
            </tbody></table></div>
            <div className="table-wrap"><table><caption>Golden window (as served; producer defaults withheld)</caption><tbody>
              <Row k="Start age"><F f={m.goldenWindow.startAge} /></Row>
              <Row k="End age"><F f={m.goldenWindow.endAge} /></Row>
              <Row k="Years available"><F f={m.goldenWindow.yearsAvailable} /></Row>
              <Row k="Annual conversion input"><F f={m.goldenWindow.annualConversion} fmt={money} /></Row>
              <Row k="Bracket ceiling"><F f={m.goldenWindow.bracketCeiling} /></Row>
            </tbody></table></div>
            <div className="table-wrap"><table><caption>Dividend income (stored calendar; its own clock is not served here)</caption><tbody>
              <Row k="Annual"><F f={m.dividend.annualTotal} fmt={money} /></Row>
              <Row k="Monthly average"><F f={m.dividend.monthlyAvg} fmt={money} /></Row>
              <Row k="Yield on the served total"><F f={m.dividend.yieldPct} fmt={v => `${v}%`} /></Row>
            </tbody></table></div>
            <h3>Milestones</h3>
            {m.timeline.length === 0 ? <p className="muted">No milestones served.</p> : (
              <div className="table-wrap"><table><thead><tr><th scope="col">Year</th><th scope="col">Age</th><th scope="col">Milestone</th></tr></thead><tbody>
                {m.timeline.map((t, i) => <tr key={i}><td><F f={t.year} /></td><td><F f={t.age} /></td><td><F f={t.milestone} /></td></tr>)}
              </tbody></table></div>
            )}
            <Missing items={m.withheld} />
          </div>
        )
      })()}

      <h3>Planning research</h3>
      {research.kind === 'loading' && <p className="muted" data-state="loading">Reading planning research…</p>}
      {research.kind === 'error' && <Err what="Planning research" s={research} />}
      {research.kind === 'ok' && (
        <div data-state="served" data-section="research">
          <p className="muted">
            Research notes only{research.model.advisoryOnly ? ' (the producer marks them advisory)' : ''}, not a plan. Built <F f={research.model.asOf} /> at request time,
            which is a read stamp, not a source clock; each note carries its own time.
          </p>
          {research.model.themes.length === 0 ? <p className="muted">No themes served.</p> : research.model.themes.map(t => (
            <details key={t.theme}><summary>{t.theme} · {t.count ?? 'count not served'}</summary>
              <ul>{t.items.map((i, k) => <li key={k}>{i.topic} · {i.status ?? 'status not served'} · confidence {i.confidence ?? 'not served'} · {i.sourceCount === null ? 'sources not served' : `${i.sourceCount} sources`} · {i.at ?? 'time not served'}</li>)}</ul>
            </details>
          ))}
        </div>
      )}
    </section>
  )
}
