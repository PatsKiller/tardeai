// Portfolio v002 (design/pages/portfolio/v002, operator-approved with amendments 2026-11-11) — main view.
// Phone order (390/412): header -> Action·Protection -> Validation gates -> Since last visit -> Portfolio status
// -> Holdings -> Details. Every block shows its age; UNKNOWN is never drawn as NO STOP; NEEDS BACKEND marks
// blocks with no production source in this build.
// 2026-11-14 (campaign CAMPAIGN-8H item 1): the four financial measures are drawn from cc-deepseek-7's
// PortfolioMeasures@v1 projection only (never computed here), stop coverage is drawn as covered / partial /
// uncovered / planned-only / exempt / unverifiable with resting vs held shares, and the risk score is an isolated
// pending decision (G7).
import { Link } from 'react-router-dom'
import {
  fmtAge, fmtET, fmtPct, fmtShares, fmtUsd, filterPositions, coverageCounts, coverageScopeRelation, exclusiveCoverage, snapshotFacts, gateEvidence, reviewPositions, scopeCoverage,
  basisCoverage, moveToday, unrealizedLine, weightLine, priceClock,
  STOP_OWNER, stopDeskHref,
  type CoverageCounts, type HoldingsFilter, type MeasuresModel, type P0Item, type PositionModel,
  type ProtectionModel, type Read, type HoldingsWire, type SinceVisitModel, type StatusRow, type VisitRecord, type MeasureKey,
} from '../../../lib/portfolioV002'
import './PortfolioV002.css'

export const NB = ({ short }: { short?: boolean }) => (
  <span className="pv2-nb" title="Backend support not yet available">{short ? 'NB' : 'NEEDS BACKEND'}</span>
)

export function stateClass(s: string): string {
  if (s === 'OK' || s === 'PROTECTED' || s === 'CLEAR' || s === 'MEASURED' || s === 'VERIFIED' || s === 'COVERED') return 'ok'
  if (s === 'WARN' || s === 'STALE' || s === 'MEDIUM' || s === 'EXPIRED' || s === 'PARTIAL' || s === 'UNVERIFIED' || s === 'PLANNED ONLY') return 'warn'
  if (s === 'GAP' || s === 'NO STOP' || s === 'TIMED OUT' || s === 'UNCOVERED') return 'bad'
  return 'neutral'
}
/** The row chip is the coverage chip: it says how much of the holding a resting stop covers, which the verdict alone
 *  does not (a PROTECTED row whose stop covers 200 of 300 shares is PARTIAL, drawn as such, verdict unchanged). */
const rowChip = (p: PositionModel) => p.coverage.chip
const rowChipClass = (p: PositionModel) =>
  p.coverage.category === 'COVERED' ? 'ok'
    : p.coverage.category === 'PARTIAL' ? 'warn'
      : p.coverage.category === 'UNCOVERED' || p.coverage.category === 'PLANNED_ONLY' ? 'bad' : 'neutral'

const MEASURE_SHORT: Record<MeasureKey, string> = {
  account_value: 'Value', price_move_estimate: 'Price move', account_value_change_1d: 'Change 1D', verified_daily_pnl: 'Verified P&L',
}
const FILTERS: [HoldingsFilter, string][] = [
  ['all', 'All'], ['covered', 'Covered'], ['unprotected', 'No broker stop'], ['partial', 'Partial'], ['planned', 'Planned'],
  ['unknown', 'Unknown'], ['exempt', 'Exempt'], ['under100', 'Under $100'],
]

export interface ViewProps {
  holdings: Read<HoldingsWire>; positions: PositionModel[]; prot: ProtectionModel; p0: P0Item[] | null; status: StatusRow[]
  measures: MeasuresModel; sinceVisit: SinceVisitModel; visitRecord: VisitRecord
  nowIso: string; filter: HoldingsFilter; account: string; shownCount: number; showAllAction: boolean
  onFilter: (f: HoldingsFilter) => void; onAccount: (a: string) => void; onShowMore: () => void; onShowAllAction: () => void
  onOpenWhy: () => void; onOpenDiag: () => void; onOpenAudit: () => void; onOpenPosition: (key: string) => void
  onOpenMeasures: () => void; onOpenMeasure: (key: MeasureKey) => void
  onOpenGates: () => void; onOpenSince: () => void; onOpenSync: () => void
  onOpenRisk: () => void; onExportCsv: () => void
}

const ACTION_LIMIT = 6
export const HOLDINGS_PAGE = 25

function verdictLabel(v: ProtectionModel['verdict']): string {
  return v === 'LOADING' ? 'reading…' : v
}

/** The header figure: the projection's account value when materialized; else the store total, labelled as such;
 *  else UNKNOWN. Never a page-side sum, and never one of two candidate totals picked silently.
 *  C2/C3 (REVIEW-CAMPAIGN8H-item1-...-cc-deepseek-6, F1/F2): the fallback's reason follows the state it was taken
 *  in, and when the figure is the store total the "store total · not reconciled" mark is VISIBLE text beside it at
 *  390/412 px — never a title= tooltip, which a phone cannot hover. */
function headerValue(measures: MeasuresModel, w: HoldingsWire | null): { text: string; title: string; mark: string | null } {
  const av = measures.measures.find(m => m.key === 'account_value')
  if (measures.state === 'LOADING') return { text: 'reading…', title: 'Reading holdings', mark: null }
  if (measures.state === 'PRESENT' && av && av.value != null) {
    return { text: `${fmtUsd(av.value)}`, title: `${av.label}: ${av.status} · PortfolioMeasures@v1 (broker store basis)`,
      mark: av.status === 'MEASURED' || av.status === 'VERIFIED' ? null : `${av.status} · not reconciled` }
  }
  const t = typeof w?.total_value === 'number' && Number.isFinite(w.total_value) ? w.total_value : null
  if (t != null) {
    // A8 (REVIEW-CAMPAIGN8H-item1-fix): only PRESENT/ABSENT can reach here — an unreadable read has no data, so there
    // is no store total either; the dead third arm is gone and the unreadable case is named below.
    const title = measures.state === 'PRESENT'
      ? 'The projection did not publish an account value; the store total is shown unreconciled.'
      : 'The four measures are not materialized in this read; the store total is shown unreconciled.'
    return { text: fmtUsd(t), title, mark: 'store total · not reconciled' }
  }
  // A8: when the holdings read itself failed, the header names the read error instead of a generic sentence.
  const unknownTitle = measures.state === 'UNREADABLE' && measures.reason
    ? `${measures.reason}; no account value was published`
    : 'No account value was published; the page does not compute one'
  return { text: 'value UNKNOWN', title: unknownTitle, mark: null }
}

export default function PortfolioV002View(props: ViewProps) {
  const { holdings, positions, prot, p0, status, measures, sinceVisit, nowIso, filter, account } = props
  const w = holdings.data
  const hv = headerValue(measures, w)
  const accounts = [...new Set(positions.map(p => p.account))].sort()
  const visible = filterPositions(positions, filter, account)
  const shown = visible.slice(0, props.shownCount)
  const action = props.showAllAction ? prot.action : prot.action.slice(0, ACTION_LIMIT)
  const cov: CoverageCounts = coverageCounts(positions)
  const excl = exclusiveCoverage(positions)
  const review = reviewPositions(positions)
  const gates = gateEvidence(prot, measures, positions, w)
  const scope = scopeCoverage(holdings, positions, { account, filtered: visible.length, rendered: shown.length })
  // R5c (b6): the SAME accessor Risk uses, over this read and this account filter — one computation, one sentence.
  // REVIEW O1 (cc-deepseek-4): the account count is over the account KEY, the same identity Risk passes
  // (`account_id ?? account`). The display label (`p.account`) never invents a second account.
  const snap = snapshotFacts(holdings.state === 'OK' ? w : null, positions.map(p => ({ account_id: p.accountKey })), account)
  const counts = {
    covered: excl.covered,
    unprotected: excl.noStop,
    partial: excl.partial,
    unknown: excl.unknown,
    under100: positions.filter(p => p.underFloor).length,
    planned: positions.filter(p => p.planned != null || p.coverage.category === 'PLANNED_ONLY').length,
    exempt: cov.exempt,
    // The review set overlaps the four exclusive tiles (it is the P0 list); the header chip draws it, not a filter chip.
    review: review.length,
  }
  const verdictCls = prot.verdict === 'OK' ? 'ok' : prot.verdict === 'GAP' ? 'bad' : prot.verdict === 'WARN' ? 'warn' : 'neutral'

  return (
    <div className="pv2" data-testid="portfolio-v002">
      {/* Header: value · time ET · Protection chip -> why · P0 · Gates · Ask */}
      <header className="pv2-hdr">
        <div className="pv2-hdr-main">
          <div className="pv2-hdr-t">
            <h1 className="pv2-title">Portfolio</h1>
            <span className="pv2-age" data-testid="hdr-value" title={hv.title}>· {hv.text}</span>
            {hv.mark && <span className="pv2-age" data-testid="hdr-mark">· {hv.mark}</span>}
            <span className="pv2-age">· {fmtET(nowIso, true)} ET</span>
          </div>
          <div className="pv2-chips">
            <button type="button" className={`pv2-chip-btn ${verdictCls}`} id="chip-protection" data-testid="chip-protection"
              onClick={props.onOpenWhy} aria-label={`Protection: ${verdictLabel(prot.verdict)}. Open why`}>
              Protection: {verdictLabel(prot.verdict)} ›
            </button>
            {/* PR-006: the badge names its population — counted positions that need stop review — and opens
                exactly those rows. Incidents and health counts are different populations and say so elsewhere. */}
            <button type="button" className={`pv2-chip ${p0 == null ? 'neutral' : review.length ? 'bad' : 'neutral'}`} data-testid="chip-p0"
              onClick={p0 == null ? undefined : () => props.onFilter('review')} disabled={p0 == null}
              title={p0 == null
                ? 'The holdings read failed; the review population cannot be counted (never 0)'
                : 'Counted positions with no resting stop in a good read, or the last-known gap kept while its read is stale. Opens those rows.'}>
              {p0 == null ? 'review count ?' : `${review.length} position${review.length === 1 ? '' : 's'} ${review.length === 1 ? 'needs' : 'need'} stop review`}
            </button>
            {/* PR-006: a published count-mismatch finding is NOT a position. It keeps its own labelled chip and
                opens the gate evidence; it never inflates the position review population. */}
            {p0 != null && p0.some(i => i.category === 'Position Count Mismatch') && (
              <button type="button" className="pv2-chip warn" data-testid="chip-count-mismatch" onClick={props.onOpenGates}
                title="A published position-count finding. It is a store reconciliation issue, not a position: open the gate evidence.">count mismatch · evidence ›</button>
            )}
            <span className="pv2-chip neutral" data-testid="chip-gates">Gates — <NB short /></span>
            {measures.state === 'PRESENT' && measures.dayUnverified && (
              <span className="pv2-chip warn" data-testid="chip-unverified" title="Verified daily P&L has no stored reconciliation">UNVERIFIED</span>
            )}
          </div>
        </div>
        {/* LQ-2752 (operator 2026-11-12 21:56 ET): the classic page stays one tap away until v002 is validated. */}
        <Link className="pv2-classic" to="/portfolio-classic" data-testid="classic-portfolio-link">Classic Portfolio</Link>
        <Link className="pv2-ask" to="/cio" aria-label="Ask the CIO">Ask</Link>
      </header>

      {/* PR-002: the denominators, in one line. Every figure is a served field or a count of the rows this read
          drew; a fact the read does not publish is named (snapshot id), never omitted or invented. */}
      <p className="pv2-scope" data-testid="scope-line">
        <b>Scope</b> · {scope.accounts} · source rows {scope.sourceRows ?? 'not published'}
        {scope.cashRows != null ? ` · cash ${scope.cashRows}` : ''}{scope.nonCashRows != null ? ` · non-cash ${scope.nonCashRows}` : ''}
        {scope.unpricedRows != null ? ` · unpriced ${scope.unpricedRows}` : ''} · quoteable {scope.quoteable}
        {' · '}drawn {scope.drawn} · after filter {scope.filtered} · rendered {scope.rendered}
        {' · '}counted here {scope.countedHere} ({scope.countedScope})
        {scope.blockHeadline != null ? ` · count block ${scope.blockHeadline}${scope.blockScope ? ` (${scope.blockScope})` : ''}` : ''}
        {` · `}<span data-testid="snapshot-line">{snap.line}</span>
        {scope.missing.length ? ` · not published: ${scope.missing.join(', ')}` : ''}
        {scope.mismatches.length ? ` · differs: ${scope.mismatches.join('; ')}` : ''}
        <button type="button" className="pv2-lnk" data-testid="scope-diag" onClick={props.onOpenDiag}>Diagnostics ›</button>
      </p>

      <div className="pv2-grid">
        <div className="pv2-col">
          {/* Action · Protection */}
          {prot.verdict === 'OK' ? (
            <div className="pv2-collapsed" id="card-protect" data-testid="card-protect">
              <span className="pv2-chip ok">CLEAR</span>
              <span className="pv2-txt">{prot.protectedN} of {prot.counted} protected</span>
              <span className="pv2-age pv2-push">read {fmtET(prot.oldestRead)} · {prot.brokers.length} broker{prot.brokers.length === 1 ? '' : 's'} with counted positions</span>
            </div>
          ) : (
            <section className="pv2-blk" id="card-protect" data-testid="card-protect">
              <div className="pv2-blk-h">
                <h2 className="pv2-h2">Action · Protection</h2>
                <span className="pv2-age">{prot.oldestRead ? `oldest stop read ${fmtET(prot.oldestRead)} · ${fmtAge(Date.parse(nowIso) - Date.parse(prot.oldestRead))}` : holdings.state === 'OK' ? 'no resting stop read' : ''}</span>
              </div>
              {prot.verdict === 'LOADING' || prot.verdict === 'TIMED OUT' || (prot.verdict === 'UNKNOWN' && !prot.counted) ? (
                <div className={`pv2-unk ${prot.verdict === 'TIMED OUT' ? 'bad' : ''}`} data-testid="protect-unread">
                  {prot.verdict === 'LOADING' ? 'Reading holdings…' : `Protection ${prot.verdict}: ${prot.cause || 'holdings not read'}. Nothing here is drawn as NO STOP.`}
                </div>
              ) : (
                <>
                  {/* PR-001: four MUTUALLY EXCLUSIVE counted-position states (exclusiveCoverage), each opening
                      exactly the rows it counts. "Partial" is its own state, so a partially covered position is
                      never read as fully covered; the sum is the counted population. The broker verdict above is
                      unchanged — this splits the wording, never the evidence. */}
                  <div className="pv2-tiles" id="prot-tiles" data-counted={excl.counted}>
                    <button type="button" className="pv2-tile ok" onClick={() => props.onFilter('covered')}
                      aria-label={`${excl.covered} fully covered positions. Show them`}><span className="k">Fully covered</span><span className="n">{excl.covered}</span></button>
                    <button type="button" className="pv2-tile warn" onClick={() => props.onFilter('partial')}
                      aria-label={`${excl.partial} partially covered positions. Show them`}><span className="k">Partial</span><span className="n">{excl.partial}</span></button>
                    <button type="button" className="pv2-tile bad" onClick={() => props.onFilter('unprotected')}
                      aria-label={`${excl.noStop} counted positions with no broker stop. Show them`}><span className="k">No broker stop</span><span className="n">{excl.noStop}</span></button>
                    <button type="button" className="pv2-tile unk" onClick={() => props.onFilter('unknown')}
                      aria-label={`${excl.unknown} positions with unverifiable protection. Show them`}><span className="k">Unknown</span><span className="n">{excl.unknown}</span></button>
                  </div>
                  <p className="pv2-muted" data-testid="prot-tiles-sum">{excl.covered + excl.partial + excl.noStop + excl.unknown} of {excl.counted} counted positions (non-cash, at or above $100){excl.complete ? '' : ' · the four states do not add to the counted total'}</p>
                  {/* Coverage categories (campaign 2026-11-14): counted by the display classifier; the verdict above
                      stays the backend's. Partial is called out because a tile cannot show "200 of 300".
                      R5b #2 (2026-11-14): these six categories count EVERY row the page drew (30 live), while the
                      tiles above count only `counted` rows (11 live). Both were right; the line did not say so and
                      read as one sentence beside the tiles. `coverageScopeRelation` now names both populations and
                      how they relate, from the same fields, so the two can never be drawn as one denominator. */}
                  <button type="button" className="pv2-covline" data-testid="prot-coverage" onClick={props.onOpenWhy}
                    aria-label="Stop coverage detail">
                    {`Coverage · ${coverageScopeRelation(cov)}: `}<b>{cov.covered}</b> covered · <b>{cov.partial}</b> partial · <b>{cov.uncovered}</b> uncovered · <b>{cov.planned}</b> planned-only · <b>{cov.exempt}</b> exempt · <b>{cov.unverifiable}</b> unverifiable
                    {cov.restingShares != null && cov.heldShares != null && <> · resting <b>{fmtShares(cov.restingShares)}</b> of <b>{fmtShares(cov.heldShares)}</b>{cov.totalsComplete ? ' held shares' : ' published held shares (some rows publish no quantity)'}</>}
                    <span aria-hidden="true"> ›</span>
                  </button>
                  <div className="pv2-pt-h" aria-hidden="true"><span>Symbol</span><span>Stop status</span><span>Last verified</span><span className="r">Action</span></div>
                  <div id="prot-rows">
                    {groupByCause(action).map(g => (
                      <div key={g.cause}>
                        {g.rows.map(p => (
                          <div className="pv2-prow" key={p.key} data-testid="prot-row">
                            <button type="button" className="pv2-prow-main" onClick={() => props.onOpenPosition(p.key)} aria-label={`${p.symbol} ${rowChip(p)}. Open detail`}>
                              <span className="sym">{p.symbol}</span>
                              <span><span className={`pv2-chip ${rowChipClass(p)}`}>{rowChip(p)}</span></span>
                              {/* PR-003: an impossible future time is unverified evidence, never a verification
                                label; a row with no published read time says so instead of "never" (which read
                                as "a read happened and found nothing"). */}
                            <span className="ver">{p.verifiedAtInvalid ? 'read time invalid · not verified'
                              : p.verifiedAt ? fmtET(p.verifiedAt, true) : 'no read time published'} · {p.account}
                              {p.planned && <span className="pv2-plan" data-testid="prot-plan">{` · plan ${p.planned.price != null ? `$${p.planned.price.toFixed(2)}` : 'price not recorded'} (not rested)`}</span>}</span>
                            </button>
                            {p.protection === 'GAP' || p.protection === 'WARN' || p.coverage.category === 'PARTIAL'
                              ? <Link className="pv2-act" to={stopDeskHref(p)} title={`Stop desk · ${p.symbol} · ${p.accountKey} · ${p.broker}`}>Place stop ›</Link>
                              : <button type="button" className="pv2-act" onClick={() => props.onOpenPosition(p.key)}>Verify ›</button>}
                          </div>
                        ))}
                        <div className="pv2-own">Cause: <b>{g.cause}</b> · Source: <b>{g.source}</b> · Owner: <b>{g.owner}</b></div>
                      </div>
                    ))}
                    {prot.action.length > ACTION_LIMIT && !props.showAllAction && (
                      <button type="button" className="pv2-more" onClick={props.onShowAllAction}>{prot.action.length - ACTION_LIMIT} more ›</button>
                    )}
                  </div>
                </>
              )}
            </section>
          )}

          {/* Validation gates — no gate store in this build. The four gates the design expects are named with the
              evidence this page can see; the box is never ticked and no gate is ever counted as open or closed. */}
          <section className="pv2-blk" id="card-gates" data-testid="card-gates">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Validation gates <NB /></h2><span className="pv2-age">result not available</span></div>
            <p className="pv2-muted">Gate store not served for Portfolio (scope=portfolio, LQ-2141). A gate is never reported by a count here.</p>
            {gates.map(g => (
              <div className="pv2-gate" key={g.gate} data-testid="gate-row">
                <span className="pv2-gbox" aria-hidden="true" />
                <div>
                  <div className="pv2-g1">{g.gate}</div>
                  <div className="pv2-g2">Blocks: <b>{g.blocks}</b>{g.blocksTrading ? ' · BLOCKS TRADING' : ''} · needs {g.threshold}</div>
                  <div className="pv2-g2">In this read: {g.pageEvidence}</div>
                </div>
              </div>
            ))}
            <p className="pv2-muted">Each gate's evidence above is this page's observation, not a gate result. The served result needs the gate store (LQ-2141).</p>
            <button type="button" className="pv2-lnk" onClick={props.onOpenGates} data-testid="open-gates">Gate evidence ›</button>
          </section>

          {/* Since your last visit — the anchor is served (LQ-2467); the change list needs the change store (LQ-2143) */}
          <section className="pv2-blk" id="card-since" data-testid="card-since">
            <div className="pv2-blk-h">
              <h2 className="pv2-h2">Since your last visit <NB /></h2>
              <span className="pv2-age">{sinceVisit.status === 'RECORDED' ? fmtET(sinceVisit.seenAt) : sinceVisit.status.toLowerCase().replace('_', ' ')}</span>
            </div>
            <p className="pv2-muted" data-testid="since-window">{sinceVisit.windowText}</p>
            <p className="pv2-muted" data-testid="since-detail">{sinceVisit.status === 'RECORDED'
              ? `Last visit ${fmtET(sinceVisit.seenAt, true)}${sinceVisit.device ? ` · ${sinceVisit.device}` : ''} · ${sinceVisit.previousSeenAt ? `previous ${fmtET(sinceVisit.previousSeenAt, true)}` : 'no previous visit recorded'}`
              : sinceVisit.reason || 'the previous-visit record is not available'}</p>
            <p className="pv2-muted">The change list needs the change store (LQ-2143). <NB short /></p>
            <button type="button" className="pv2-lnk" onClick={props.onOpenSince} data-testid="open-since">Last visit &amp; window ›</button>
          </section>

          {/* Portfolio status: the four measures, then the system rows */}
          <section className="pv2-blk" id="card-status" data-testid="card-status">
            <div className="pv2-blk-h">
              <h2 className="pv2-h2">Portfolio status <span className="pv2-age pv2-plain">· {measures.asOf ? fmtET(measures.asOf) : holdings.at ? fmtET(holdings.at) : '—'}</span></h2>
              <span className="pv2-chips">
                {measures.state !== 'PRESENT' && <NB short />}
                {measures.state === 'PRESENT' && measures.dayUnverified && <span className="pv2-chip warn">UNVERIFIED</span>}
                <button type="button" className="pv2-lnk" onClick={props.onOpenDiag} data-testid="open-diag">Diagnostics ›</button>
              </span>
            </div>
            {measures.measures.map(m => (
              <button type="button" className="pv2-measure" key={m.key} data-testid="measure-row" onClick={() => props.onOpenMeasure(m.key)}
                title={`${m.label} — open its reconciliation`}>
                <span className="n">{MEASURE_SHORT[m.key]}</span>
                <span><span className={`pv2-chip ${m.statusClass}`}>{m.status}</span></span>
                <span className="sub">{m.text}{m.estimate ? ` · Finviz estimate ${fmtUsd(m.estimate.value)}${m.estimate.delta != null ? ` (${fmtUsd(m.estimate.delta, true)})` : ''}, separate` : ''}</span>
              </button>
            ))}
            <p className="pv2-muted" data-testid="measures-note">
              {measures.state === 'PRESENT'
                ? `PortfolioMeasures@v1 · basis ${measures.basis || 'not named'} · Finviz marks are a separate estimate and never added to a “today” figure.${measures.dayUnverified ? ' Verified daily P&L has no stored reconciliation, so it stays UNKNOWN.' : ''}`
                : measures.reason || 'the four measures are not published in this read'}
            </p>
            {status.map(r => r.id === 'row-risk' ? (
              <div className="pv2-st" id={r.id} key={r.id} data-testid={r.id}>
                <div className="s1">
                  <span className="n">{r.name}</span>
                  <span><span className="pv2-chip warn">PENDING</span></span>
                  <span className="sub">pending decision: no approved risk-score definition (G7){' '}
                    <button type="button" className="pv2-lnk" onClick={props.onOpenRisk} data-testid="risk-why">Why ›</button>
                  </span>
                </div>
                <div className="pv2-own">RISK-SCORE-SPEC-20261111 is PROPOSED; nothing is scored, no letter, no colour, no number.</div>
              </div>
            ) : (
              <div className="pv2-st" id={r.id} key={r.id} data-testid={r.id}>
                <div className="s1">
                  <span className="n">{r.name}</span>
                  <span><span className={`pv2-chip ${stateClass(r.state)}`}>{r.state === 'LOADING' ? '…' : r.state}</span></span>
                  <span className="sub">{r.text} {r.needsBackend && <NB short />}
                    {r.href && <Link className="pv2-lnk" to={r.href} data-testid={`${r.id}-evidence`}> Open the incidents ›</Link>}
                  </span>
                </div>
                {r.cause && <div className="pv2-own">{r.cause}</div>}
              </div>
            ))}
          </section>
        </div>

        <div className="pv2-col">
          {/* Holdings */}
          <section className="pv2-blk" id="card-holdings" data-testid="card-holdings">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Holdings · {holdings.state === 'OK' ? positions.length : '—'}</h2><span className="pv2-age">by value</span></div>
            {/* OBS-P1 (operator 11:15 ET): cost-basis coverage is a header fact — a reader must know how much of the
                book's P&L is drawn before reading a single row. Cash rows are exempt and excluded from the population. */}
            {holdings.state === 'OK' && (
              <p className="pv2-muted" data-testid="basis-coverage">{basisCoverage(positions).line}</p>
            )}
            {holdings.state !== 'OK' ? (
              <div className="pv2-unk">{holdings.state === 'LOADING' ? 'Reading holdings…' : `Holdings ${holdings.state}: ${holdings.error || ''}`}</div>
            ) : (
              <>
                <label className="pv2-sel">
                  <span className="pv2-sr">Account</span>
                  <select value={account} onChange={e => props.onAccount(e.target.value)} data-testid="acct-select">
                    <option value="all">All accounts ({accounts.length})</option>
                    {accounts.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
                <div className="pv2-fchips" role="group" aria-label="Filter holdings">
                  {FILTERS.map(([k, label]) => {
                    const n = k === 'all' ? null : counts[k]
                    return (
                      <button type="button" key={k} className={`pv2-fchip ${filter === k ? 'on' : ''}`} aria-pressed={filter === k} onClick={() => props.onFilter(k)}>
                        {label}{n != null ? ` ${n}` : ''}
                      </button>
                    )
                  })}
                </div>
                <div className="pv2-hl-h" aria-hidden="true"><span>Symbol</span><span className="r">Shares</span><span className="r">Value</span><span>Protection</span><span>Risk</span></div>
                {shown.map(p => {
                  // OBS-P1: every financial fact is drawn from the read and labelled — the mark with its source and
                  // clock, the session PRICE MOVE (never "P&L"), the weight only if published, and unrealized P&L only
                  // on a recorded basis. A fact the read does not publish is named; nothing is blank and nothing is 0.
                  const mv = moveToday(p), pnl = p.isCash ? { text: 'cash row · no unrealized P&L', known: true, cls: null } : unrealizedLine(p.basis), wl = weightLine(p), pc = priceClock(p.raw, w)
                  return (
                    <button type="button" className="pv2-hrow" key={p.key} onClick={() => props.onOpenPosition(p.key)} data-testid="holding-row" data-symbol={p.symbol}>
                      <span className="c1"><b>{p.symbol}</b><span className="s2">{p.account}{p.underFloor ? ' · under $100' : ''}{p.coverage.category === 'PARTIAL' ? ` · stop ${fmtShares(p.coverage.restingShares)}/${fmtShares(p.coverage.heldShares)}` : ''}</span></span>
                      <span className="num">{fmtShares(p.shares)}</span>
                      <span className="num">{fmtUsd(p.value)}</span>
                      <span><span className={`pv2-chip ${rowChipClass(p)}`}>{p.isCash && p.protection === 'EXEMPT' ? 'CASH' : rowChip(p)}</span></span>
                      <span className="risk" title="Risk score: pending decision (G7)">—</span>
                      <span className="facts">
                        <span data-testid="row-quote">{p.isCash ? 'cash balance · no mark' : p.price == null ? 'mark not published in this read' : `mark $${p.price.toFixed(2)} · ${p.priceSource || 'source not named'} · ${pc.line}`}{p.priceStale ? <span className="pv2-stale-mark"> · STALE</span> : null}</span>
                        <span className={wl.known ? '' : 'pv2-unk-fact'} data-testid="row-weight">{wl.text}</span>
                        <span className={mv.cls ? `pv2-move ${mv.cls}` : 'pv2-move'} data-testid="row-move">{mv.text}</span>
                        <span className={pnl.cls ? `pv2-pnl ${pnl.cls}` : 'pv2-pnl'} data-testid="row-pnl">{pnl.text}</span>
                      </span>
                    </button>
                  )
                })}
                {visible.length === 0 && <p className="pv2-muted">No holdings match this filter.</p>}
                {visible.length > shown.length && (
                  <button type="button" className="pv2-more" onClick={props.onShowMore} data-testid="show-more">
                    Showing {shown.length} of {visible.length} · show {Math.min(HOLDINGS_PAGE, visible.length - shown.length)} more ›
                  </button>
                )}
                <div className="pv2-blk-h">
                  <p className="pv2-muted">Risk column: pending decision <NB short /> · tap a row for its full-screen detail</p>
                  <button type="button" className="pv2-lnk" onClick={props.onExportCsv} data-testid="export-csv"
                    disabled={visible.length === 0} aria-label="Export the filtered holdings as CSV">Export CSV</button>
                </div>
              </>
            )}
          </section>

          {/* Details: replaces the 8 tabs (R3); each opens a full-screen sheet or a desk */}
          <section className="pv2-blk" id="card-details" data-testid="card-details">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Details</h2></div>
            <button type="button" className="pv2-det" onClick={props.onOpenAudit} data-testid="open-audit"><span>Audit state</span><span>›</span></button>
            <button type="button" className="pv2-det" onClick={props.onOpenMeasures} data-testid="open-measures"><span>The numbers · reconciliation</span><span>›</span></button>
            <button type="button" className="pv2-det" onClick={props.onOpenSync} data-testid="open-sync"><span>Sync &amp; export</span><span>›</span></button>
            <button type="button" className="pv2-det" onClick={props.onOpenRisk} data-testid="open-risk"><span>Risk score · pending decision</span><span>›</span></button>
            <Link className="pv2-det" to="/retirement" data-testid="lnk-retirement"><span>Retirement</span><span>›</span></Link>
            <Link className="pv2-det" to="/risk" data-testid="lnk-risk"><span>Risk desk</span><span>›</span></Link>
            <Link className="pv2-det" to="/defense" data-testid="lnk-defense"><span>Defense</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio/re-entry" data-testid="lnk-reentry"><span>Re-entry</span><span>›</span></Link>
            <Link className="pv2-det" to="/rotation" data-testid="lnk-rotation"><span>Rotation review</span><span>›</span></Link>
            <Link className="pv2-det" to="/redeploy" data-testid="lnk-redeploy"><span>Redeploy desk</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Allocation"><span>Allocation · Look-through</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Returns"><span>Returns · Dividends · Forecast</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Tax"><span>Tax lots</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Stop+Management"><span>Stop management desk</span><span>›</span></Link>
            <div className="pv2-det pv2-retired" data-testid="retired-fidelity"><span>Fidelity GTC stop sync</span><span className="pv2-chip neutral">Retired</span></div>
            <Link className="pv2-det" to="/portfolio-classic" data-testid="classic-link"><span>Classic Portfolio page (sync, export, stop audit)</span><span>›</span></Link>
          </section>
        </div>
      </div>
    </div>
  )
}

function groupByCause(rows: PositionModel[]): { cause: string; source: string; owner: string; rows: PositionModel[] }[] {
  const out: { cause: string; source: string; owner: string; rows: PositionModel[] }[] = []
  for (const p of rows) {
    const cause = p.cause || 'Protection Unknown'
    const last = out[out.length - 1]
    if (last && last.cause === cause) last.rows.push(p)
    else out.push({ cause, source: 'stop store', owner: STOP_OWNER, rows: [p] })
  }
  return out
}
