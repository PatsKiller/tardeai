// Performance presenter: source-owned values and intervals, optional page-owned selection callbacks.
// The source owns every number, actual interval, membership fact and clock; no financial derivation here.
import { AsOf } from '../../components/StateView'
import { Note, Panel, Tag } from '../../components/primitives'
import {
  PERFORMANCE_WINDOWS, accountCoverageText, clockHasEvidence, coverageText, measureWarnings, methodText, missingMeasure,
  RESIDUAL_FLAG, contractLines, numberClass, numberIsKnown, numberText, pageState, performanceAccountLabel,
} from './performanceView'
import type { PerformanceMeasure, PerformancePageProps, PerformanceWindow } from './performanceView'
import { signedMoney, signedPct } from './format'
import './semantic.css'

// Scoped layout additions keep the approved shell/panel typography and semantic tokens intact.
// Cards reflow rather than imposing a seven-column table on a phone or narrow desktop workspace.
const LAYOUT = `
.performance-page { min-width:0; display:grid; gap:14px; overflow-wrap:anywhere; }
.performance-page .performance-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,17rem),1fr)); gap:10px; }
.performance-page .performance-window { min-width:0; padding:12px; border:1px solid var(--line); border-radius:8px; background:var(--panel); }
.performance-page .performance-window h3 { margin-bottom:10px; }
.performance-page .performance-measure + .performance-measure { border-top:1px solid var(--line); margin-top:12px; padding-top:12px; }
.performance-page .performance-measure > p.money-unknown { font-size:11px; }
.performance-page .performance-method { font-size:12px; margin:0 0 7px; }
.performance-page .performance-values { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin:8px 0; }
.performance-page .performance-values dt { color:var(--muted); font-size:11px; }
.performance-page .performance-values dd { margin:3px 0 0; font-size:18px; font-weight:650; font-variant-numeric:tabular-nums; }
.performance-page .performance-values dd.money-unknown { font-size:13px; }
.performance-page .performance-provenance { font-size:11px; color:var(--muted); font-style:italic; line-height:1.5; }
.performance-page .performance-provenance > div { margin:3px 0; }
.performance-page details { margin-top:8px; font-size:11px; color:var(--muted); }
.performance-page summary { cursor:pointer; padding:7px 0; min-height:32px; color:var(--blue); }
.performance-page summary:focus-visible { outline:2px solid var(--gold); outline-offset:3px; }
.performance-page .panel-head { flex-wrap:wrap; }
.performance-page .panel-head > div { min-width:0; }
@media(max-width:600px) { .performance-page .performance-grid { grid-template-columns:minmax(0,1fr); } }
`

function Measure({ measure, window, scope, allowHouseholdEstimate = false }: {
  measure: PerformanceMeasure
  window: PerformanceWindow
  scope: string
  allowHouseholdEstimate?: boolean
}) {
  // Also refuse at runtime: untyped callers must not turn a household residual into an account figure.
  if (measure.method === 'household-estimate' && !allowHouseholdEstimate) {
    return <p className="money-unknown">Unknown — account measure not served — owner: {measure.owner}</p>
  }
  const warnings = measureWarnings(measure)
  // Review B1 (2026-11-16): a withheld cell (eligibility unknown/ineligible, refused anchor, ...) prints no figure at all,
  // so the household-residual allocation and the raw NAV change appear only when the measure itself is shown.
  const measureShown = numberIsKnown(measure.amount)
  const lines = contractLines(measure.contract, measure.startAt, measure.endAt, !measureShown)
  const reasons = [...new Set([measure.amount, measure.percent].filter(number => !numberIsKnown(number))
    .map(number => numberText(number, 'amount', measure.owner)))]
  return <div className="performance-measure" data-method={measure.method}>
    <p className="performance-method"><strong>{methodText(measure)}</strong></p>
    {warnings.length > 0 && <Tag tone="warn" title={warnings.join(' · ')}>! {warnings.join(' · ')}</Tag>}
    <dl className="performance-values">
      <div><dt>Change (USD)</dt><dd className={numberClass(measure.amount, measure)}>{numberIsKnown(measure.amount) ? numberText(measure.amount, 'amount', measure.owner) : 'Unknown'}</dd></div>
      <div><dt>Change (%)</dt><dd className={numberClass(measure.percent, measure)}>{numberIsKnown(measure.percent) ? numberText(measure.percent, 'percent', measure.owner) : 'Unknown'}</dd></div>
    </dl>
    {reasons.length > 0 && <p className="money-unknown">{reasons.join(' · ')}</p>}
    {measure.contract?.residualAllocated === true && !measureShown && <div className="note warn" data-residual-allocated="withheld">! {RESIDUAL_FLAG}; the allocated figure is withheld with this measure.</div>}
    {measure.contract?.residualAllocated === true && measureShown && <div className="note warn" data-residual-allocated="true">! {RESIDUAL_FLAG}.
      {' '}Allocated {numberIsKnown({ value: measure.contract.allocatedAmount, unknownReason: null }) ? signedMoney(measure.contract.allocatedAmount) : 'unknown'}
      {' · '}{numberIsKnown({ value: measure.contract.allocatedPercent, unknownReason: null }) ? signedPct(measure.contract.allocatedPercent) : 'unknown'}
      {' '}beside raw NAV change {numberText(measure.amount, 'amount', measure.owner)} (includes deposits and withdrawals).</div>}
    <p className="performance-provenance" data-contract-line="true">{lines.slice(0, 2).join(' · ')}</p>
    <details><summary>Method &amp; interval details</summary><div className="performance-provenance" aria-label="Measure provenance">
      <div>Scope: {scope} · Coverage: {coverageText(measure)}</div>
      <div>Source: {measure.source || 'not served'} · owner: {measure.owner}</div>
      {measure.clocks.length === 0 ? <div>Source clock and age unknown — owner: {measure.owner}</div> : measure.clocks.map((clock, index) =>
        <div key={index}>{clock.label}: <AsOf asOf={clock.asOf}
          ageHours={clock.ageSeconds !== null && Number.isFinite(clock.ageSeconds) && clock.ageSeconds >= 0 ? clock.ageSeconds / 3600 : null} />
          {(clock.ageSeconds === null || !Number.isFinite(clock.ageSeconds) || clock.ageSeconds < 0) && ' · age unknown'}
          {' · '}{clock.freshness === 'fresh' && clockHasEvidence(clock)
            ? 'source reports fresh' : clock.freshness === 'stale' ? 'stale' : 'freshness unknown'}
        </div>)}
      {window === 'Latest session' && <div>{measure.attributedSession
        ? `Attributed session: ${measure.attributedSession}` : 'Attributed session unknown'}</div>}
    </div>
      <p>{window === 'YTD' ? 'Calendar year to date; pin clock/source shown above when supplied.'
        : window === 'Latest session' ? 'Holdings price movement is an estimate, not reconciled investment profit.'
          : 'Rolling window; actual snapshot bounds may cover a shorter interval.'}</p>
      <p>Actual start: {measure.startAt ?? 'unknown'} · Actual end: {measure.endAt ?? 'not served'}</p>
      {lines.map((l, i) => <p key={i}>{l}</p>)}
      {measure.method === 'household-estimate' && <p>{measure.methodNote} Household only; not individual account profit.</p>}
      {measure.note && <p>{measure.note}</p>}
    </details>
  </div>
}

export function PerformancePage(props: PerformancePageProps) {
  const state = pageState(props)
  const windows = props.selectedPeriod === undefined ? PERFORMANCE_WINDOWS : props.selectedPeriod === null ? [] : [props.selectedPeriod]
  return <div className="performance-page" data-performance-state={state}>
    <style>{LAYOUT}</style>
    <div className="row-between" style={{ flexWrap: 'wrap', gap: 10 }}>
      <h2 style={{ fontSize: 16 }}>Performance evidence</h2>
      {props.selectedPeriod !== undefined && <label>Period <select aria-label="Performance period"
        value={props.selectedPeriod ?? ''} disabled={!props.availablePeriods?.length}
        onChange={e => props.onPeriodChange?.(e.target.value as PerformanceWindow)}>
        {!props.availablePeriods?.length && <option value="">No periods served</option>}
        {props.availablePeriods?.map(period => <option key={period} value={period}>{period}</option>)}
      </select></label>}
    </div>
    {state === 'empty' ? <Note>No accounts in this view. Choose an account scope with available history.
      No household total is substituted for an empty account selection.</Note> : <>
      {state === 'unknown' ? <Note>All performance measures are unknown. Read the source gap below; {props.gapOwner} owns missing evidence.</Note>
        : state === 'partial' ? <div className="note warn">! Partial performance view — some measures are estimated, stale or unavailable.
          Open evidence for the source gap and actual interval.</div>
          : <Note>Supplied measures are shown below. Compare actual intervals and flow treatment before interpreting a change as investment performance.</Note>}
      {props.accountCoverage && <Note>{accountCoverageText(props.accountCoverage)}</Note>}
      {props.showHousehold !== false && <Panel title="Household" sub="Source-supplied scope; membership is not inferred from these rows.">
        <div className="performance-grid">{windows.map(window => {
          const period = props.household[window]
          return <article className="performance-window" key={window}>
            <h3>{window}</h3>
            <Measure window={window} scope="Household" measure={period?.observation ?? missingMeasure(window, props.gapOwner)} />
            {period?.estimate && <Measure window={window} scope="Household only" measure={period.estimate} allowHouseholdEstimate />}
          </article>
        })}</div>
      </Panel>}
      <div data-performance-accounts="true">{props.accounts.map((account, index) => {
        const label = performanceAccountLabel(account)
        return <div key={account.key} data-performance-account={index}>
          <Panel title={label} sub={account.scopeNote}>
            <div className="performance-grid">{windows.map(window =>
              <article className="performance-window" key={window}>
                <h3>{window}</h3>
                <Measure window={window} scope={label} measure={account.periods[window] ?? missingMeasure(window, props.gapOwner)} />
              </article>)}
            </div>
          </Panel>
        </div>
      })}</div>
    </>}
  </div>
}
