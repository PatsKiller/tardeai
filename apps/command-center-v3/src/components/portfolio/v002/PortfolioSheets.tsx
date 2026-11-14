// Portfolio v002 full-screen sheets: why-protection (GAP / WARN / UNKNOWN / OK, with the six coverage categories),
// position detail with per-field source/writer/age and resting-vs-held shares, the four-measure reconciliation,
// gate evidence, last visit & window, sync & export, the pending risk decision, and audit state.
// Same shell and classes as Home v010's WhySheet (reused, not edited).
import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import '../../home/v010' // loads the Home v010 WhySheet styles this shell reuses
import {
  fmtET, fmtUsd, fmtShares, positionFields, coverageCounts, gateEvidence, stopDeskHref, RISK_SCORE, STOP_OWNER, UNVERIFIED_NOTE,
  type AuditCategory, type GateEvidence, type HoldingsWire, type MeasureKey, type MeasuresModel, type PositionModel, type ProtectionModel,
  type SinceVisitModel, type VisitRecord,
} from '../../../lib/portfolioV002'
import { NB, stateClass } from './PortfolioV002View'

function Sheet({ open, onClose, title, id, children }: { open: boolean; onClose: () => void; title: string; id: string; children: ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    closeRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="v010-why-scrim" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="v010-why" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} id={id} data-testid={id}>
        <div className="v010-why-head">
          <h2 className="v010-why-title" id={`${id}-title`}>{title}</h2>
          <button type="button" ref={closeRef} className="v010-why-close" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

const Chip = ({ s, label }: { s: string; label?: string }) => <span className={`v010-why-chip ${stateClass(s) === 'neutral' ? '' : stateClass(s) === 'ok' ? 'ok' : stateClass(s) === 'warn' ? 'warn' : 'bad'}`}>{label ?? s}</span>

export function ProtectionWhySheet({ open, onClose, prot, positions, nowIso, onGoTo }: {
  open: boolean; onClose: () => void; prot: ProtectionModel; positions: PositionModel[]; nowIso: string; onGoTo: (id: string) => void
}) {
  const v = prot.verdict
  const title = v === 'OK' ? 'Is everything protected?' : 'Why is protection not OK?'
  const notProtected = (prot.gap ?? 0) + (prot.warn ?? 0) + (prot.unknown ?? 0)
  const gap = prot.action.filter(p => p.protection === 'GAP')
  const warn = prot.action.filter(p => p.protection === 'WARN')
  const unk = prot.action.filter(p => p.protection === 'UNKNOWN')
  const causes = [...new Set(unk.map(p => p.cause || 'Protection Unknown'))]
  const cov = coverageCounts(positions)
  const partial = positions.filter(p => p.coverage.category === 'PARTIAL')
  const planned = positions.filter(p => p.coverage.category === 'PLANNED_ONLY')
  return (
    <Sheet open={open} onClose={onClose} title={title} id="sheet-why">
      <p className="v010-why-note" data-testid="why-verdict">
        <Chip s={v} label={`Protection: ${v}`} />{' '}
        {prot.counted != null ? (v === 'OK' ? `${prot.protectedN} of ${prot.counted}` : `${notProtected} of ${prot.counted} not protected`) : prot.cause}
        <br /><span className="v010-why-age">computed in this page {fmtET(nowIso)} ET from each row's backend verdict · served rollup (G2)</span> <NB short />
      </p>
      {v === 'OK' ? (
        <ul className="v010-why-list">
          {prot.brokers.map(b => (
            <li className="v010-why-item" key={b.broker}>
              <div className="v010-why-txt"><span className="v010-why-cat">{b.broker}</span>
                <span className="v010-why-detail">oldest read {fmtET(b.oldest, true)} · {b.protectedN} of {b.counted} resting</span></div>
              <Chip s="OK" />
            </li>
          ))}
          <li className="v010-why-item"><div className="v010-why-txt"><span className="v010-why-cat">Per-broker read state (G3)</span>
            <span className="v010-why-detail">not served in this build; rows with an unread broker are UNKNOWN</span><NB /></div><Chip s="UNKNOWN" label="NOT AVAILABLE" /></li>
        </ul>
      ) : (
        <ol className="v010-why-list">
          {whyItems(prot, gap, planned, warn, unk, causes).map((it, i) => (
            <WhyItem key={it.cat} n={i + 1} {...it} onGo={it.go ? () => onGoTo('card-protect') : undefined} />
          ))}
        </ol>
      )}
      <h3 className="pv2-sheet-h">Coverage categories</h3>
      <p className="v010-why-note" data-testid="why-coverage">
        <b>{cov.covered}</b> covered · <b>{cov.partial}</b> partial · <b>{cov.uncovered}</b> uncovered · <b>{cov.planned}</b> planned-only ·{' '}
        <b>{cov.exempt}</b> exempt · <b>{cov.unverifiable}</b> unverifiable
        {cov.restingShares != null && cov.heldShares != null
          ? (cov.totalsComplete
            ? <> · resting stops cover <b>{fmtShares(cov.restingShares)}</b> of <b>{fmtShares(cov.heldShares)}</b> held shares.</>
            : <> · resting stops cover <b>{fmtShares(cov.restingShares)}</b> of <b>{fmtShares(cov.heldShares)}</b> <b>published</b> held shares — some rows publish no quantity, so this is a partial sum, not a total.</>)
          : ' · the resting and held share totals are not both published in this read.'}
      </p>
      {partial.length > 0 && (
        <p className="v010-why-note">
          Partial: {partial.map(p => `${p.symbol} ${fmtShares(p.coverage.restingShares)} of ${fmtShares(p.coverage.heldShares)}`).join(', ')}. The
          backend verdict stays PROTECTED; a short stop is drawn, not hidden, and is never counted as full coverage.
        </p>
      )}
      <h3 className="pv2-sheet-h">Counted</h3>
      <p className="v010-why-note">{prot.counted ?? '—'} positions at or above $100. {prot.listedNotCounted ?? '—'} under $100 are listed, not counted; {prot.exempt ?? '—'} cash / money-market / exempt rows are not counted.</p>
      <h3 className="pv2-sheet-h">Rule</h3>
      <p className="v010-why-note">OK only when every counted position, broker and stop source was read and every counted position has a verified resting stop (a pending-activation GTC stop counts). GAP when a good read shows no resting stop. An expired stop is WARN. Any unread broker or source gives UNKNOWN, never OK.</p>
    </Sheet>
  )
}

type WhyRow = { cat: string; chip: string; detail: string; src: string; go?: string; nb?: boolean }

/** The items in one pass so the numbered prefix is the item's position in the list: a planned-only row is its own
 *  item, never a second "1.". */
function whyItems(prot: ProtectionModel, gap: PositionModel[], planned: PositionModel[], warn: PositionModel[],
  unk: PositionModel[], causes: string[]): WhyRow[] {
  const out: WhyRow[] = []
  const go = 'Go to the positions'
  const unprotected = gap.filter(p => p.coverage.category !== 'PLANNED_ONLY')
  if (unprotected.length > 0) {
    out.push({ cat: `Unprotected position · ${unprotected.length}`, chip: 'GAP',
      detail: `${unprotected.map(p => p.symbol).join(', ')}: a good read shows no resting stop.`,
      src: `Source: stop store · Owner: ${STOP_OWNER}`, go })
  }
  if (planned.length > 0) {
    out.push({ cat: `Planned only · ${planned.length}`, chip: 'PLANNED ONLY',
      detail: `${planned.map(p => p.symbol).join(', ')}: the level exists only as a plan at the broker; no resting order protects the position.`,
      src: `Source: stop store · Owner: ${STOP_OWNER}`, go })
  }
  if (warn.length > 0) {
    out.push({ cat: `Expired stop · ${warn.length}`, chip: 'WARN',
      detail: `${warn.map(p => p.symbol).join(', ')}: protection existed but the stop expired (never OK).`,
      src: `Source: stop store · Owner: ${STOP_OWNER}`, go })
  }
  if (unk.length > 0) {
    out.push({ cat: `Protection unknown · ${unk.length}`, chip: 'UNKNOWN',
      detail: `${unk.map(p => p.symbol).join(', ')}: protection cannot be verified. Never drawn as NO STOP.`,
      src: `Cause: ${causes.join(', ')} · Source: stop store · Owner: ${STOP_OWNER}`, go })
  }
  if (prot.counted == null) {
    out.push({ cat: `Holdings ${prot.verdict}`, chip: prot.verdict, detail: prot.cause || 'The holdings read did not complete.',
      src: 'Source: /api/v2/portfolio/holdings' })
  }
  out.push({ cat: 'Open validation gate', chip: 'UNKNOWN', detail: 'Gate store not served for Portfolio.',
    src: 'Source: gate store · Owner: validation lane', nb: true })
  return out
}

function WhyItem({ n, cat, chip, detail, src, go, onGo, nb }: { n: number; cat: string; chip: string; detail: string; src: string; go?: string; onGo?: () => void; nb?: boolean }) {
  return (
    <li className="v010-why-item" data-testid="why-item">
      <div className="v010-why-txt">
        <span className="v010-why-cat">{n}. {cat} {nb && <NB short />}</span>
        <span className="v010-why-detail">{detail}</span>
        <span className="v010-why-age">{src}</span>
      </div>
      <Chip s={chip} />
      {go && onGo && <button type="button" className="v010-why-go" onClick={onGo}>{go} ›</button>}
    </li>
  )
}

export function PositionSheet({ pos, onClose, holdings, nowIso }: { pos: PositionModel | null; onClose: () => void; holdings: HoldingsWire | null; nowIso: string }) {
  const open = pos != null
  const fields = pos ? positionFields(pos, holdings, Date.parse(nowIso)) : []
  return (
    <Sheet open={open} onClose={onClose} title={pos ? `${pos.symbol} · ${pos.account}` : ''} id="sheet-pos">
      {pos && (
        <>
          <p className="v010-why-note"><b>{fmtUsd(pos.value)}</b> {pos.dayUsd == null ? 'day change UNKNOWN' : `${fmtUsd(pos.dayUsd, true)} today`}</p>
          <p className="v010-why-note" data-testid="pos-protection">
            <Chip s={pos.protection === 'GAP' ? 'GAP' : pos.protection === 'WARN' ? 'WARN' : pos.protection === 'PROTECTED' ? 'OK' : 'UNKNOWN'} label={pos.chip} />{' '}
            {pos.reason}{pos.cause ? ` · Cause: ${pos.cause}` : ''}{!pos.counted ? ' · listed, not counted' : ''}
          </p>
          <p className="v010-why-note" data-testid="pos-coverage">
            <Chip s={pos.coverage.category === 'PLANNED_ONLY' ? 'PLANNED ONLY' : pos.coverage.category} label={pos.coverage.label} />{' '}
            {pos.coverage.restingShares != null && pos.coverage.heldShares != null
              ? `resting stop ${fmtShares(pos.coverage.restingShares)} of ${fmtShares(pos.coverage.heldShares)} held shares · `
              : 'resting and held quantities not both published · '}
            {pos.coverage.detail}
          </p>
          <p className="v010-why-note">
            Position identity: <b>{pos.accountKey}</b> · <b>{pos.broker}</b> · <b>{pos.symbol}</b>
            {pos.raw.stop_order_id || pos.raw.order_id ? <> · order <b>{pos.raw.stop_order_id || pos.raw.order_id}</b></> : <> · no order id in the read</>}
          </p>
          {(pos.protection === 'GAP' || pos.protection === 'WARN' || pos.coverage.category === 'PARTIAL') && (
            <Link className="v010-why-go pv2-go" to={stopDeskHref(pos)}
              title={`Stop desk · ${pos.symbol} · ${pos.accountKey} · ${pos.broker}`}>Place stop (Stop management desk) ›</Link>
          )}
          <div className="pv2-va-h"><span>Field</span><span>Value · source</span><span>Age</span></div>
          {fields.map(f => (
            <div className="pv2-va" key={f.field} data-testid="pos-field">
              <span className="f">{f.field}</span><span className="v">{f.value}</span><span className="a">{f.age}</span>
              <span className="p">{f.provenance} {f.needsBackend && <NB short />}</span>
            </div>
          ))}
          <h3 className="pv2-sheet-h">Audit state · this symbol <NB /></h3>
          <p className="v010-why-note">Lifecycle (OPEN / INVESTIGATING / FIXED · UNPROVEN / VALIDATED / MONITORING) needs the change store (LQ-2143).</p>
        </>
      )}
    </Sheet>
  )
}

/** The four measures, exactly as the projection published them. Nothing here is computed, summed or reconciled by
 *  the page: the reconciliation verdict is the wire's own `drill_down.reconciles`, and an unpriced component is
 *  UNKNOWN, never zero. */
export function MeasuresSheet({ open, onClose, measures, nowIso, focus }: {
  open: boolean; onClose: () => void; measures: MeasuresModel; nowIso: string; focus?: MeasureKey | null
}) {
  // A status row opens the sheet at its own measure: the focused measure is drawn first and marked, and the others
  // stay in the page's order so the four are never hidden.
  const list = focus ? [...measures.measures].sort((a, b) => (a.key === focus ? -1 : b.key === focus ? 1 : 0)) : measures.measures
  return (
    <Sheet open={open} onClose={onClose} title="The numbers · four measures" id="sheet-measures">
      <p className="v010-why-note" data-testid="measures-state">
        {measures.state === 'PRESENT'
          ? <><Chip s={measures.dayUnverified ? 'UNVERIFIED' : 'VERIFIED'} label={measures.dayUnverified ? 'DAY FIGURES UNVERIFIED' : 'VERIFIED'} />{' '}
            {measures.contractVersion} · as of {fmtET(measures.asOf, true)} · basis <b>{measures.basis || 'not named'}</b>. {measures.basisWhy}</>
          : <><Chip s="UNKNOWN" label="NOT AVAILABLE" /> {measures.reason || 'the projection published no measures in this read'} <NB /></>}
        <br /><span className="v010-why-age">Read in this page {fmtET(nowIso)} ET · the page computes none of these; GET never computes a verified figure.</span>
      </p>
      {list.map(m => (
        <div key={m.key} data-testid="measure-detail" data-focus={focus === m.key ? 'true' : undefined}>
          <h3 className="pv2-sheet-h">{m.label}</h3>
          <p className="v010-why-note">
            <Chip s={m.status} /> {m.value == null ? 'no value' : fmtUsd(m.value, m.key !== 'account_value')}
            {m.asOf ? <> · as of {fmtET(m.asOf, true)}</> : null}
            <br />{m.text}
          </p>
          {m.definition && <p className="v010-why-age">{m.definition}</p>}
          {m.estimate && (
            <p className="v010-why-note" data-testid="measure-estimate">
              {m.estimate.label}: <b>{fmtUsd(m.estimate.value)}</b>
              {m.estimate.delta != null ? <> · delta vs the anchor {fmtUsd(m.estimate.delta, true)}</> : null}
              {m.estimate.at ? <> · marks {fmtET(m.estimate.at, true)}</> : null}
              <br /><span className="v010-why-age">{m.estimate.note || 'A mark difference between two feeds is not a move and not P&L; it is never added to a today figure.'}</span>
            </p>
          )}
          {m.components.length > 0 && (
            <div className="pv2-va-h"><span>Component</span><span>Value · source</span><span /></div>
          )}
          {m.components.map(c => (
            <div className="pv2-va" key={c.key} data-testid="measure-component">
              <span className="f">{c.label}</span>
              <span className="v">{c.value == null ? 'UNKNOWN' : fmtUsd(c.value, true)}</span>
              <span className="a">{c.note ? 'not 0' : ''}</span>
              {c.note && <span className="p">{c.note}</span>}
            </div>
          ))}
          {m.key === 'account_value_change_1d' && (
            <p className="v010-why-note" data-testid="measure-reconciles">
              Reconciliation: {m.reconciles === true ? <Chip s="OK" label="COMPONENTS RECONCILE" />
                : m.reconciles === false ? <Chip s="WARN" label="DO NOT RECONCILE" />
                  : <Chip s="UNKNOWN" label="NOT PROVEN" />}{' '}
              {m.reconciles == null ? 'the projection did not publish a reconciliation verdict; the page does not compute one.' : null}
            </p>
          )}
          {m.key === 'verified_daily_pnl' && m.value == null && (
            <p className="v010-why-note" data-testid="measure-unverified">
              <b>UNVERIFIED.</b> {UNVERIFIED_NOTE}{m.candidate != null ? ` Candidate ${fmtUsd(m.candidate, true)} is shown beside the known components and is not a verified figure.` : ''}
              {m.gap ? <> {m.gap}</> : null}
            </p>
          )}
          {m.gap && m.key !== 'verified_daily_pnl' && m.value == null && <p className="v010-why-note">Gap: {m.gap}</p>}
        </div>
      ))}
      <h3 className="pv2-sheet-h">Rule</h3>
      <p className="v010-why-note">The broker positions store is the accounting anchor. A broker→Finviz mark difference is a valuation difference between two feeds: it is published beside the anchor with its timestamp and is never added to any “today” measure. Every value above is the projection's; the page does not add, subtract or re-derive one measure from another.</p>
    </Sheet>
  )
}

export function GateEvidenceSheet({ open, onClose, prot, measures, positions, holdings }: {
  open: boolean; onClose: () => void; prot: ProtectionModel; measures: MeasuresModel; positions: PositionModel[]
  holdings?: HoldingsWire | null
}) {
  const gates: GateEvidence[] = gateEvidence(prot, measures, positions, holdings)
  return (
    <Sheet open={open} onClose={onClose} title="Validation gates · evidence" id="sheet-gates">
      <p className="v010-why-note">No gate store is served for Portfolio (scope=portfolio, LQ-2141). A gate is never
        reported open or closed here; each row names the evidence this page can see and what the served gate would
        need. <NB /></p>
      <ul className="v010-why-list">
        {gates.map(g => (
          <li className="v010-why-item" key={g.gate} data-testid="gate-item">
            <div className="v010-why-txt">
              <span className="v010-why-cat">{g.gate}</span>
              <span className="v010-why-detail">Blocks: <b>{g.blocks}</b> · page evidence: {g.pageEvidence}</span>
              <span className="v010-why-age">Threshold: {g.threshold} · Served status: {g.servedStatus} · needs {g.needs} · Owner: {g.owner}</span>
            </div>
            <Chip s="UNKNOWN" label="NOT AVAILABLE" />
          </li>
        ))}
      </ul>
      <p className="v010-why-age">Page evidence is computed from this load only. It is not a served gate result and cannot stand in for one.</p>
    </Sheet>
  )
}

export function SinceLastVisitSheet({ open, onClose, since, visitRecord }: {
  open: boolean; onClose: () => void; since: SinceVisitModel; visitRecord: VisitRecord
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Since your last visit" id="sheet-since">
      <p className="v010-why-note" data-testid="since-state">
        <Chip s={since.status === 'RECORDED' ? 'OK' : 'UNKNOWN'} label={since.status.replace('_', ' ')} /> {since.windowText}
        <br /><span className="v010-why-age">Window basis: {since.windowBasis} · source: /api/v2/ui/prefs/get?key=portfolio.last_seen (LQ-2467)</span>
      </p>
      <div className="pv2-va-h"><span>Field</span><span>Value · source</span><span>Age</span></div>
      <div className="pv2-va"><span className="f">Last visit</span><span className="v">{since.seenAt ? fmtET(since.seenAt, true) : 'not recorded'}</span><span className="a">{since.seenAt ? fmtET(since.seenAt) : '—'}</span>
        <span className="p">Server-stamped (seen_at); a client time is ignored.</span></div>
      <div className="pv2-va"><span className="f">Previous</span><span className="v">{since.previousSeenAt ? fmtET(since.previousSeenAt, true) : 'none'}</span><span className="a">—</span>
        <span className="p">previous_seen_at, copied by the server from the stored seen_at.</span></div>
      <div className="pv2-va"><span className="f">Device</span><span className="v">{since.device || 'not recorded'}</span><span className="a">—</span>
        <span className="p">phone | desktop, the only value the client sends.</span></div>
      <div className="pv2-va"><span className="f">This visit</span><span className="v">{visitRecord}</span><span className="a">—</span>
        <span className="p">Recorded after the page's reads settle; refused when the session is not the operator's or the same-origin check fails.</span></div>
      <h3 className="pv2-sheet-h">The change list <NB /></h3>
      <p className="v010-why-note">What changed since {since.seenAt ? fmtET(since.seenAt, true) : 'the window'} needs the change store
        (LQ-2143): new / fixed-unproven / monitoring labels per holding, with before+after evidence. It is not derived from this
        page's reads.</p>
    </Sheet>
  )
}

export function SyncToolsSheet({ open, onClose, holdings, nowIso, onExportCsv, canExport }: {
  open: boolean; onClose: () => void; holdings: HoldingsWire | null; nowIso: string; onExportCsv: () => void; canExport: boolean
}) {
  const at = (iso: string | null | undefined) => (iso ? `${fmtET(iso, true)} ET` : 'not published')
  return (
    <Sheet open={open} onClose={onClose} title="Sync & export" id="sheet-sync">
      <p className="v010-why-note">This page reads; it never syncs a broker or writes a position. Sync lives on the
        classic page. The only write this page makes is the server-stamped visit (portfolio.last_seen).</p>
      <div className="pv2-va-h"><span>Field</span><span>Value · source</span><span>Age</span></div>
      <div className="pv2-va"><span className="f">Positions</span><span className="v">{at(holdings?.positions_as_of)}</span><span className="a">positions store</span></div>
      <div className="pv2-va"><span className="f">Valuation</span><span className="v">{at(holdings?.valuation_as_of)}</span><span className="a">valuation</span></div>
      <div className="pv2-va"><span className="f">Quotes</span><span className="v">{at(holdings?.quote_as_of)}</span><span className="a">quote cache</span></div>
      <div className="pv2-va"><span className="f">Page read</span><span className="v">{fmtET(nowIso, true)} ET</span><span className="a">this load</span></div>
      <div className="pv2-det pv2-retired"><span>Fidelity GTC stop sync</span><span className="pv2-chip neutral">Retired</span></div>
      <Link className="v010-why-go pv2-go" to="/portfolio-classic" data-testid="sync-classic">Open classic Portfolio (sync, stop audit) ›</Link>
      <Link className="v010-why-go pv2-go" to="/portfolio-classic?tab=Stop+Management">Open the Stop management desk ›</Link>
      <button type="button" className="v010-why-go pv2-go" onClick={onExportCsv} disabled={!canExport} data-testid="sync-export">
        Export the filtered holdings as CSV ›
      </button>
      <p className="v010-why-age">The CSV carries the served columns (shares, resting stop shares, coverage, value, protection,
        identity, reason). It contains no computed P&amp;L: the page has no such figure to export.</p>
    </Sheet>
  )
}

export function RiskSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} title="Risk score · pending decision" id="sheet-risk">
      <p className="v010-why-note" data-testid="risk-state">
        <Chip s="UNKNOWN" label={RISK_SCORE.status} /> <b>{RISK_SCORE.spec}</b>
        <br />{RISK_SCORE.text}
      </p>
      <p className="v010-why-note">Until an approved definition exists, every risk surface on this page (the holdings column,
        the status row, the position sheet) stays empty or says PENDING DECISION. No score, band, letter or colour is
        invented here. <NB /></p>
    </Sheet>
  )
}

export function AuditSheet({ open, onClose, categories, readOk }: { open: boolean; onClose: () => void; categories: AuditCategory[]; readOk: boolean }) {
  return (
    <Sheet open={open} onClose={onClose} title="Audit state · Portfolio" id="sheet-audit">
      <p className="v010-why-note">Raw check failures grouped by category. Lifecycle labels need the change store. <NB /></p>
      {!readOk ? <p className="v010-why-note">Holdings not read: categories UNKNOWN.</p>
        : categories.length === 0 ? <p className="v010-why-note">No open category from this page's reads. Lifecycle history not available. <NB short /></p>
          : (
            <ul className="v010-why-list">
              {categories.map(c => (
                <li className="v010-why-item" key={c.category} data-testid="audit-item">
                  <div className="v010-why-txt">
                    <span className="v010-why-cat">{c.category} · {c.count}</span>
                    {c.symbols.length > 0 && <span className="v010-why-detail">{c.symbols.join(', ')}</span>}
                    <span className="v010-why-age">Source: {c.source} · Owner: {c.owner}</span>
                  </div>
                  <Chip s="UNKNOWN" label="LIFECYCLE NOT AVAILABLE" />
                </li>
              ))}
            </ul>
          )}
    </Sheet>
  )
}
