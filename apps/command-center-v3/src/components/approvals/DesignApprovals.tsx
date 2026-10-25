import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MobileDetailSheet, useMobilePageDetail } from '../MobileDetailSheet'
import DesignThumb from './DesignThumb'
import { DESIGN_API, canSubmit, decidedAt, designRequest, newRequestId, thumbsFor, type DesignQueue, type ProposedDesign } from '../../lib/designApprovals'
import '../../styles/designApprovals.css'

const DECIDED_EVENT = 'design-decided'

export function useDesignQueue() {
  const [data, setData] = useState<DesignQueue | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(n => n + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    designRequest<DesignQueue>(`${DESIGN_API}/approvals`, undefined, controller.signal).then(setData)
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [revision])
  useEffect(() => {
    window.addEventListener(DECIDED_EVENT, refresh)
    return () => window.removeEventListener(DECIDED_EVENT, refresh)
  }, [refresh])
  return { data, error, refresh }
}

/** Approvals → Designs: PROPOSED page versions with their private mockups and one-tap Approve / Reject. */
export default function DesignApprovals({ onDecided }: { onDecided?: () => void }) {
  const { data, error, refresh } = useDesignQueue()
  const detail = useMobilePageDetail('design')
  const [openId, setOpenId] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const selected = data?.proposed.find(d => d.id === (detail.mobile ? detail.id : openId)) ?? null
  // One shared refresh: this list and Board 19's "Decided recently" re-read; the decided card leaves the queue.
  const decided = (message: string) => { setNotice(message); setOpenId(null); window.dispatchEvent(new Event(DECIDED_EVENT)); onDecided?.() }
  return <section className="design-approvals" aria-label="Design versions waiting for you" data-testid="design-approvals">
    <h2 className="design-heading">Page designs waiting for you</h2>
    {error && <p className="design-status error" role="alert">{error} <button type="button" onClick={refresh}>Try again</button></p>}
    {notice && <p className="design-status" role="status" data-testid="design-decided-notice">{notice}</p>}
    {!data && !error && <p role="status">Loading designs…</p>}
    {data && <>
      {data.gaps.length > 0 && <p className="design-status" role="status">Some design sources are unavailable: {data.gaps.map(g => g.reason).join('; ')}</p>}
      {data.proposed.length === 0 && <p className="muted">No page design versions are waiting for a decision.</p>}
      {data.proposed.map(card => <article key={card.id} className="design-card" data-testid="design-card">
        <div className="design-meta"><span className="badge">Design</span><span>{card.page_title} · {card.version}</span>
          <span>Proposed {decidedAt(card.created)}{card.proposed_by ? ` by ${card.proposed_by}` : ''}</span></div>
        <h3>{card.title}</h3>
        <p className="design-status">{card.removals.length ? `${card.removals.length} removal, hide or move listed` : 'No removals, hides or moves listed'}</p>
        {detail.mobile
          ? <button type="button" className="primary" onClick={() => detail.open(card.id)}>Review {card.version}</button>
          : openId === card.id
            ? <><DesignDetail card={card} canDecide={data.can_decide} onDecided={decided} /><button type="button" onClick={() => setOpenId(null)}>Close review</button></>
            : <button type="button" className="primary" onClick={() => setOpenId(card.id)}>Review {card.version}</button>}
      </article>)}
      {data.dsn_proposed.length > 0 && <section className="design-card" aria-label="Design documents waiting for you">
        <h3>Design documents (docs/designs)</h3>
        {data.dsn_proposed.map(d => <div key={d.id} className="design-meta" style={{ justifyContent: 'space-between' }}>
          <span>{d.title}</span><Link className="primary" to={d.href}>Read &amp; decide</Link></div>)}
      </section>}
      <p className="muted">{data.signature}.</p>
    </>}
    {detail.mobile && selected && <MobileDetailSheet title={`${selected.page_title} ${selected.version}`} onBack={detail.close}>
      <div className="approvals design-approvals"><DesignDetail card={selected} canDecide={!!data?.can_decide} onDecided={message => { decided(message); detail.close() }} /></div>
    </MobileDetailSheet>}
  </section>
}

function DesignDetail({ card, canDecide, onDecided }: { card: ProposedDesign; canDecide: boolean; onDecided: (message: string) => void }) {
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [failed, setFailed] = useState(false)
  const submit = async (decision: 'APPROVE' | 'REJECT') => {
    if (!canSubmit(decision, reason, busy)) return
    setBusy(true); setNotice(''); setFailed(false)
    try {
      await designRequest(`${DESIGN_API}/decide`, { page: card.page, version: card.version, fingerprint: card.fingerprint,
        decision, reason: decision === 'REJECT' ? reason : '', request_id: newRequestId() })
      onDecided(`${card.page_title} ${card.version} ${decision === 'APPROVE' ? 'approved' : 'rejected'} and recorded in the decisions ledger.`)
    } catch (err) { setNotice((err as Error).message); setFailed(true) } finally { setBusy(false) }
  }
  return <div className="stack" data-testid="design-detail">
    <div className="design-thumbs">{thumbsFor(card.images).map(t => <DesignThumb key={t.width} page={card.page} version={card.version} width={t.width} image={t.image} />)}</div>
    <section aria-label="Removals, hides and moves"><h3 className="design-subheading">Removals, hides and moves</h3>
      {card.removals.length ? <ul className="design-removals">{card.removals.map((r, i) => <li key={i}>{r.action} {r.kind} “{r.label}”</li>)}</ul>
        : <p className="muted">This version lists none.</p>}</section>
    <details><summary>Full design spec</summary><pre>{card.spec}</pre></details>
    {notice && <p className={`design-status${failed ? ' error' : ''}`} role={failed ? 'alert' : 'status'}>{notice}</p>}
    {!canDecide ? <p className="muted">Only your authenticated operator session can approve or reject a design.</p>
      : rejecting ? <div className="stack"><label>Why are you rejecting it?<textarea aria-label="Reject reason" value={reason} onChange={e => setReason(e.target.value)} /></label>
        <div className="design-actions"><button type="button" className="design-reject" disabled={!canSubmit('REJECT', reason, busy)} onClick={() => submit('REJECT')}>{busy ? 'Recording…' : `Reject ${card.version}`}</button>
          <button type="button" disabled={busy} onClick={() => setRejecting(false)}>Cancel</button></div></div>
        : <div className="design-actions"><button type="button" className="design-approve" disabled={busy} onClick={() => submit('APPROVE')}>{busy ? 'Recording…' : `Approve ${card.version}`}</button>
          <button type="button" className="design-reject" disabled={busy} onClick={() => setRejecting(true)}>Reject…</button></div>}
  </div>
}
