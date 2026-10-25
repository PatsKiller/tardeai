import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import DeskPage, { DeskGap, useDeskTab } from '../components/DeskPage'
import AmendmentReader from '../components/AmendmentReader'
import { GOVERNANCE, KIND_LABEL, useGovernance, waitingSince, type ApprovalQueue } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'

const tabs = [{ id: 'waiting', label: 'Waiting on you' }, { id: 'POLICY', label: 'Policy' }, { id: 'RELEASE', label: 'Releases' },
  { id: 'SPEND', label: 'Spending caps' }, { id: 'ACTIVATE', label: 'Activations' }, { id: 'DESIGN', label: 'Designs' },
  { id: 'CONFLICT', label: 'Conflicts' }, { id: 'FINANCIAL', label: 'Trade reviews' }, { id: 'history', label: 'Decision history' }]

export default function ApprovalsHub() {
  const { id } = useParams()
  if (id) return <AmendmentReader id={id} />
  return <Queue />
}

function Queue() {
  const [active] = useDeskTab(tabs)
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [active])
  const { data, error, refresh } = useGovernance<ApprovalQueue>(`${GOVERNANCE}/approvals?offset=${offset}&kind=${active === 'waiting' || active === 'history' ? '' : active}`)
  return <div className="approvals"><DeskPage title="Approvals Center" purpose="Everything waiting for your decision. Read the exact version, then decide."
    tabs={tabs} sources={[{ id: 'approvals', label: 'Approval queue', asOf: data?.as_of,
      gap: data?.gaps.length ? 'Some approval sources are unavailable. The total is not yet known.' : undefined }]}
    decisionGap={data?.pending_count === null ? 'The total is unavailable until every source can be checked.' : data ? `${data.pending_count} waiting for review.` : 'Loading the latest queue.'}>
    {active => <div className="stack">
      {error && <DeskGap title="Queue unavailable" reason={error}><button onClick={refresh}>Try again</button></DeskGap>}
      {!data && !error && <p role="status">Loading approvals…</p>}
      {data && <>
        {data.gaps.length > 0 && <DeskGap title="Some sources need attention" reason={`${data.known_pending_count} known items. The full total is unavailable.`}>
          <details><summary>Source details</summary><ul>{data.gaps.map(gap => <li key={gap.source}>{gap.source.replace(/_/g, ' ')}: {gap.reason}</li>)}</ul></details>
        </DeskGap>}
        {active === 'history' ? <section className="panel"><h2>Decision history</h2>{data.recent.length ? data.recent.map((record, i) => <article key={i} className="rule">
          <strong>{record.decision.replace(/_/g, ' ')}</strong><p>{record.actor} · {new Date(record.at).toLocaleString()}</p>
          <details><summary>Exact version and comment</summary><code>{record.document_sha}</code><p>{record.comment}</p></details>
        </article>) : <p>No recorded decisions were returned.</p>}</section> : <div className="columns">
          <section className="panel" aria-label="Waiting approvals">
            {data.items.filter(item => active === 'waiting' || item.kind === active).map(item => <article className="queue-row" key={item.id}>
              <span className="badge">{KIND_LABEL[item.kind] ?? item.kind}</span><div><h2>{item.title}</h2><p className="muted">{item.version || 'Exact document available in the reader'}</p></div>
              <span>{item.proposed_by ?? 'Proposer not recorded'}</span><span className="muted">{waitingSince(item.created_at)}</span>
              <Link className="primary" to={`/approvals/${encodeURIComponent(item.id)}`}>Read &amp; decide</Link>
            </article>)}
            {!data.items.some(item => active === 'waiting' || item.kind === active) && <p>No items in this view. {data.complete ? '' : 'Some sources are still unavailable.'}</p>}
            <div className="toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
              <button disabled={offset + 50 >= data.filtered_count} onClick={() => setOffset(offset + 50)}>Next</button></div>
          </section>
          <aside className="stack"><section className="panel"><h2>How a decision is recorded</h2><p>Your authenticated tailnet identity, the exact version you read, and the time are recorded together. Agents can propose and read; they cannot decide.</p></section>
            <section className="panel"><h2>Decided recently</h2>{data.recent.slice(0, 5).map((record, i) => <p key={i}>{record.decision.replace(/_/g, ' ')} · {new Date(record.at).toLocaleDateString()}</p>)}
              <Link className="primary" to="/approvals?tab=history">Full decision history</Link></section>
            <section className="panel"><h2>Notify me</h2><p className="muted">Approval notification delivery and its schedule have not been verified yet.</p></section>
            <section className="panel"><h2>Rulebook</h2><p>Read the rules, ask questions, and propose changes.</p><Link className="primary" to="/policy">Open Rulebook</Link></section>
            <section className="panel"><h2>Conflict rules</h2><p>How disagreements between sources are decided, and AI-proposed rules waiting for you.</p><Link className="primary" to="/conflicts/rules">How conflicts are decided →</Link></section>
          </aside>
        </div>}
      </>}
    </div>}
  </DeskPage></div>
}
