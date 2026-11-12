// Portfolio v002 full-screen sheets: why-protection (GAP / WARN / UNKNOWN / OK), position detail with per-field
// source/writer/age, and audit state. Same shell and classes as Home v010's WhySheet (reused, not edited).
import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import '../../home/v010' // loads the Home v010 WhySheet styles this shell reuses
import {
  fmtET, fmtUsd, fmtPct, positionFields, STOP_OWNER,
  type AuditCategory, type HoldingsWire, type PositionModel, type ProtectionModel,
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

export function ProtectionWhySheet({ open, onClose, prot, nowIso, onGoTo }: {
  open: boolean; onClose: () => void; prot: ProtectionModel; nowIso: string; onGoTo: (id: string) => void
}) {
  const v = prot.verdict
  const title = v === 'OK' ? 'Is everything protected?' : 'Why is protection not OK?'
  const notProtected = (prot.gap ?? 0) + (prot.warn ?? 0) + (prot.unknown ?? 0)
  const gap = prot.action.filter(p => p.protection === 'GAP')
  const warn = prot.action.filter(p => p.protection === 'WARN')
  const unk = prot.action.filter(p => p.protection === 'UNKNOWN')
  const causes = [...new Set(unk.map(p => p.cause || 'Protection Unknown'))]
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
          {gap.length > 0 && <WhyItem n={1} cat={`Unprotected position · ${gap.length}`} chip="GAP" detail={`${gap.map(p => p.symbol).join(', ')}: a good read shows no resting stop.`}
            src={`Source: stop store · Owner: ${STOP_OWNER}`} go="Go to the positions" onGo={() => onGoTo('card-protect')} />}
          {warn.length > 0 && <WhyItem n={2} cat={`Expired stop · ${warn.length}`} chip="WARN" detail={`${warn.map(p => p.symbol).join(', ')}: protection existed but the stop expired (never OK).`}
            src={`Source: stop store · Owner: ${STOP_OWNER}`} go="Go to the positions" onGo={() => onGoTo('card-protect')} />}
          {unk.length > 0 && <WhyItem n={3} cat={`Protection unknown · ${unk.length}`} chip="UNKNOWN" detail={`${unk.map(p => p.symbol).join(', ')}: protection cannot be verified. Never drawn as NO STOP.`}
            src={`Cause: ${causes.join(', ')} · Source: stop store · Owner: ${STOP_OWNER}`} go="Go to the positions" onGo={() => onGoTo('card-protect')} />}
          {prot.counted == null && <WhyItem n={1} cat={`Holdings ${v}`} chip={v} detail={prot.cause || 'The holdings read did not complete.'} src="Source: /api/v2/portfolio/holdings" />}
          <WhyItem n={4} cat="Open validation gate" chip="UNKNOWN" detail="Gate store not served for Portfolio." src="Source: gate store · Owner: validation lane" nb />
        </ol>
      )}
      <h3 className="pv2-sheet-h">Counted</h3>
      <p className="v010-why-note">{prot.counted ?? '—'} positions at or above $100. {prot.listedNotCounted ?? '—'} under $100 are listed, not counted; {prot.exempt ?? '—'} cash / money-market / exempt rows are not counted.</p>
      <h3 className="pv2-sheet-h">Rule</h3>
      <p className="v010-why-note">OK only when every counted position, broker and stop source was read and every counted position has a verified resting stop (a pending-activation GTC stop counts). GAP when a good read shows no resting stop. An expired stop is WARN. Any unread broker or source gives UNKNOWN, never OK.</p>
    </Sheet>
  )
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
          <p className="v010-why-note"><b>{fmtUsd(pos.value)}</b> {fmtPct(pos.dayPct)} today</p>
          <p className="v010-why-note" data-testid="pos-protection">
            <Chip s={pos.protection === 'GAP' ? 'GAP' : pos.protection === 'WARN' ? 'WARN' : pos.protection === 'PROTECTED' ? 'OK' : 'UNKNOWN'} label={pos.chip} />{' '}
            {pos.reason}{pos.cause ? ` · Cause: ${pos.cause}` : ''}{!pos.counted ? ' · listed, not counted' : ''}
          </p>
          {(pos.protection === 'GAP' || pos.protection === 'WARN') && (
            <Link className="v010-why-go pv2-go" to={`/portfolio-classic?tab=Stop+Management&symbol=${encodeURIComponent(pos.symbol)}`}>Place stop (Stop management desk) ›</Link>
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
